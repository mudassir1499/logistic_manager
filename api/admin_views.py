"""
Endpoints the back-office mobile app needs that the browser never did.

WHY A SEPARATE MODULE

The rest of the API mirrors the models: one viewset per table, filterable and
paginated. That shape is right for a desktop screen, which loads one list at a
time over a fast connection, and wrong for a phone home screen, which needs
eight numbers at once over a connection that may be a hotel wifi in Guangzhou.

DashboardView answers that in one round trip. It is deliberately NOT a viewset:
there is no dashboard table, and pretending otherwise would invite filtering and
pagination onto something that is a single computed snapshot.

ProductTagViewSet is here rather than in views.py simply because tags are a
back-office concept — customers never see or set them.
"""

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from customers.models import Customer
from orders.models import Order, ShipmentStatus
from products.models import Product, ProductTag
from support.models import Ticket

from .permissions import HasModule, IsBackOffice
from .serializers import ProductTagSerializer


class DashboardView(APIView):
    """
    Everything a back-office home screen shows, in one request.

    Returns:
        Response: counts grouped by the module they belong to.

    WHAT IS AND IS NOT COUNTED

    Every number here answers "is there something I need to do", not "how big is
    the business". `orders.awaiting_action` counts orders with no shipment status
    yet — the ones nobody has touched — rather than all open orders, because a
    number that never reaches zero stops being read after a week.

    Each block is gated on the caller's module permissions, so a coordinator with
    only `orders` gets orders and nothing else. The blocks are simply absent
    rather than zeroed: zero would say "nothing to do", when the truth is "not
    your department".
    """

    permission_classes = [IsAuthenticated, IsBackOffice]
    throttle_scope = 'read'

    @extend_schema(
        summary='Back-office dashboard counts',
        description='One call returning the figures a staff home screen shows. '
                    'Blocks are omitted where the caller lacks the module.',
        responses={200: dict},
    )
    def get(self, request):
        profile = getattr(request.user, 'profile', None)
        week_ago = timezone.now() - timedelta(days=7)

        def allowed(module):
            return bool(profile and profile.can(module))

        data = {
            'user': {
                'name': request.user.get_full_name() or request.user.username,
                'role': getattr(profile, 'role', ''),
            },
            'generated_at': timezone.now().isoformat(),
        }

        if allowed('orders'):
            orders = Order.objects.all()
            # An order with no ShipmentStatus row has never been picked up by
            # anybody. That is the queue worth putting on a home screen.
            untouched = orders.annotate(n=Count('shipment_statuses')).filter(n=0)
            data['orders'] = {
                'total': orders.count(),
                'awaiting_action': untouched.count(),
                'this_week': orders.filter(date__gte=week_ago).count(),
                'delivered': ShipmentStatus.objects.filter(
                    status=ShipmentStatus.STATUS_DELIVERED).values('order').distinct().count(),
            }

        if allowed('products'):
            products = Product.objects.all()
            data['products'] = {
                'total': products.count(),
                'public': products.filter(is_private=False, is_draft=False).count(),
                'drafts': products.filter(is_draft=True).count(),
                # Not advertisable: Meta and TikTok both reject an item with no
                # image, so this is the number of products silently missing from
                # every catalogue ad. See products/feeds.py.
                'missing_photo': sum(
                    1 for p in products.filter(is_private=False, is_draft=False)
                                       .prefetch_related('images')
                    if not p.displayable_images
                ),
                'incomplete_shipping': products.filter(
                    Q(weight__isnull=True) | Q(carton_qty__isnull=True)
                ).count(),
            }

        if allowed('customers'):
            data['customers'] = {
                'total': Customer.objects.count(),
                'new_this_week': Customer.objects.filter(created_at__gte=week_ago).count(),
            }

        if allowed('support'):
            data['support'] = {
                'open': Ticket.objects.filter(status=Ticket.STATUS_OPEN).count(),
                'total': Ticket.objects.count(),
            }

        if allowed('khata'):
            from khata.models import LedgerEntry
            # One `amount` column split by entry_type, not two columns. Sum
            # returns None on an empty table, so each falls back to 0 - a
            # dashboard that renders "None owed" reads as a broken screen.
            totals = LedgerEntry.objects.aggregate(
                credit=Sum('amount', filter=Q(entry_type=LedgerEntry.CREDIT)),
                debit=Sum('amount', filter=Q(entry_type=LedgerEntry.DEBIT)),
            )
            credit = totals['credit'] or 0
            debit = totals['debit'] or 0
            data['ledger'] = {
                'credit': str(credit),
                'debit': str(debit),
                # What customers owe overall, which is the figure anybody
                # opening this on a phone is actually looking for.
                'outstanding': str(debit - credit),
            }

        return Response(data)


class ProductTagViewSet(viewsets.ModelViewSet):
    """
    Cross-cutting product labels.

    Back-office only. Tags describe internal state — which supplier something
    came from, what still needs photographing — and are never shown to
    customers, so unlike categories they are not readable without a module.
    """

    queryset = ProductTag.objects.annotate(product_count=Count('products'))
    serializer_class = ProductTagSerializer
    permission_classes = [HasModule.for_module('products')]
    search_fields = ['name']
    ordering_fields = ['name', 'product_count', 'created_at']
    ordering = ['name']

    def get_throttles(self):
        # Reading the tag list happens on every screen that shows a filter bar;
        # creating one is rare. Charging both at the write rate would throttle
        # ordinary browsing.
        self.throttle_scope = 'read' if self.request.method in ('GET', 'HEAD') else 'write'
        return super().get_throttles()
