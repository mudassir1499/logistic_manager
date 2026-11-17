"""
Cart and checkout for API clients.

SCOPING: every queryset here is filtered to ``request.user.profile.customer``
before anything else. A cart item id is a small integer and guessable, so if the
filter were on the caller's word rather than their credential, one customer
could read, re-quantity or delete another's cart.

CHECKOUT does not build an order itself - it calls
``portal.checkout.create_order_from_cart``, the same function the website's
checkout uses. See the note at the top of that module for why there is exactly
one implementation.
"""

from decimal import Decimal

from drf_spectacular.utils import (OpenApiResponse, extend_schema,
                                   extend_schema_field)
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from portal.checkout import cart_totals, create_order_from_cart, requires_labels
from portal.models import CartItem
from products.models import Product, ProductVariant
from settings_manager.models import CompanySettings

from .permissions import IsCustomer, profile_of
from .serializers import OrderSerializer


class CartItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    variant_name = serializers.CharField(source='variant.name', read_only=True, default=None)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    line_total = serializers.SerializerMethodField()
    needs_labels = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ['id', 'product', 'product_name', 'variant', 'variant_name',
                  'quantity', 'unit_price', 'line_total', 'needs_labels',
                  'label_mark', 'carton_mark', 'carton_asn', 'carton_quantity']

    @extend_schema_field(serializers.CharField())
    def get_line_total(self, obj):
        """Quantity times unit price, as a string. See the money note in serializers.py."""
        return str((obj.unit_price * obj.quantity).quantize(Decimal('0.01')))

    @extend_schema_field(serializers.BooleanField())
    def get_needs_labels(self, obj):
        """
        Whether this line cannot be checked out without label details.

        Surfaced per line so an app can ask for them at the right moment rather
        than discovering it as a validation error on the checkout call.
        """
        return requires_labels(obj.product)


class AddToCartSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    variant = serializers.PrimaryKeyRelatedField(
        queryset=ProductVariant.objects.all(), required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        product = attrs['product']
        variant = attrs.get('variant')

        # A draft or private product is not orderable. Without this check a
        # customer who learned an id could add one to their cart and check out.
        if product.is_draft or product.is_private:
            raise serializers.ValidationError({'product': 'That product is not available to order.'})

        if variant is not None:
            if variant.product_id != product.id:
                raise serializers.ValidationError(
                    {'variant': 'That variation belongs to a different product.'})
            if not variant.is_active:
                raise serializers.ValidationError({'variant': 'That variation is no longer available.'})

        moq = product.moq or 1
        if attrs['quantity'] < moq:
            raise serializers.ValidationError(
                {'quantity': f'Minimum order quantity for this product is {moq}.'})
        return attrs


class CartViewSet(viewsets.ModelViewSet):
    """The signed-in customer's cart."""

    serializer_class = CartItemSerializer
    permission_classes = [IsCustomer]
    pagination_class = None          # a cart is short; paging it helps nobody
    throttle_scope = 'read'

    def get_queryset(self):
        profile = profile_of(self.request)
        if profile is None or not profile.customer_id:
            return CartItem.objects.none()
        return (
            CartItem.objects
            .filter(customer_id=profile.customer_id)
            .select_related('product', 'variant')
            .order_by('id')
        )

    def get_serializer_class(self):
        if self.action == 'create':
            return AddToCartSerializer
        return CartItemSerializer

    def get_throttles(self):
        self.throttle_scope = 'read' if self.request.method in ('GET', 'HEAD', 'OPTIONS') else 'write'
        return super().get_throttles()

    def create(self, request, *args, **kwargs):
        """
        Add to the cart, or increase the quantity if it is already there.

        Adding the same product twice produces one line with a larger quantity
        rather than two identical lines - which is what a customer means, and
        what the website's add-to-cart already does.
        """
        serializer = AddToCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        profile = profile_of(request)

        existing = CartItem.objects.filter(
            customer_id=profile.customer_id,
            product=data['product'],
            variant=data.get('variant'),
        ).first()

        if existing is not None:
            existing.quantity += data['quantity']
            existing.save(update_fields=['quantity', 'updated_at'])
            item = existing
        else:
            item = CartItem.objects.create(
                customer_id=profile.customer_id,
                product=data['product'],
                variant=data.get('variant'),
                quantity=data['quantity'],
            )

        return Response(
            CartItemSerializer(item, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )


class CartSummaryView(APIView):
    """
    What the cart comes to, using the same arithmetic checkout will apply.

    Exists so an app can show a total without reimplementing the commission
    calculation and disagreeing with the server by a cent.
    """

    permission_classes = [IsCustomer]
    throttle_scope = 'read'

    @extend_schema(summary='Cart totals', responses={200: OpenApiResponse(
        description='subtotal, commission_percentage, commission_amount, total, currency, item_count')})
    def get(self, request):
        profile = profile_of(request)
        items = list(
            CartItem.objects
            .filter(customer_id=profile.customer_id)
            .select_related('product', 'variant')
        )
        settings = CompanySettings.get_settings()
        totals = cart_totals(items, settings)
        return Response({
            'item_count': len(items),
            'currency': settings.currency,
            'subtotal': str(totals['subtotal']),
            'commission_percentage': str(totals['commission_percentage']),
            'commission_amount': str(totals['commission_amount']),
            'total': str(totals['total']),
        })


class CheckoutSerializer(serializers.Serializer):
    """
    Optional per-line label details, keyed by cart item id.

    Example: {"lines": {"12": {"label_mark": "FBA15", "carton_mark": "CTN-1"}}}
    """

    lines = serializers.DictField(child=serializers.DictField(), required=False, default=dict)


class CheckoutView(APIView):
    """Turn the cart into an order."""

    permission_classes = [IsCustomer]
    throttle_scope = 'write'

    @extend_schema(
        summary='Place an order from the cart',
        request=CheckoutSerializer,
        responses={201: OrderSerializer,
                   400: OpenApiResponse(description='Empty cart, or missing label details')},
    )
    def post(self, request):
        profile = profile_of(request)
        items = (
            CartItem.objects
            .filter(customer_id=profile.customer_id)
            .select_related('product', 'variant')
        )
        if not items.exists():
            return Response({'detail': 'Your cart is empty.'},
                            status=status.HTTP_400_BAD_REQUEST)

        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_lines = serializer.validated_data.get('lines') or {}

        line_extras = {}
        missing = []
        for item in items:
            # JSON object keys are strings; cart item ids are integers.
            supplied = raw_lines.get(str(item.id)) or raw_lines.get(item.id) or {}
            label_mark = (supplied.get('label_mark') or '').strip()
            carton_mark = (supplied.get('carton_mark') or '').strip()

            # Ready-to-ship Amazon/Noon goods go straight to a fulfilment centre
            # and are refused there without these. Better a 400 now than a
            # rejected shipment later.
            if requires_labels(item.product):
                if not label_mark:
                    missing.append(f'{item.product.name}: label_mark is required.')
                if not carton_mark:
                    missing.append(f'{item.product.name}: carton_mark is required.')

            try:
                carton_quantity = int(supplied.get('carton_quantity') or 1)
            except (TypeError, ValueError):
                carton_quantity = 1

            line_extras[item.id] = {
                'label_mark': label_mark,
                'carton_mark': carton_mark,
                'carton_asn': (supplied.get('carton_asn') or '').strip(),
                'carton_quantity': carton_quantity,
                # File uploads are not part of the JSON checkout. The marks are
                # enough to place the order; the label FILES can be attached
                # afterwards through the website, which is where a PDF picker
                # belongs anyway.
                'shipping_label': None,
                'carton_label': None,
            }

        if missing:
            return Response({'detail': 'Label details are required for some items.',
                             'errors': missing},
                            status=status.HTTP_400_BAD_REQUEST)

        settings = CompanySettings.get_settings()
        order = create_order_from_cart(profile.customer, items, settings, line_extras)

        data = OrderSerializer(order, context={'request': request}).data
        # The click-to-chat handoff the website uses, so an app can offer the
        # same "message us about this order" button.
        data['whatsapp_url'] = order.whatsapp_url(settings) or ''
        return Response(data, status=status.HTTP_201_CREATED)
