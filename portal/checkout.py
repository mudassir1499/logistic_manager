"""
Turning a cart into an order.

WHY THIS IS NOT INSIDE THE VIEW ANY MORE

``checkout_confirm`` held the only implementation of what an order IS: how the
commission is calculated, that the order starts as a draft so staff can price
shipping, that each line freezes the price it was bought at, and that the cart is
emptied only after the order exists. All of that was reachable only by POSTing an
HTML form with files attached.

The API needs the same behaviour, and the one thing that must not happen is a
second implementation of it. Two copies of order creation drift, and the way you
find out is an order placed through the app that has no commission on it, or a
cart that empties without an order. So the logic lives here and both callers use
it.

The web view keeps everything this does not cover - the label file uploads, the
Django messages, the WhatsApp redirect - because those are genuinely about the
HTML flow.
"""

from decimal import Decimal

from django.db import transaction

from orders.models import Order, OrderItem


def cart_totals(items, settings):
    """
    Money for a cart, without creating anything.

    Args:
        items (iterable): CartItem rows, each with a ``unit_price``.
        settings (CompanySettings): supplies the commission percentage.

    Returns:
        dict: {'subtotal', 'commission_percentage', 'commission_amount', 'total'}
        as Decimals quantised to two places.

    Exposed separately so a client can show the customer what they are about to
    pay using the SAME arithmetic that will be applied - rather than
    reimplementing the commission in JavaScript and disagreeing by a cent.
    """
    subtotal = sum((item.unit_price * item.quantity for item in items), Decimal('0'))
    commission_pct = settings.commission_percentage or Decimal('0')
    commission_amount = (subtotal * commission_pct / Decimal('100')).quantize(Decimal('0.01'))
    return {
        'subtotal': subtotal.quantize(Decimal('0.01')),
        'commission_percentage': commission_pct,
        'commission_amount': commission_amount,
        'total': (subtotal + commission_amount).quantize(Decimal('0.01')),
    }


@transaction.atomic
def create_order_from_cart(customer, items, settings, line_extras=None):
    """
    Create a draft Order from a cart and empty the cart.

    Args:
        customer (Customer): who is ordering.
        items (QuerySet): the CartItem rows to convert. A queryset rather than a
            list because it is deleted at the end, and deleting a list means one
            query per row.
        settings (CompanySettings): commission percentage and currency.
        line_extras (dict | None): optional per-cart-item extras keyed by cart
            item id, e.g. {12: {'label_mark': 'X', 'shipping_label': <File>}}.
            This is how the web view passes its uploaded label files without
            this module knowing anything about request.FILES.

    Returns:
        Order: the created order, with its items.

    Raises:
        ValueError: if the cart is empty. Creating a zero-line order would leave
            a customer looking at an order confirming nothing.

    ATOMIC ON PURPOSE. The cart is emptied in the same transaction that creates
    the order. Without that, a failure between the two leaves the customer with
    an empty cart and no order - the goods they chose simply gone - or with an
    order they can place a second time.

    THE PRICE IS FROZEN HERE. ``OrderItem.price`` is written from the cart item's
    unit price at this moment and never recalculated. That is what makes a later
    catalogue price change unable to rewrite an order that was already placed.
    """
    items = list(items)
    if not items:
        raise ValueError('Cannot create an order from an empty cart.')

    line_extras = line_extras or {}
    totals = cart_totals(items, settings)

    order = Order.objects.create(
        customer=customer,
        total=totals['total'],
        commission_amount=totals['commission_amount'],
        commission_percentage=totals['commission_percentage'],
        # Draft, not placed: staff still have to price the shipping. An order
        # that arrived already "placed" would skip the review the whole flow
        # exists for.
        status=Order.STATUS_DRAFT,
        payment_status='unpaid',
    )

    for item in items:
        extras = line_extras.get(item.id, {})
        OrderItem.objects.create(
            order=order,
            product=item.product,
            # Carried onto the line so the invoice, packing list and supplier
            # order all say WHICH variation was bought.
            variant=item.variant,
            quantity=item.quantity,
            price=item.unit_price,
            shipment_no=1,
            shipment_method='manual',
            cargo_type='standard',
            label_mark=extras.get('label_mark', '') or '',
            carton_mark=extras.get('carton_mark', '') or '',
            carton_asn=extras.get('carton_asn', '') or '',
            carton_quantity=extras.get('carton_quantity') or 1,
            shipping_label=extras.get('shipping_label'),
            carton_label=extras.get('carton_label'),
        )

    # Only after the order and every line exist.
    from portal.models import CartItem
    CartItem.objects.filter(id__in=[item.id for item in items]).delete()

    return order


def requires_labels(product):
    """
    True when a product cannot be ordered without label details.

    Ready-to-ship Amazon/Noon goods ship straight to a fulfilment centre, so they
    need the marks and label files that centre will look for. Anything else is
    consolidated by us and does not.
    """
    return bool(product.ready_to_ship and product.source in {'amazon', 'noon'})
