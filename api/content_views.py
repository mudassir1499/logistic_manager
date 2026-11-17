"""
The remaining domains: product requests, order tracking, public content,
and the staff-only records.

Grouped here rather than piled into views.py because these are a different kind
of endpoint - mostly read-only projections and one narrow write each - and
views.py already holds the four that carry the real permission logic.
"""

from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from accounts.services import log_action
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AuditLog
from noon_labels.models import LabelBatch
from orders.models import Notification, Order, ShipmentStatus
from portal.models import (BlogPost, ContactMessage, PortfolioItem,
                           ProductRequest)
from products.models import PriceAdjustment
from settings_manager.models import CompanySettings, ShippingCompany

from .permissions import HasModule, IsBackOffice, IsCustomer, profile_of
from .serializers import (AuditLogSerializer, BlogPostDetailSerializer,
                          BlogPostListSerializer, CompanyInfoSerializer,
                          ContactMessageSerializer, LabelBatchSerializer,
                          NotificationSerializer, OrderCreateSerializer, OrderStatusUpdateSerializer,
                          PortfolioItemSerializer, PriceAdjustmentSerializer,
                          ProductRequestSerializer,
                          ProductRequestStaffSerializer,
                          ShipmentStatusSerializer, ShippingCompanySerializer)


# ---------------------------------------------------------------------------
# PRODUCT REQUESTS
# ---------------------------------------------------------------------------

class ProductRequestViewSet(viewsets.ModelViewSet):
    """
    "Please source this for me."

    A customer creates and reads their own; staff see all and move them through
    the workflow. Which serializer is used decides who may set `status` - see
    ProductRequestSerializer.
    """

    filterset_fields = ['status']
    ordering_fields = ['created_at', 'updated_at', 'id']
    ordering = ['-created_at']
    throttle_scope = 'read'

    def get_permissions(self):
        profile = profile_of(self.request)
        staff = profile is not None and profile.is_back_office
        return [IsBackOffice() if staff else IsCustomer()]

    def get_serializer_class(self):
        profile = profile_of(self.request)
        if profile is not None and profile.can('products'):
            return ProductRequestStaffSerializer
        return ProductRequestSerializer

    def get_queryset(self):
        qs = ProductRequest.objects.select_related('customer').prefetch_related('images')
        profile = profile_of(self.request)
        if profile is None:
            return qs.none()
        if profile.is_back_office:
            return qs
        return qs.filter(customer_id=profile.customer_id)

    def perform_create(self, serializer):
        # Ownership from the credential, never the body.
        profile = profile_of(self.request)
        serializer.save(customer_id=profile.customer_id)

    def get_throttles(self):
        self.throttle_scope = 'read' if self.request.method in ('GET', 'HEAD', 'OPTIONS') else 'write'
        return super().get_throttles()


# ---------------------------------------------------------------------------
# ORDER TRACKING
# ---------------------------------------------------------------------------

class ShipmentStatusViewSet(viewsets.ReadOnlyModelViewSet):
    """Where an order's shipments have got to."""

    serializer_class = ShipmentStatusSerializer
    filterset_fields = ['order', 'shipment_no', 'status']
    ordering = ['-updated_at']
    throttle_scope = 'read'

    def get_permissions(self):
        profile = profile_of(self.request)
        staff = profile is not None and profile.is_back_office
        return [IsBackOffice() if staff else IsCustomer()]

    def get_queryset(self):
        qs = ShipmentStatus.objects.select_related('order')
        profile = profile_of(self.request)
        if profile is None:
            return qs.none()
        if profile.is_back_office:
            return qs
        # Scoped through the order's customer: a shipment row is only visible to
        # the person whose order it belongs to.
        return qs.filter(order__customer_id=profile.customer_id)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """The caller's notifications, with a way to mark them read."""

    serializer_class = NotificationSerializer
    permission_classes = [IsCustomer]
    filterset_fields = ['is_read', 'notification_type']
    ordering = ['-created_at']
    throttle_scope = 'read'

    def get_queryset(self):
        profile = profile_of(self.request)
        if profile is None or not profile.customer_id:
            return Notification.objects.none()
        return Notification.objects.filter(customer_id=profile.customer_id)

    @extend_schema(summary='Mark one notification read', request=None,
                   responses={200: NotificationSerializer})
    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        notification = self.get_object()      # already scoped by get_queryset
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        return Response(self.get_serializer(notification).data)

    @extend_schema(summary='Mark every notification read', request=None,
                   responses={200: OpenApiResponse(description='{"marked": <count>}')})
    @action(detail=False, methods=['post'], url_path='read-all')
    def mark_all_read(self, request):
        marked = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({'marked': marked})


class OrderAdminViewSet(viewsets.GenericViewSet):
    """
    The staff-writable slice of an order.

    Separate from OrderViewSet, which is read-only for everyone, because the
    fields a staff member may change are a narrow subset - and mixing them into
    one serializer would have made `total` writable for whoever could PATCH.
    """

    queryset = Order.objects.all()
    serializer_class = OrderStatusUpdateSerializer
    permission_classes = [HasModule.for_module('orders')]
    throttle_scope = 'write'

    def get_serializer_class(self):
        # Creating takes a customer and a list of lines; updating takes a narrow
        # set of scalar fields. One serializer covering both would have to make
        # `items` optional on update, where it means nothing.
        if self.action == 'create':
            return OrderCreateSerializer
        return OrderStatusUpdateSerializer

    @extend_schema(summary='Create an order with its line items',
                   request=OrderCreateSerializer,
                   responses={201: OrderCreateSerializer})
    def create(self, request):
        """
        Build a whole order in one request.

        The total is computed from the lines server-side and is never read from
        the request: it is the figure the customer is billed, so the client
        asking for the order must not be the thing that decides it.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        log_action(request, 'orders.create',
                   target=f'Order #{order.id}',
                   detail=f'{order.items.count()} line(s), total {order.total}, '
                          f'customer {order.customer.name}')
        return Response(serializer.to_representation(order),
                        status=status.HTTP_201_CREATED)

    @extend_schema(summary='Update order status and costs',
                   request=OrderStatusUpdateSerializer,
                   responses={200: OrderStatusUpdateSerializer})
    def partial_update(self, request, pk=None):
        order = self.get_object()
        serializer = self.get_serializer(order, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# PUBLIC CONTENT
# ---------------------------------------------------------------------------

class BlogPostViewSet(viewsets.ReadOnlyModelViewSet):
    """Published articles. Public: these are already indexed by search engines."""

    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = 'slug'
    filterset_fields = ['category__slug', 'is_featured']
    search_fields = ['title', 'excerpt', 'keywords']
    ordering_fields = ['published_at', 'id']
    ordering = ['-published_at']
    throttle_scope = 'read'

    def get_queryset(self):
        # Drafts are not published. There is no staff branch here on purpose:
        # this endpoint exists to serve the public blog, and staff edit posts in
        # the admin.
        return (
            BlogPost.objects
            .filter(is_published=True, published_at__lte=timezone.now())
            .select_related('category')
        )

    def get_serializer_class(self):
        return BlogPostDetailSerializer if self.action == 'retrieve' else BlogPostListSerializer


class PortfolioViewSet(viewsets.ReadOnlyModelViewSet):
    """Portfolio pieces shown on the public site."""

    queryset = PortfolioItem.objects.filter(is_active=True).order_by('display_order', '-created_at')
    serializer_class = PortfolioItemSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'read'


class ContactMessageView(APIView):
    """
    Send an enquiry from the public site.

    Write-only by design. Listing contact messages would publish everyone's name,
    email and phone number to anyone who called the endpoint; staff read them in
    the back office.

    Requires a signed-in account (bearer token or session). The website's forms
    are protected by a CAPTCHA (portal/captcha.py); an anonymous endpoint that
    writes into the same inbox would be a way straight around it, and no client
    has ever called this one anonymously.
    """

    # Default authentication classes and IsAuthenticated from REST_FRAMEWORK.
    throttle_scope = 'auth'      # the tightest bucket

    @extend_schema(summary='Send a contact enquiry',
                   request=ContactMessageSerializer,
                   responses={201: ContactMessageSerializer})
    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CompanyInfoView(APIView):
    """Public company details, so an app can render its contact screen."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'read'

    @extend_schema(summary='Public company information',
                   responses={200: CompanyInfoSerializer})
    def get(self, request):
        settings = CompanySettings.get_settings()
        return Response(CompanyInfoSerializer({
            'company_name': settings.company_name,
            'currency': settings.currency,
            'currency_symbol': settings.currency_symbol,
            'email': getattr(settings, 'email', '') or '',
            'phone': getattr(settings, 'phone', '') or '',
            'address': getattr(settings, 'address', '') or '',
        }).data)


# ---------------------------------------------------------------------------
# STAFF-ONLY RECORDS
# ---------------------------------------------------------------------------

class PriceAdjustmentViewSet(viewsets.ReadOnlyModelViewSet):
    """
    History of catalogue-wide price changes.

    Read-only through the API. Running an adjustment rewrites every product and
    variant price it touches, and that belongs behind the confirmation dialog on
    the products screen, not one POST away.
    """

    queryset = PriceAdjustment.objects.select_related('user').order_by('-created_at')
    serializer_class = PriceAdjustmentSerializer
    permission_classes = [HasModule.for_module('products')]
    filterset_fields = ['scope']
    throttle_scope = 'read'


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Who did what. Admin only.

    Not merely staff: the audit log records other people's actions, including
    logins and permission changes, so reading it is an administrative act.
    """

    queryset = AuditLog.objects.select_related('user').order_by('-created_at')
    serializer_class = AuditLogSerializer
    permission_classes = [HasModule.for_module('settings')]
    filterset_fields = ['action']
    search_fields = ['target', 'detail']
    throttle_scope = 'read'


class LabelBatchViewSet(viewsets.ModelViewSet):
    """Noon label batches."""

    queryset = LabelBatch.objects.order_by('-created_at')
    serializer_class = LabelBatchSerializer
    permission_classes = [HasModule.for_module('noon_labels')]
    throttle_scope = 'read'

    def get_throttles(self):
        self.throttle_scope = 'read' if self.request.method in ('GET', 'HEAD', 'OPTIONS') else 'write'
        return super().get_throttles()


class ShippingCompanyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Freight rate cards. Staff only.

    These are cost prices. Published, they would tell a customer exactly what
    margin sits on their shipping.
    """

    queryset = ShippingCompany.objects.order_by('name')
    serializer_class = ShippingCompanySerializer
    permission_classes = [HasModule.for_module('settings')]
    throttle_scope = 'read'
