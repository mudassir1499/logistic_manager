"""
Viewsets for /api/v1/.

THE SCOPING RULE

Several of these endpoints serve both staff and customers, and the difference is
never "which fields are hidden" - it is WHICH ROWS EXIST. ``get_queryset``
narrows to the caller's own Customer before anything else runs, so a customer
asking for order 999 gets a 404, not a 403. A 403 confirms the order exists,
which is itself a leak: it tells an attacker their id guessing is working.

Filtering by a query parameter is never the scoping mechanism. A caller controls
query parameters; they cannot control what get_queryset returns.
"""

from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from customers.models import Customer
from khata.models import LedgerEntry
from orders.models import Order
from products.models import Category, Product, ProductVariant
from support.models import Ticket

from .permissions import (HasModule, IsBackOffice, IsCustomer, PublicRead,
                          ReadOnlyOrModule, profile_of)
from .serializers import (CategorySerializer, CustomerSelfSerializer,
                          CustomerSerializer, LedgerEntrySerializer,
                          MeSerializer, OrderSerializer,
                          ProductPublicSerializer, ProductStaffSerializer,
                          ProductWriteSerializer, TicketMessageSerializer, TicketSerializer)


class CategoryViewSet(viewsets.ModelViewSet):
    """Product categories and their subcategories."""

    queryset = Category.objects.filter(is_active=True).prefetch_related('subcategories')
    serializer_class = CategorySerializer
    permission_classes = [PublicRead.for_module('products')]
    lookup_field = 'slug'
    search_fields = ['name', 'slug']
    ordering_fields = ['name', 'id']
    ordering = ['name']
    throttle_scope = 'read'


class ProductViewSet(viewsets.ModelViewSet):
    """
    The catalogue.

    Reading is public - these products are already published on the website and
    indexed by search engines, so a token would protect nothing. Writing needs
    the products module permission.
    """

    permission_classes = [PublicRead.for_module('products')]
    lookup_field = 'slug'
    filterset_fields = ['category__slug', 'subcategory__slug', 'source', 'ready_to_ship']
    search_fields = ['name', 'sku']
    ordering_fields = ['name', 'price', 'id']
    ordering = ['id']
    throttle_scope = 'read'

    def get_queryset(self):
        """
        Private and draft products are staff-only.

        `is_private` marks negotiated or customer-exclusive lines and `is_draft`
        marks something not ready to sell. Both are excluded for anyone without
        the products permission - including authenticated customers, for whom
        this is the same catalogue the website shows them.
        """
        qs = (
            Product.objects
            .select_related('category', 'subcategory')
            .prefetch_related('images', 'variants', 'attributes')
        )
        profile = profile_of(self.request)
        if profile is None or not profile.can('products'):
            qs = qs.filter(is_private=False, is_draft=False)
        return qs

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return ProductWriteSerializer
        profile = profile_of(self.request)
        if profile is not None and profile.can('products'):
            return ProductStaffSerializer
        return ProductPublicSerializer

    def get_throttles(self):
        self.throttle_scope = 'read' if self.request.method in ('GET', 'HEAD', 'OPTIONS') else 'write'
        return super().get_throttles()


class CustomerViewSet(viewsets.ModelViewSet):
    """Customer business records. Staff only - see MeView for a customer's own."""

    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [HasModule.for_module('customers')]
    search_fields = ['name', 'email', 'phone']
    ordering_fields = ['name', 'created_at', 'id']
    ordering = ['name']
    throttle_scope = 'read'


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Orders.

    Read-only on purpose. Placing an order touches stock, pricing, the ledger
    and the WhatsApp notification, and exposing a bare POST that writes an Order
    row would let a caller create one that skipped all of it. Ordering goes
    through the checkout flow; this endpoint is for reading what exists.
    """

    serializer_class = OrderSerializer
    filterset_fields = ['status', 'payment_status', 'is_placed']
    ordering_fields = ['date', 'id', 'total']
    ordering = ['-id']
    throttle_scope = 'read'

    def get_permissions(self):
        # Either a staff member with the orders module, or a customer reading
        # their own. The queryset below is what enforces the second half.
        return [(HasModule.for_module('orders')() if self._is_staff() else IsCustomer())]

    def _is_staff(self):
        profile = profile_of(self.request)
        return profile is not None and profile.is_back_office

    def get_queryset(self):
        qs = (
            Order.objects
            .select_related('customer')
            # shipping_companies is a ManyToMany, and OrderSerializer uses
            # fields='__all__', so DRF serialises it for every order. Without
            # this prefetch that is one extra query PER ORDER - measured at 17
            # queries for 5 orders and 26 for 15, which is invisible on a
            # developer's three test rows and a real cost on a customer with a
            # year of history.
            .prefetch_related('items', 'items__product', 'shipping_companies')
        )
        profile = profile_of(self.request)
        if profile is None:
            return qs.none()
        if profile.is_back_office:
            return qs
        # Scoped to the caller's own rows. Anything else is invisible, not
        # forbidden - see the module docstring.
        return qs.filter(customer_id=profile.customer_id)


class LedgerEntryViewSet(viewsets.ModelViewSet):
    """
    The account book.

    A customer may READ their own entries and nothing else. Writing is staff
    only: a customer able to post a credit to their own ledger could clear their
    own balance.
    """

    serializer_class = LedgerEntrySerializer
    filterset_fields = ['customer', 'entry_type', 'currency']
    ordering_fields = ['date', 'id', 'amount']
    ordering = ['-date']
    throttle_scope = 'read'

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [IsBackOffice() if self._is_staff() else IsCustomer()]
        return [HasModule.for_module('khata')()]

    def _is_staff(self):
        profile = profile_of(self.request)
        return profile is not None and profile.is_back_office

    def get_queryset(self):
        qs = LedgerEntry.objects.select_related('customer')
        profile = profile_of(self.request)
        if profile is None:
            return qs.none()
        if profile.can('khata'):
            return qs
        if profile.role == 'customer' and profile.customer_id:
            return qs.filter(customer_id=profile.customer_id)
        return qs.none()

    def get_throttles(self):
        self.throttle_scope = 'read' if self.request.method in ('GET', 'HEAD', 'OPTIONS') else 'write'
        return super().get_throttles()


class TicketViewSet(viewsets.ModelViewSet):
    """Support tickets. Customers see their own; the support desk sees all."""

    serializer_class = TicketSerializer
    filterset_fields = ['status', 'priority', 'category']
    ordering_fields = ['created_at', 'updated_at', 'id']
    ordering = ['-updated_at']
    throttle_scope = 'read'

    def get_permissions(self):
        return [IsBackOffice() if self._is_staff() else IsCustomer()]

    def _is_staff(self):
        profile = profile_of(self.request)
        return profile is not None and profile.is_back_office

    def get_queryset(self):
        """
        Tickets the caller may see, with the messages they may see.

        The base queryset deliberately does NOT prefetch 'messages'. Adding it
        here and then attaching a filtered Prefetch for customers raises
        "'messages' lookup was already seen with a different queryset" - Django
        refuses two different querysets for one lookup rather than silently
        picking one. Each branch attaches exactly one.
        """
        from support.models import TicketMessage

        qs = Ticket.objects.select_related('customer')
        profile = profile_of(self.request)
        if profile is None:
            return qs.none()

        if profile.can('support'):
            return qs.prefetch_related('messages')

        if profile.role == 'customer' and profile.customer_id:
            # Internal notes are staff-only: a customer reading their own ticket
            # must not see the desk talking about them. Filtering in the
            # Prefetch means the excluded rows are never loaded, so there is
            # nothing for the serializer to accidentally include.
            return (
                qs.filter(customer_id=profile.customer_id)
                  .prefetch_related(Prefetch(
                      'messages',
                      queryset=TicketMessage.objects.filter(is_internal=False),
                  ))
            )
        return qs.none()

    def perform_create(self, serializer):
        profile = profile_of(self.request)
        if profile is not None and profile.role == 'customer':
            serializer.save(customer_id=profile.customer_id, created_by=self.request.user)
        else:
            serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'], throttle_classes=[])
    def reply(self, request, pk=None):
        """
        Post a message onto a ticket.

        Args:
            request: POST with {'body': str, 'is_internal': bool}.
            pk: the ticket.

        Returns:
            Response: the created message.

        Replying is its own action rather than a nested router because a message
        only ever exists inside one ticket - a top-level /ticket-messages/
        endpoint would need its own permission logic to stop a customer posting
        into somebody else's thread. Here the ticket is resolved through
        get_object(), which already applies the queryset filtering above.

        `is_internal` is forced False for customers. An internal note is the
        desk talking to itself about the person, and a customer who could set
        the flag could also read the replies to it.
        """
        from support.models import TicketMessage

        ticket = self.get_object()
        body = (request.data.get('body') or '').strip()
        if not body:
            return Response({'detail': 'A reply needs a message.'},
                            status=status.HTTP_400_BAD_REQUEST)

        internal = bool(request.data.get('is_internal')) and self._is_staff()

        message = TicketMessage.objects.create(
            ticket=ticket,
            author=request.user,
            body=body[:5000],
            is_internal=internal,
        )
        # Touch the ticket so it sorts to the top of the desk's list, which is
        # ordered by -updated_at. Without this a busy thread sinks.
        ticket.save(update_fields=['updated_at'])

        return Response(TicketMessageSerializer(message).data,
                        status=status.HTTP_201_CREATED)

    def get_throttles(self):
        self.throttle_scope = 'write' if self.request.method in ('POST', 'PATCH', 'PUT') else 'read'
        return super().get_throttles()


@extend_schema_view(
    get=extend_schema(
        summary='Who this token belongs to',
        responses=MeSerializer,
    ),
    patch=extend_schema(
        summary='Update your own customer record',
        request=CustomerSelfSerializer,
        responses=CustomerSelfSerializer,
    ),
)
class MeView(APIView):
    """
    Who the current token belongs to, and the customer record behind it.

    The first call any client should make: it confirms the token works and says
    what it may do, so a consumer can hide what it cannot reach rather than
    discovering it through 403s.
    """

    throttle_scope = 'auth'

    def get(self, request):
        profile = profile_of(request)
        if profile is None:
            return Response({'detail': 'No profile for this account.'},
                            status=status.HTTP_403_FORBIDDEN)

        from accounts.models import Profile
        data = {
            'username': request.user.get_username(),
            'email': request.user.email,
            'full_name': request.user.get_full_name(),
            'role': profile.role,
            'is_back_office': profile.is_back_office,
            # What this token may reach, so a client can build its own menu
            # instead of probing endpoints to find out.
            'modules': {m: profile.can(m) for m in Profile.MODULES},
            'customer': None,
        }
        if profile.customer_id:
            data['customer'] = CustomerSelfSerializer(profile.customer).data
        return Response(data)

    def patch(self, request):
        """Update the caller's own customer record (name, phone, address)."""
        profile = profile_of(request)
        if profile is None or not profile.customer_id:
            raise PermissionDenied('This account has no customer record to update.')
        serializer = CustomerSelfSerializer(profile.customer, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
