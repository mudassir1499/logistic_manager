"""
Back-office screens for quotations.

The list is built around the one number this app exists to produce — the
conversion rate — rather than around a table of rows. Everything else here
supports getting a quote out and recording what happened to it.
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import module_required
from customers.models import Customer
from products.models import Product
from settings_manager.models import CompanySettings

from .models import Quotation, QuotationItem


def _to_decimal(value, fallback=Decimal('0.00')):
    """
    Parse a posted money value without destroying the old one.

    A blank or malformed field returns the fallback rather than zero. Writing
    zero on a parse failure is how a form silently wipes a price that was
    already correct.
    """
    text = (value or '').strip().replace(',', '')
    if not text:
        return fallback
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return fallback


def _to_int(value, fallback=0):
    try:
        return int(str(value).strip() or fallback)
    except (TypeError, ValueError):
        return fallback


@module_required('quotes')
def quotation_list(request):
    """
    Every quotation, with the conversion figures above it.

    Args:
        request (HttpRequest): GET, optionally with `status`, `customer` and `q`.

    Returns:
        HttpResponse: the list page.
    """
    quotations = (Quotation.objects
                  .select_related('customer', 'order')
                  # The subtotal on each row sums the line items, so they are
                  # prefetched here - without this the list is one query per
                  # row, which is the classic way a list page dies at scale.
                  .prefetch_related(Prefetch('items', queryset=QuotationItem.objects.select_related('product'))))

    status = (request.GET.get('status') or '').strip()
    if status in dict(Quotation.STATUS_CHOICES):
        quotations = quotations.filter(status=status)

    customer_id = (request.GET.get('customer') or '').strip()
    if customer_id.isdigit():
        quotations = quotations.filter(customer_id=int(customer_id))

    search = (request.GET.get('q') or '').strip()
    if search:
        quotations = quotations.filter(
            Q(number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(items__description__icontains=search)
            | Q(items__product__name__icontains=search)
        ).distinct()

    paginator = Paginator(quotations, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    # ---- the figures the page exists for --------------------------------
    #
    # Counted over ALL quotations rather than the current filter: a conversion
    # rate that changes when you click a status tab is not a conversion rate.
    counts = dict(
        Quotation.objects.values_list('status').annotate(n=Count('id')).values_list('status', 'n')
    )
    accepted = counts.get(Quotation.STATUS_ACCEPTED, 0)
    declined = counts.get(Quotation.STATUS_DECLINED, 0)
    expired = counts.get(Quotation.STATUS_EXPIRED, 0)
    decided = accepted + declined + expired
    # Denominator is DECIDED quotes, not all of them. Counting quotes that are
    # still open as losses would make the rate drop every time one is sent.
    conversion = round(accepted / decided * 100, 1) if decided else None

    return render(request, 'quotes/quotation_list.html', {
        'settings': CompanySettings.get_settings(),
        'page_obj': page_obj,
        'quotations': page_obj.object_list,
        'status': status,
        'search': search,
        'customer_id': customer_id,
        'customers': Customer.objects.order_by('name'),
        'status_choices': Quotation.STATUS_CHOICES,
        'counts': counts,
        'total_count': sum(counts.values()),
        'open_count': (counts.get(Quotation.STATUS_DRAFT, 0)
                       + counts.get(Quotation.STATUS_SENT, 0)),
        'accepted_count': accepted,
        'decided_count': decided,
        'conversion_rate': conversion,
    })


@module_required('quotes')
def quotation_detail(request, quotation_id):
    """One quotation, its lines, and the actions available on it."""
    quotation = get_object_or_404(
        Quotation.objects.select_related('customer', 'order', 'request'),
        id=quotation_id,
    )
    return render(request, 'quotes/quotation_detail.html', {
        'settings': CompanySettings.get_settings(),
        'quotation': quotation,
        'items': quotation.items.select_related('product'),
        'products': Product.objects.filter(is_draft=False).order_by('name')[:500],
        'can_edit': quotation.status == Quotation.STATUS_DRAFT,
    })


@module_required('quotes')
def quotation_create(request):
    """
    Start a quotation.

    Deliberately minimal: a customer and an optional validity window. Lines are
    added on the detail screen, because choosing products is the slow part and
    putting it behind a half-filled create form means losing the lot if
    anything goes wrong.
    """
    if request.method != 'POST':
        return render(request, 'quotes/quotation_form.html', {
            'settings': CompanySettings.get_settings(),
            'customers': Customer.objects.order_by('name'),
            'default_valid_until': timezone.localdate() + timedelta(days=30),
        })

    customer = Customer.objects.filter(id=request.POST.get('customer')).first()
    if customer is None:
        messages.error(request, 'Choose a customer for this quotation.')
        return redirect('quotation_create')

    company = CompanySettings.get_settings()
    quotation = Quotation.objects.create(
        customer=customer,
        currency=(request.POST.get('currency') or company.currency_code or 'AED').strip(),
        valid_until=request.POST.get('valid_until') or None,
        notes=(request.POST.get('notes') or '').strip(),
        internal_notes=(request.POST.get('internal_notes') or '').strip(),
        created_by=request.user if request.user.is_authenticated else None,
    )
    messages.success(request, 'Quotation %s created. Add the lines below.' % quotation.number)
    return redirect('quotation_detail', quotation_id=quotation.id)


@module_required('quotes')
def quotation_add_item(request, quotation_id):
    """Add one line. Works with or without a catalogue product."""
    quotation = get_object_or_404(Quotation, id=quotation_id)
    if request.method != 'POST':
        return redirect('quotation_detail', quotation_id=quotation.id)

    if quotation.status != Quotation.STATUS_DRAFT:
        # Editing a quote the customer is already holding would change what
        # they were offered without any record of the original.
        messages.error(request, 'Only a draft can be edited. %s has already been sent.'
                       % quotation.number)
        return redirect('quotation_detail', quotation_id=quotation.id)

    product = Product.objects.filter(id=request.POST.get('product')).first()
    description = (request.POST.get('description') or '').strip()
    if product is None and not description:
        messages.error(request, 'Pick a product or type a description for the line.')
        return redirect('quotation_detail', quotation_id=quotation.id)

    unit_cost_raw = (request.POST.get('unit_cost') or '').strip()
    QuotationItem.objects.create(
        quotation=quotation,
        product=product,
        description=description,
        quantity=max(1, _to_int(request.POST.get('quantity'), 1)),
        unit_price=_to_decimal(request.POST.get('unit_price')),
        unit_cost=_to_decimal(unit_cost_raw, None) if unit_cost_raw else None,
        position=quotation.items.count(),
    )
    return redirect('quotation_detail', quotation_id=quotation.id)


@module_required('quotes')
def quotation_delete_item(request, quotation_id, item_id):
    quotation = get_object_or_404(Quotation, id=quotation_id)
    if request.method == 'POST' and quotation.status == Quotation.STATUS_DRAFT:
        QuotationItem.objects.filter(id=item_id, quotation=quotation).delete()
    return redirect('quotation_detail', quotation_id=quotation.id)


@module_required('quotes')
def quotation_action(request, quotation_id):
    """
    Move a quotation along: send, accept, decline, expire.

    Args:
        request (HttpRequest): POST carrying `action`, and `reason` for a decline.

    Each transition is guarded by the status it is legal from, so a double
    submit or a stale tab cannot, for example, re-send a quote that has already
    been accepted and reset its decision date.
    """
    quotation = get_object_or_404(Quotation, id=quotation_id)
    if request.method != 'POST':
        return redirect('quotation_detail', quotation_id=quotation.id)

    action = (request.POST.get('action') or '').strip()

    if action == 'send':
        if quotation.status != Quotation.STATUS_DRAFT:
            messages.error(request, '%s has already been sent.' % quotation.number)
        elif not quotation.items.exists():
            messages.error(request, 'Add at least one line before sending %s.' % quotation.number)
        else:
            quotation.mark_sent()
            messages.success(request, '%s marked as sent.' % quotation.number)

    elif action in ('accept', 'decline', 'expire'):
        if quotation.status != Quotation.STATUS_SENT:
            messages.error(request, 'Only a sent quotation can be %sed. %s is %s.'
                           % (action.rstrip('e'), quotation.number, quotation.get_status_display().lower()))
        elif action == 'accept':
            quotation.mark_accepted()
            messages.success(request, '%s accepted. Convert it to an order when ready.'
                             % quotation.number)
        elif action == 'decline':
            quotation.mark_declined(request.POST.get('reason', ''))
            messages.success(request, '%s marked as declined.' % quotation.number)
        else:
            quotation.mark_expired()
            messages.success(request, '%s marked as expired.' % quotation.number)
    else:
        messages.error(request, 'Unknown action.')

    return redirect('quotation_detail', quotation_id=quotation.id)


@module_required('quotes')
def quotation_convert(request, quotation_id):
    """
    Turn an accepted quotation into an order.

    Args:
        request (HttpRequest): POST.

    Returns:
        HttpResponseRedirect: to the new order, or back with the reason why not.

    Only lines carrying a real catalogue Product become order lines, because
    OrderItem.product is non-null and PROTECT. Free-text lines - the custom
    carton, the tooling charge - are reported rather than dropped silently, so
    whoever converts knows what still has to be handled by hand.
    """
    from orders.models import Order, OrderItem

    quotation = get_object_or_404(Quotation.objects.select_related('customer'), id=quotation_id)
    if request.method != 'POST':
        return redirect('quotation_detail', quotation_id=quotation.id)

    if quotation.status != Quotation.STATUS_ACCEPTED:
        messages.error(request, 'Accept %s before converting it to an order.' % quotation.number)
        return redirect('quotation_detail', quotation_id=quotation.id)
    if quotation.order_id:
        messages.warning(request, '%s already became order #%s.'
                         % (quotation.number, quotation.order_id))
        return redirect('quotation_detail', quotation_id=quotation.id)

    lines = list(quotation.items.select_related('product'))
    with_product = [line for line in lines if line.product_id]
    without = [line for line in lines if not line.product_id]

    if not with_product:
        messages.error(
            request,
            '%s has no catalogue products on it, so there is nothing to put on an '
            'order. Add the products to the catalogue first.' % quotation.number)
        return redirect('quotation_detail', quotation_id=quotation.id)

    with transaction.atomic():
        order = Order.objects.create(
            customer=quotation.customer,
            total=sum((line.line_total for line in with_product), Decimal('0.00')),
        )
        for line in with_product:
            OrderItem.objects.create(
                order=order,
                product=line.product,
                quantity=line.quantity,
                price=line.unit_price,
            )
        quotation.order = order
        quotation.save(update_fields=['order', 'updated_at'])

    note = '%s converted to order #%s.' % (quotation.number, order.id)
    if without:
        note += (' %d line(s) had no catalogue product and were not copied: %s.'
                 % (len(without), ', '.join(line.label for line in without[:3])))
        messages.warning(request, note)
    else:
        messages.success(request, note)
    return redirect('quotation_detail', quotation_id=quotation.id)
