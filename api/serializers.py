"""
Serializers for /api/v1/.

TWO RULES RUN THROUGH ALL OF THESE

1. The supplier link never leaves the building. ``Product.source_url`` is where
   the goods are bought; publishing it to a customer is publishing how to skip
   us. It appears only in the staff serializer, and the customer/public ones do
   not merely hide it - they never load it into the representation, so there is
   nothing to leak through a debug view or a cached response.

2. Money is a string, never a float. ``DecimalField`` is serialised as a string
   because JSON numbers are IEEE-754 doubles: 0.1 + 0.2 is famously not 0.3, and
   a price that round-trips through a float can come back a hundredth out. Every
   consumer should parse these with a decimal type, not a float.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from decimal import Decimal

from customers.models import Customer
from khata.models import LedgerEntry
from orders.models import PAYMENT_STATUS_CHOICES, Order, OrderItem
from products.models import (Category, Product, ProductTag, ProductAttribute, ProductImage,
                             ProductVariant, SubCategory)
from accounts.models import AuditLog
from noon_labels.models import LabelBatch
from orders.models import Notification, ShipmentStatus
from portal.models import (BlogCategory, BlogPost, ContactMessage,
                           PortfolioItem, ProductRequest, ProductRequestImage)
from products.models import PriceAdjustment
from settings_manager.models import ShippingCompany
from support.models import Ticket, TicketMessage


# ---------------------------------------------------------------------------
# CATALOGUE
# ---------------------------------------------------------------------------

class SubCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubCategory
        fields = ['id', 'name', 'slug']


class CategorySerializer(serializers.ModelSerializer):
    subcategories = SubCategorySerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'is_active', 'subcategories']


class ProductTagSerializer(serializers.ModelSerializer):
    """
    A cross-cutting product label.

    `slug` is read-only on purpose. It is what the ?tag= filter carries, so a
    bookmarked or shared filtered view has to survive somebody fixing a typo in
    the name - see products.views.tag_save, which applies the same rule.
    """

    product_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProductTag
        fields = ['id', 'name', 'slug', 'colour', 'product_count', 'created_at']
        read_only_fields = ['slug', 'created_at', 'product_count']


class ProductImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ['id', 'url']

    @extend_schema_field(serializers.URLField())
    def get_url(self, obj):
        """
        Absolute URL for the image, whichever way it is stored.

        ``src`` resolves a locally uploaded file first and a remote CDN URL
        second. A relative MEDIA path is made absolute against the request,
        because an API consumer is not necessarily on this origin and cannot
        resolve '/media/...' on its own.
        """
        src = getattr(obj, 'src', '') or ''
        if not src:
            return ''
        if src.startswith(('http://', 'https://')):
            return src
        request = self.context.get('request')
        return request.build_absolute_uri(src) if request else src


class ProductVariantSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ['id', 'name', 'price', 'stock', 'sku', 'image', 'sort_order', 'is_active']

    @extend_schema_field(serializers.URLField())
    def get_image(self, obj):
        src = getattr(obj, 'src', '') or ''
        if not src or src.startswith(('http://', 'https://')):
            return src
        request = self.context.get('request')
        return request.build_absolute_uri(src) if request else src


class ProductVariantWriteSerializer(serializers.ModelSerializer):
    """
    Create and edit a variation.

    Separate from the read serializer above because that one exposes `image` as
    a computed URL - useful to a client, impossible to write to. This one takes
    `product`, which the read serializer omits because a variation is always
    fetched in the context of its parent and repeating the id is noise.
    """

    class Meta:
        model = ProductVariant
        fields = ['id', 'product', 'name', 'price', 'stock', 'sku',
                  'sort_order', 'is_active']

    def validate_price(self, value):
        # The customer pays the VARIANT price, so a zero here is a free product
        # rather than a product with no price set.
        if value is None or value <= 0:
            raise serializers.ValidationError('Price must be greater than zero.')
        return value


class OrderLineSerializer(serializers.Serializer):
    """One line of a new order."""

    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    variant = serializers.PrimaryKeyRelatedField(
        queryset=ProductVariant.objects.all(), required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1)
    # Optional: left out, the line is priced from the catalogue. Sent, it
    # overrides — a negotiated price on one order must not rewrite the listing,
    # which is exactly what editing the product would do.
    price = serializers.DecimalField(max_digits=10, decimal_places=2,
                                     required=False, allow_null=True)

    def validate(self, attrs):
        variant = attrs.get('variant')
        if variant is not None and variant.product_id != attrs['product'].id:
            raise serializers.ValidationError(
                'That variation belongs to a different product.')
        return attrs


class OrderCreateSerializer(serializers.Serializer):
    """
    Create an order and its lines in one request.

    WHY A PLAIN SERIALIZER

    An Order is not one row. It is a row plus N OrderItems, and the total is
    derived from those items — so a ModelSerializer over Order would either
    expose `total` as writable (letting a client invent it) or create empty
    orders that have to be filled in by a second call. Both are worse than
    taking the whole thing at once.

    The TOTAL IS COMPUTED HERE, never accepted. It is the number the customer
    is billed, and the client asking for it is the one thing that must not
    decide it.
    """

    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    items = OrderLineSerializer(many=True)
    status = serializers.ChoiceField(
        choices=Order.STATUS_CHOICES, required=False, default=Order.STATUS_DRAFT)
    payment_status = serializers.ChoiceField(
        choices=PAYMENT_STATUS_CHOICES, required=False, default='unpaid')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    shipping_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, default=0)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError('An order needs at least one item.')
        return value

    def create(self, validated):
        from django.db import transaction

        lines = validated.pop('items')
        # Atomic: an order that exists with half its lines is worse than one
        # that failed outright, because the half is invisible until somebody
        # opens it and the total looks plausible.
        with transaction.atomic():
            order = Order.objects.create(
                customer=validated['customer'],
                status=validated.get('status', Order.STATUS_DRAFT),
                payment_status=validated.get('payment_status', 'unpaid'),
                notes=validated.get('notes', ''),
                shipping_cost=validated.get('shipping_cost') or 0,
            )

            total = Decimal('0')
            for line in lines:
                product = line['product']
                variant = line.get('variant')
                # Priced from the variation when there is one: that is what the
                # customer actually buys, and the parent price is often just the
                # cheapest of them.
                price = line.get('price')
                if price is None:
                    price = variant.price if variant is not None else product.price
                price = Decimal(str(price))

                OrderItem.objects.create(
                    order=order, product=product, variant=variant,
                    quantity=line['quantity'], price=price,
                )
                total += price * line['quantity']

            order.total = total + Decimal(str(validated.get('shipping_cost') or 0))
            order.save(update_fields=['total'])
        return order

    def to_representation(self, instance):
        # The tracking number is generated in Order.save(), so it only exists
        # after the row is written - and it is the one thing the caller needs
        # back, because it is how the customer will follow the shipment.
        return {
            'id': instance.id,
            'tracking_number': instance.tracking_number,
            'customer': instance.customer_id,
            'customer_name': instance.customer.name,
            'total': str(instance.total),
            'status': instance.status,
            'payment_status': instance.payment_status,
            'items': instance.items.count(),
        }


class ProductAttributeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductAttribute
        fields = ['id', 'name', 'value', 'sort_order']


class ProductPublicSerializer(serializers.ModelSerializer):
    """
    What anyone may see: the catalogue as it appears on the website.

    Deliberately absent: source_url, and the internal cost fields. See rule 1 in
    the module docstring.
    """

    images = ProductImageSerializer(many=True, read_only=True)
    variants = serializers.SerializerMethodField()
    attributes = ProductAttributeSerializer(many=True, read_only=True)
    category = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    subcategory = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'sku', 'price', 'moq', 'weight',
            'carton_length', 'carton_width', 'carton_height', 'carton_qty',
            'category', 'subcategory', 'ready_to_ship', 'is_draft',
            'images', 'variants', 'attributes', 'url',
        ]

    @extend_schema_field(ProductVariantSerializer(many=True))
    def get_variants(self, obj):
        """Only active variants: an inactive one is retired, not orderable."""
        active = [v for v in obj.variants.all() if v.is_active]
        return ProductVariantSerializer(active, many=True, context=self.context).data

    @extend_schema_field(serializers.URLField())
    def get_url(self, obj):
        request = self.context.get('request')
        try:
            path = obj.get_absolute_url()
        except Exception:
            return ''
        return request.build_absolute_uri(path) if request else path


class ProductStaffSerializer(ProductPublicSerializer):
    """Everything the public serializer has, plus what only staff may see."""

    class Meta(ProductPublicSerializer.Meta):
        fields = ProductPublicSerializer.Meta.fields + [
            'source_url', 'price_air', 'price_sea', 'is_private', 'source',
        ]


class ProductWriteSerializer(serializers.ModelSerializer):
    """
    Create and update. Separate from the read serializers because the nested
    images/variants/attributes above are read-only projections, and letting a
    writer post into them would silently do nothing.
    """

    category = serializers.SlugRelatedField(
        slug_field='slug', queryset=Category.objects.all(),
        required=False, allow_null=True,
    )
    subcategory = serializers.SlugRelatedField(
        slug_field='slug', queryset=SubCategory.objects.all(),
        required=False, allow_null=True,
    )

    class Meta:
        model = Product
        # `slug` is read-only but present: ProductViewSet looks up by slug, so a
        # caller that creates a product needs it back to address the row it has
        # just made. Returning only `id` leaves it holding a key that does not
        # open the door.
        read_only_fields = ['slug']
        fields = [
            'id', 'slug', 'name', 'sku', 'price', 'price_air', 'price_sea', 'moq', 'weight',
            'carton_length', 'carton_width', 'carton_height', 'carton_qty',
            'category', 'subcategory', 'source', 'source_url',
            'ready_to_ship', 'is_draft', 'is_private', 'tags',
        ]

    def validate_price(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Price must be greater than zero.')
        return value

    def validate_moq(self, value):
        if value is not None and value < 1:
            raise serializers.ValidationError('MOQ must be at least 1.')
        return value

    def validate_source_url(self, value):
        """
        Store the canonical form of a supplier link.

        The same 1688 offer arrives as several different strings depending on
        tracking parameters and host. Canonicalising on write is what lets
        duplicate detection compare them at all - see products/source_url.py.
        """
        from products.source_url import canonical_source_url
        return canonical_source_url(value)[:500]


# ---------------------------------------------------------------------------
# CUSTOMERS
# ---------------------------------------------------------------------------

class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['id', 'name', 'phone', 'email', 'address', 'is_active', 'created_at']
        read_only_fields = ['created_at']


class CustomerSelfSerializer(serializers.ModelSerializer):
    """
    A customer's own record.

    is_active is read-only here: an account must not be able to deactivate or
    reactivate itself through the API, which would be either a support problem or a
    way back in after being switched off.
    """

    class Meta:
        model = Customer
        fields = ['id', 'name', 'phone', 'email', 'address', 'is_active']
        read_only_fields = ['id', 'email', 'is_active']


# ---------------------------------------------------------------------------
# ORDERS
# ---------------------------------------------------------------------------

class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'product_name', 'variant', 'quantity', 'price']
        # price is what was agreed when the order was placed. It is stored on the
        # row precisely so that later catalogue price changes cannot rewrite
        # history, and exposing it as writable here would undo that guarantee.
        read_only_fields = ['price']


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True)

    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


# ---------------------------------------------------------------------------
# LEDGER
# ---------------------------------------------------------------------------

class LedgerEntrySerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)

    class Meta:
        model = LedgerEntry
        fields = ['id', 'customer', 'customer_name', 'entry_type', 'amount',
                  'currency', 'date', 'description', 'order']

    def validate_amount(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value


# ---------------------------------------------------------------------------
# SUPPORT
# ---------------------------------------------------------------------------

class TicketMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketMessage
        fields = '__all__'
        read_only_fields = ['created_at']


class TicketSerializer(serializers.ModelSerializer):
    messages = TicketMessageSerializer(many=True, read_only=True)

    class Meta:
        model = Ticket
        fields = '__all__'
        # customer and created_by are set by the view from the authenticated
        # caller, never from the request body. Left writable - which is what
        # fields='__all__' does by default - a customer could POST another
        # customer's id and file a ticket attributed to them, or set created_by
        # to a staff account. Ownership must come from the credential, not from
        # a field the caller controls.
        read_only_fields = ['created_at', 'updated_at', 'customer', 'created_by']


# ---------------------------------------------------------------------------
# IDENTITY
# ---------------------------------------------------------------------------

class MeSerializer(serializers.Serializer):
    """
    Shape of GET /api/v1/me/.

    Declared rather than inferred so the generated schema documents it. A plain
    APIView returning a dict gives drf-spectacular nothing to describe, and the
    endpoint every client calls first would be the one endpoint with no
    documented response.
    """

    username = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
    full_name = serializers.CharField(allow_blank=True)
    role = serializers.CharField()
    is_back_office = serializers.BooleanField()
    modules = serializers.DictField(
        child=serializers.BooleanField(),
        help_text='Which back-office modules this token may reach.',
    )
    customer = CustomerSelfSerializer(allow_null=True)


# ---------------------------------------------------------------------------
# PRODUCT REQUESTS  (a customer asking us to source something)
# ---------------------------------------------------------------------------

class ProductRequestImageSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True)

    class Meta:
        model = ProductRequestImage
        fields = ['id', 'image', 'uploaded_at']


class ProductRequestSerializer(serializers.ModelSerializer):
    images = ProductRequestImageSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True)

    class Meta:
        model = ProductRequest
        fields = ['id', 'customer', 'customer_name', 'name', 'description',
                  'product_link', 'requested_quantity', 'status', 'admin_notes',
                  'converted_product', 'images', 'created_at', 'updated_at']
        # customer comes from the token, never the body - the same ownership rule
        # as tickets. status, admin_notes and converted_product are the staff side
        # of the conversation: a customer able to set their own request to
        # "approved" would be answering their own question.
        read_only_fields = ['customer', 'status', 'admin_notes',
                            'converted_product', 'created_at', 'updated_at']


class ProductRequestStaffSerializer(ProductRequestSerializer):
    """Staff may move a request through its workflow."""

    class Meta(ProductRequestSerializer.Meta):
        read_only_fields = ['customer', 'created_at', 'updated_at']


# ---------------------------------------------------------------------------
# ORDER TRACKING
# ---------------------------------------------------------------------------

class ShipmentStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShipmentStatus
        fields = ['id', 'order', 'shipment_no', 'status', 'note', 'updated_at']


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'order', 'message', 'notification_type', 'is_read', 'created_at']
        # Everything except is_read: a client marks a notification read, it does
        # not author one.
        read_only_fields = ['id', 'order', 'message', 'notification_type', 'created_at']


class OrderStatusUpdateSerializer(serializers.ModelSerializer):
    """
    The only writable slice of an Order, for staff.

    Deliberately narrow. Exposing the whole model would let a caller rewrite
    total, commission_amount or the line prices - the figures the customer
    agreed to. Those are set at checkout and are not an API concern.
    """

    class Meta:
        model = Order
        fields = ['id', 'status', 'payment_status', 'is_placed', 'notes',
                  'shipping_cost', 'other_cost', 'other_cost_reason',
                  'total_weight', 'total_cbm', 'cargo_type', 'shipping_method']


# ---------------------------------------------------------------------------
# PUBLIC CONTENT
# ---------------------------------------------------------------------------

class BlogCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogCategory
        fields = ['id', 'name', 'slug', 'description', 'display_order']


class BlogPostListSerializer(serializers.ModelSerializer):
    """Listing shape: no body, which is the whole article."""

    category = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    author = serializers.CharField(source='display_author', read_only=True)

    class Meta:
        model = BlogPost
        fields = ['id', 'title', 'slug', 'category', 'excerpt', 'author',
                  'hero_image', 'hero_image_alt', 'reading_minutes',
                  'is_featured', 'published_at', 'updated_at']


class BlogPostDetailSerializer(BlogPostListSerializer):
    class Meta(BlogPostListSerializer.Meta):
        fields = BlogPostListSerializer.Meta.fields + ['body', 'keywords', 'meta_description']


class PortfolioItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioItem
        fields = ['id', 'title', 'description', 'media_type', 'file',
                  'display_order', 'created_at']


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ['id', 'name', 'email', 'phone', 'subject', 'message', 'created_at']
        read_only_fields = ['id', 'created_at']


# ---------------------------------------------------------------------------
# STAFF-ONLY RECORDS
# ---------------------------------------------------------------------------

class PriceAdjustmentSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True, default='')
    difference = serializers.SerializerMethodField()

    class Meta:
        model = PriceAdjustment
        fields = ['id', 'user_name', 'percentage', 'scope', 'scope_label',
                  'products_affected', 'variants_affected', 'total_before',
                  'total_after', 'difference', 'excluded_private', 'created_at']

    @extend_schema_field(serializers.CharField())
    def get_difference(self, obj):
        return str(obj.difference)


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True, default='')

    class Meta:
        model = AuditLog
        fields = ['id', 'user_name', 'action', 'target', 'detail',
                  'ip_address', 'created_at']


class LabelBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabelBatch
        fields = '__all__'
        read_only_fields = ['created_at']


class ShippingCompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = ShippingCompany
        fields = '__all__'


class CompanyInfoSerializer(serializers.Serializer):
    """
    The public face of CompanySettings.

    A deliberate allowlist, not the model. CompanySettings holds three sets of
    SMTP credentials, the WhatsApp number, freight rates and commission
    percentages - serialising the model would publish the lot.
    """

    company_name = serializers.CharField()
    currency = serializers.CharField()
    currency_symbol = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)
