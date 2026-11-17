"""
Orders Views — Order Management, Invoicing, Quotation Import & Packing Lists

Business Context:
This is the CORE module of the logistics management system. It handles the entire order lifecycle:
1. Order creation and editing (draft -> confirmed -> placed)
2. Multi-shipment orders (a single order can have multiple air/sea shipments)
3. Invoice generation with per-shipment shipping cost calculations
4. Payment tracking (unpaid / partial / paid)
5. Commission calculation (percentage added to order total as business profit)
6. Quotation import (customer fills an Excel, admin uploads it to create a draft order)
7. Packing list generation (for warehouse/fulfillment)
8. Order duplication (clone an existing order as a new draft)

Key Concepts:
- Order: The top-level order with customer, total, shipping, commission, payment status.
- OrderItem: Individual line items within an order (product, quantity, price, shipment details).
- OrderExtraCost: Additional costs (customs, insurance, etc.) added to the order total.
- Shipment: Orders can be split into multiple shipments (e.g., 3 cartons by air, 2 by sea).
  Each OrderItem has a shipment_no, shipment_method, cargo_type, and shipping company.
- CBM: Cubic meters (used for sea freight pricing).
- Chargeable Weight: For air freight, the greater of actual weight vs volumetric weight.
- Landed Cost: Unit price + shipping cost per unit (the true cost to the customer).

Django Concepts Used:
- @login_required: Protects all order management views (financial data is sensitive).
- @csrf_exempt: Allows AJAX endpoints to accept requests without CSRF token.
- select_related('customer'): SQL JOIN to fetch customer data in the same query (avoids N+1).
- prefetch_related('items__product'): Fetches related items and their products efficiently.
- Order.objects.aggregate(): Uses Django aggregation functions (Sum, Count) for statistics.
- Q objects: Complex query conditions for filtering (e.g., payment_status='unpaid' AND status='confirmed').
- Decimal: All money calculations use Decimal for precision (avoiding float errors like 0.1 + 0.2).
- request.POST.getlist(): Gets multiple values for the same form field name (e.g., product_id[], quantity[]).
"""

import re
import json
import calendar
import zipfile
import os
from io import BytesIO
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db.models import Sum, Count, Q, F

# transaction.atomic makes order saves all-or-nothing. Editing an order deletes
# every existing line item before re-creating them from the form, so a failure
# part-way through previously destroyed data with no way to recover it.
from django.db import transaction
from django.db.models.functions import TruncMonth
from django.http import JsonResponse, FileResponse, HttpResponse
from django.contrib.auth.decorators import login_required
# Role-aware access guard: only users whose profile grants the 'orders' module
# (admins always, or staff with perm_orders) may reach these views.
from accounts.decorators import module_required
from django.shortcuts import render, get_object_or_404, redirect
# NOTE: @csrf_exempt was removed from the views in this file. The admin UI now
# attaches X-CSRFToken to every same-origin state-changing fetch() automatically
# (see the wrapper at the top of static/main.js), so these endpoints are
# protected again without any call site needing to change.

from django.core.paginator import Paginator

# Used by the bulk-action view: messages for the confirmation banner, reverse() to
# build the fallback redirect, and url_has_allowed_host_and_scheme to reject a
# `next` parameter pointing off-site (an open-redirect guard).
from django.contrib import messages
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.mail import send_mail, get_connection
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth.models import User
from django.contrib import messages

# Typed email helper sends order-status emails from the dedicated order_status SMTP profile.
from utils.email_utils import send_typed_email

from customers.models import Customer
from products.models import Product
from settings_manager.models import CompanySettings
from settings_manager.models import ShippingCompany

from .models import Order, OrderItem, OrderExtraCost, OrderNote, Notification, ShipmentStatus, SHIPPING_METHOD_CHOICES, CARGO_TYPE_CHOICES


def _to_decimal(value, default='0'):
    """
    Safely convert a value to a Decimal, falling back to a default if conversion fails.

    Args:
        value: Any value that might be convertible to Decimal (string, int, float, Decimal).
        default (str): The default string value to use if conversion fails.

    Returns:
        Decimal: The converted Decimal value, or the default if conversion fails.

    Business Logic:
        Form inputs and POST data are always strings. This helper ensures we safely
        convert them to Decimal for precise money calculations. If the user enters
        something invalid (like a letter), we gracefully fall back to zero.
    """
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return Decimal(default)


def _quantize_money(value):
    """
    Round a Decimal to 2 decimal places using standard rounding (half up).

    Args:
        value (Decimal): The monetary value to round.

    Returns:
        Decimal: The value rounded to 2 decimal places.

    Business Logic:
        All money amounts in the system (prices, totals, shipping costs) are stored
        with exactly 2 decimal places. This ensures consistent display and prevents
        rounding discrepancies in financial reports.
    """
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _quantize_metric(value):
    """
    Round a Decimal to 3 decimal places using standard rounding (half up).

    Args:
        value (Decimal): The metric value (weight, CBM) to round.

    Returns:
        Decimal: The value rounded to 3 decimal places.

    Business Logic:
        Weight and CBM values need 3 decimal places for precision in shipping calculations.
        For example, a product might weigh 0.125 kg or occupy 0.045 CBM.
    """
    return value.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)


def _notify_customer_order_status(order, subject, headline):
    """
    Send an order-status email to the customer using the order_status SMTP profile.

    Args:
        order (Order): The order being updated.
        subject (str): Email subject line.
        headline (str): Short description of the status change (e.g. 'confirmed').

    Returns:
        int: Number of emails sent (0 if SMTP is not configured or the customer
             has no email address).
    """
    customer = order.customer
    if not customer or not customer.email:
        return 0

    settings = CompanySettings.get_settings()
    items_list = "\n".join(
        f"- {item.product.name} x {item.quantity}"
        for item in order.items.select_related('product').all()
    )

    message = (
        f"Dear {customer.name},\n\n"
        f"{headline}\n\n"
        f"Order #{order.id}\n"
        f"Date: {order.date.strftime('%b %d, %Y %H:%M')}\n"
        f"Total: {settings.currency} {order.total}\n"
        f"Payment Status: {order.get_payment_status_display()}\n"
        f"Order Status: {order.get_status_display()}\n\n"
        f"Items:\n{items_list or 'No items'}\n\n"
        f"You can log in to the customer portal to view the full details.\n\n"
        f"Best regards,\n{settings.company_name}"
    )

    try:
        return send_typed_email(
            email_type='order_status',
            subject=subject,
            message=message,
            recipient_list=[customer.email],
            fail_silently=True,
        )
    except Exception:
        return 0


def _uses_cbm_shipping(method):
    """
    Check if a shipping method uses CBM (cubic meters) for pricing.

    Args:
        method (str): The shipping method code (e.g., 'sea', 'air', 'ksa_sea').

    Returns:
        bool: True if the method uses CBM-based pricing (sea freight).

    Business Logic:
        Sea freight is priced by CBM (volume), not by weight. Air freight is priced
        by chargeable weight (actual vs volumetric). This helper determines which
        pricing model to use for a given shipment method.
    """
    return method in {'sea', 'ksa_sea', 'ksa'}


def _is_air_method(method):
    """
    Check if a shipping method is an air-based method.

    Args:
        method (str): The shipping method code.

    Returns:
        bool: True if the method is air-based (air, ksa_air).

    Business Logic:
        Air freight needs special handling for volumetric weight (volume converted to weight).
        This helper identifies which shipments need chargeable weight calculations.
    """
    return method in {'air', 'ksa_air'}


class _OrderBuildError(Exception):
    """
    Raised inside an atomic block to abort an order save and roll it back.

    _build_order signals failure by RETURNING an error string, which cannot undo
    work already written inside a transaction. Wrapping that string in an
    exception lets the caller roll the transaction back and then report the same
    message to the user unchanged.
    """


def _build_order(request, order=None):
    """
    Shared logic for creating a new order or updating an existing order from POST data.

    Args:
        request (HttpRequest): The incoming POST request with all order form data.
        order (Order, optional): An existing Order instance to update. If None, a new order is created.

    Returns:
        tuple: (Order, str) — the order object and an error message (or None if success).

    Business Logic:
        This is the heart of order creation. It processes a complex form with:
        - Customer selection
        - Multiple products with quantities
        - Per-item shipment details (method, cargo type, CBM, weight, shipping company, cost)
        - Extra costs (customs, insurance, etc.)
        - Commission calculation
        - Payment status and notes
        - Show/hide shipping details toggle for customer portal

    Django Concepts:
        - request.POST.getlist(): Gets arrays of values from the form (e.g., multiple product_ids).
        - zip(): Iterates over multiple lists in parallel (product_ids, quantities, etc.).
        - Order.objects.create(): Creates a new order record.
        - order.items.all().delete(): Clears existing items before re-creating them (for updates).
        - order.save(): Persists the order with all calculated fields.
    """
    customer_id = request.POST.get('customer_id')
    # Get parallel arrays of form data for order items
    product_ids = request.POST.getlist('product_id')
    quantities = request.POST.getlist('quantity')
    shipment_nos = request.POST.getlist('shipment_no')
    shipment_names = request.POST.getlist('shipment_name')
    shipment_methods = request.POST.getlist('shipment_method')
    cargo_types = request.POST.getlist('cargo_type')
    shipment_cbms = request.POST.getlist('shipment_cbm')
    shipment_weights = request.POST.getlist('shipment_weight')
    shipment_volumetric_weights = request.POST.getlist('shipment_volumetric_weight')
    shipment_company_ids = request.POST.getlist('shipment_company_id')
    shipment_shipping_costs = request.POST.getlist('shipment_shipping_cost')
    shipment_statuses = request.POST.getlist('shipment_status')
    is_checked_list = request.POST.getlist('is_checked')
    # Per-line unit price. Blank falls back to the catalogue price, so a row
    # added without touching the field behaves exactly as before.
    unit_prices = request.POST.getlist('unit_price')
    status = request.POST.get('status', Order.STATUS_CONFIRMED)
    settings = CompanySettings.get_settings()

    try:
        # Look up the customer by ID; if not found, return an error
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return None, 'Customer not found'

    # -------------------------------------------------------------------------
    # VALIDATE EVERY LINE ITEM BEFORE WRITING ANYTHING
    # -------------------------------------------------------------------------
    # The item loop below used to swallow ValueError/TypeError/DoesNotExist and
    # `continue`, which meant a single mistyped quantity silently DELETED that
    # line from the order while the response still reported success with a
    # plausible total. On an order with fifteen lines nobody notices until the
    # customer asks where their goods are.
    #
    # Validating up front turns that into a refusal with the offending row
    # named, and — combined with the transaction wrapper on the callers — leaves
    # the existing order untouched when a save is rejected.
    # -------------------------------------------------------------------------
    for index, (product_id, qty) in enumerate(zip(product_ids, quantities), start=1):
        raw_qty = str(qty).strip()
        if not raw_qty:
            return None, f'Item {index}: quantity is missing.'
        try:
            parsed_qty = int(raw_qty)
        except (ValueError, TypeError):
            return None, f'Item {index}: "{raw_qty}" is not a valid quantity.'
        if parsed_qty <= 0:
            return None, f'Item {index}: quantity must be at least 1.'
        if not Product.objects.filter(id=product_id).exists():
            return None, f'Item {index}: the selected product no longer exists.'

    # Shipping companies (optional, multiple can be selected for an order)
    shipping_company_ids = request.POST.getlist('shipping_company_id')
    selected_companies = []
    for sc_id in shipping_company_ids:
        try:
            selected_companies.append(int(sc_id))
        except (ValueError, TypeError):
            pass

    if order is None:
        # Create a new order with the customer and a zero total (will be calculated below)
        order = Order.objects.create(customer=customer, total=0, status=status)
    else:
        # Update existing order: change customer and status, then clear all items for re-creation
        order.customer = customer
        order.status = status
        order.items.all().delete()

    # Initialize running totals for the order
    total = Decimal('0')
    calculated_weight = Decimal('0')
    calculated_cbm = Decimal('0')
    total_shipment_shipping = Decimal('0')
    # Transit status submitted per shipment block (shipment_no -> status). Applied
    # to ShipmentStatus rows after the order is saved. First non-empty wins.
    submitted_shipment_status = {}

    # Iterate over all submitted products in parallel using zip()
    for index, (product_id, qty) in enumerate(zip(product_ids, quantities)):
        try:
            product = Product.objects.get(id=product_id)
            quantity = int(qty)

            # THE LINE PRICE IS THE ORDER'S, NOT THE CATALOGUE'S.
            #
            # This read `product.price` unconditionally, which had two
            # consequences. Staff could not agree a different figure with a
            # customer - a bulk discount, a corrected quote - because the line
            # always snapped back to the listing. And re-saving an existing
            # order silently RE-PRICED it at today's catalogue price, so an
            # order placed at 168 became an order at 195 the moment somebody
            # opened it to change a shipping date. OrderItem.price exists
            # precisely to freeze what was agreed; that guarantee was being
            # broken by the edit path.
            #
            # Editing a line here never writes back to Product.price. The
            # catalogue is the list price; this is what one customer paid once.
            raw_price = unit_prices[index] if index < len(unit_prices) else ''
            if str(raw_price).strip():
                price = _to_decimal(raw_price, str(product.price))
                if price < 0:
                    price = product.price
            else:
                price = product.price

            # Parse per-item shipment details from the parallel form arrays
            # If the index is out of range, use sensible defaults
            shipment_no = int(shipment_nos[index]) if index < len(shipment_nos) and str(shipment_nos[index]).strip() else 1
            shipment_name = str(shipment_names[index]).strip()[:100] if index < len(shipment_names) else ''
            shipment_method = str(shipment_methods[index]).strip() if index < len(shipment_methods) and str(shipment_methods[index]).strip() else 'manual'
            # Validate the shipment method against the allowed choices
            if shipment_method not in {m[0] for m in SHIPPING_METHOD_CHOICES}:
                shipment_method = 'manual'
            cargo_type = str(cargo_types[index]).strip() if index < len(cargo_types) and str(cargo_types[index]).strip() else 'standard'
            if cargo_type not in {c[0] for c in CARGO_TYPE_CHOICES}:
                cargo_type = 'standard'
            shipment_cbm = _to_decimal(shipment_cbms[index], '0') if index < len(shipment_cbms) and str(shipment_cbms[index]).strip() else Decimal('0')
            shipment_weight = _to_decimal(shipment_weights[index], '0') if index < len(shipment_weights) and str(shipment_weights[index]).strip() else Decimal('0')
            shipment_volumetric_weight = _to_decimal(shipment_volumetric_weights[index], '0') if index < len(shipment_volumetric_weights) and str(shipment_volumetric_weights[index]).strip() else Decimal('0')
            # Look up the shipping company for this item (optional)
            raw_sc_id = shipment_company_ids[index] if index < len(shipment_company_ids) else ''
            shipment_company = None
            if raw_sc_id:
                try:
                    shipment_company = ShippingCompany.objects.get(id=int(raw_sc_id))
                except (ShippingCompany.DoesNotExist, ValueError, TypeError):
                    pass
            shipment_shipping_cost = _to_decimal(shipment_shipping_costs[index], '0') if index < len(shipment_shipping_costs) and str(shipment_shipping_costs[index]).strip() else Decimal('0')
            # Transit status for this shipment block (first non-empty value wins).
            raw_status = str(shipment_statuses[index]).strip() if index < len(shipment_statuses) else ''
            if raw_status and shipment_no not in submitted_shipment_status:
                submitted_shipment_status[shipment_no] = raw_status
            # Check if the item is marked as "checked" (used for invoice filtering)
            is_checked = str(is_checked_list[index]).strip().lower() in {'1', 'true', 'on', 'yes'} if index < len(is_checked_list) else False

            # Create the OrderItem linking the product to this order with all shipment details
            OrderItem.objects.create(order=order, product=product, shipment_no=shipment_no, shipment_name=shipment_name, shipment_method=shipment_method, cargo_type=cargo_type, shipment_cbm=shipment_cbm, shipment_weight=shipment_weight, shipment_volumetric_weight=shipment_volumetric_weight, shipment_company=shipment_company, shipment_shipping_cost=shipment_shipping_cost, quantity=quantity, price=price, is_checked=is_checked)
            total_shipment_shipping += shipment_shipping_cost
            total += price * quantity
            # Auto-calculation of weight/CBM from product data is disabled for now.
        except (Product.DoesNotExist, ValueError, TypeError) as exc:
            # Everything here was already validated above, so reaching this point
            # means something changed underneath us (e.g. a product deleted by
            # another user mid-save). Fail loudly rather than silently dropping
            # the line — the transaction on the caller rolls the whole save back.
            raise ValueError(f'Item {index + 1} could not be saved: {exc}') from exc

    # Order-level weight and CBM (manual overrides or auto-calculated fallbacks)
    manual_weight = request.POST.get('total_weight', '').strip()
    order.total_weight = _to_decimal(manual_weight, str(calculated_weight)) if manual_weight else calculated_weight
    order.total_cbm = _quantize_metric(_to_decimal(request.POST.get('total_cbm', '').strip(), str(calculated_cbm)) if request.POST.get('total_cbm', '').strip() else calculated_cbm)
    order.total = _quantize_money(total)

    # Commission calculation: percentage of the order total added as business profit
    commission_pct = _to_decimal(
        request.POST.get('commission_percentage', '').strip() or settings.commission_percentage,
        str(settings.commission_percentage),
    )
    order.commission_percentage = commission_pct
    order.commission_amount = _quantize_money(order.total * commission_pct / Decimal('100'))

    # Derive order-level shipping method and cargo type from the first non-manual item
    first_non_manual = None
    first_cargo = None
    for item in order.items.all():
        if item.shipment_method and item.shipment_method != 'manual':
            first_non_manual = item.shipment_method
            first_cargo = item.cargo_type
            break
    order.cargo_type = first_cargo or 'standard'
    order.shipping_method = first_non_manual or 'manual'
    order.shipping_rate = Decimal('0')  # Order-level rate is no longer used (per-shipment rates are used instead)
    order.shipping_cost = _quantize_money(total_shipment_shipping)

    # Extra costs (multiple items like customs, insurance, handling fees)
    extra_cost_amounts = request.POST.getlist('extra_cost_amount')
    extra_cost_reasons = request.POST.getlist('extra_cost_reason')
    extra_costs_data = []
    total_extra = Decimal('0')
    for amt, rsn in zip(extra_cost_amounts, extra_cost_reasons):
        amount = _to_decimal(amt, '0')
        if amount > 0:
            total_extra += amount
            extra_costs_data.append({'amount': _quantize_money(amount), 'reason': rsn.strip()[:255]})
    order.other_cost = _quantize_money(total_extra)
    order.other_cost_reason = ''

    # Payment status validation (must be one of the allowed values)
    valid_payment = {'unpaid', 'partial', 'paid'}
    submitted_payment = request.POST.get('payment_status', 'unpaid').strip()
    order.payment_status = submitted_payment if submitted_payment in valid_payment else 'unpaid'
    order.notes = request.POST.get('notes', '').strip()

    # Show shipping details toggle: controls whether the customer sees shipping breakdown
    show_shipping = request.POST.get('show_shipping_details')
    order.show_shipping_details = str(show_shipping).strip().lower() in {'1', 'true', 'on', 'yes'}
    order.save()
    order.shipping_companies.set(selected_companies)

    # Re-create extra cost rows (we deleted old ones if updating)
    order.extra_costs.all().delete()
    for ec in extra_costs_data:
        OrderExtraCost.objects.create(order=order, amount=ec['amount'], reason=ec['reason'])

    # -------------------------------------------------------------------------
    # Apply per-shipment transit statuses submitted on the form. We upsert the
    # ShipmentStatus row and, only when the value actually changed, notify the
    # customer and write an audit entry (so re-saving an order is not noisy).
    # -------------------------------------------------------------------------
    if submitted_shipment_status:
        from accounts.services import log_action, notify_customer
        valid_statuses = {c[0] for c in ShipmentStatus.STATUS_CHOICES}
        existing = {ss.shipment_no: ss.status for ss in order.shipment_statuses.all()}
        for sno, new_status in submitted_shipment_status.items():
            if new_status not in valid_statuses:
                continue
            if existing.get(sno) == new_status:
                continue  # unchanged — skip notification/audit
            obj, _created = ShipmentStatus.objects.update_or_create(
                order=order, shipment_no=sno, defaults={'status': new_status},
            )
            log_action(request, 'shipment.status', target=f'Order #{order.id} shipment {sno}',
                       detail=obj.get_status_display())
            notify_customer(
                order.customer,
                f'Shipment {sno} of order #{order.id} is now: {obj.get_status_display()}',
                notification_type='shipment', order=order,
            )

    return order, None


def _stale_shipment_days():
    """
    How many days without movement makes a shipment "stuck".

    Returns:
        int: the configured threshold, or 0 when the warning is switched off.

    Read from CompanySettings so the number can be tuned to how this business
    actually runs — a sea consolidation legitimately sits for weeks, an air
    shipment does not — rather than being a constant somebody has to redeploy.
    """
    from settings_manager.models import CompanySettings

    try:
        return int(CompanySettings.get_settings().stale_shipment_days or 0)
    except Exception:                                            # noqa: BLE001
        return 0


def _stale_shipment_order_ids(days):
    """
    Orders holding at least one shipment that has not moved in `days` days.

    Args:
        days (int): the staleness threshold.

    Returns:
        QuerySet: order ids, for use with `id__in`.

    Delivered shipments are excluded — a delivered consignment is finished, and
    it not changing is the correct outcome rather than a neglected one. This is
    the query behind both the dashboard's "shipments with no movement" item and
    the `?stale=1` filter, so the count you click always matches the list you
    land on.
    """
    from django.utils import timezone as _tz

    cutoff = _tz.now() - _tz.timedelta(days=days)
    return (ShipmentStatus.objects
            .exclude(status=ShipmentStatus.STATUS_DELIVERED)
            .filter(updated_at__lt=cutoff)
            .values_list('order_id', flat=True))


@module_required('orders')
def bulk_order_action(request):
    """
    Apply one status change to every selected order in a single request.

    Args:
        request (HttpRequest): POST carrying `order_ids` (repeated), `action`, and
                               `next` (the list URL to return to, filters intact).

    Returns:
        HttpResponseRedirect: Back to the order list the action was launched from.

    Business Logic:
        After a supplier run the admin needs to mark a batch of orders as placed.
        One at a time that is a click and a round trip per order; on twenty orders
        it is twenty of each. This applies the change to the whole selection in a
        single UPDATE.

        Supported actions are deliberately limited to reversible status flags —
        placed/not placed and paid/unpaid. Nothing here deletes or alters money,
        because a bulk control that can destroy twenty records on a mis-click is
        not worth the time it saves. Deletion stays a single-order action with its
        own confirmation.

        `next` is validated before redirecting: an unvalidated redirect target
        taken from POST data is an open-redirect vulnerability.
    """
    if request.method != 'POST':
        return redirect('order_list')

    # url_has_allowed_host_and_scheme rejects absolute URLs pointing off-site, so a
    # crafted `next` cannot bounce a logged-in admin to an attacker's page.
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = reverse('order_list')

    order_ids = request.POST.getlist('order_ids')
    if not order_ids:
        messages.warning(request, 'No orders were selected.')
        return redirect(next_url)

    action = request.POST.get('action', '')

    # Moving a batch of shipments along the transit timeline. Handled separately
    # from the flag updates below because it is not a single UPDATE: each order
    # needs its own ShipmentStatus rows, its own customer notification and its
    # own audit entry.
    if action == 'set_shipment_status':
        return _bulk_set_shipment_status(request, order_ids, next_url)

    updates = {
        'mark_placed': ({'is_placed': True}, 'marked as placed'),
        'mark_not_placed': ({'is_placed': False}, 'marked as not placed'),
        'mark_paid': ({'payment_status': 'paid'}, 'marked as paid'),
        'mark_unpaid': ({'payment_status': 'unpaid'}, 'marked as unpaid'),
    }
    if action not in updates:
        messages.error(request, 'Unknown bulk action.')
        return redirect(next_url)

    fields, verb = updates[action]
    count = Order.objects.filter(id__in=order_ids).update(**fields)
    messages.success(request, f'{count} order{"" if count == 1 else "s"} {verb}.')
    return redirect(next_url)


def _bulk_set_shipment_status(request, order_ids, next_url):
    """
    Move every shipment block of the selected orders to one transit status.

    Args:
        request (HttpRequest): carries `shipment_status`.
        order_ids (list[str]): the selected orders.
        next_url (str): validated return URL.

    Returns:
        HttpResponseRedirect: back to the order list.

    WHY THIS IS THE BULK ACTION THAT MATTERS

    A container leaves the port with thirty consignments on it, and every one of
    them moves to "On the Way" on the same day. Per order that was a page load, a
    dropdown, a submit and a redirect — thirty times, for a single real-world
    event. Marking orders placed or paid already had a bulk control; the status
    staff touch most often did not.

    ALREADY-DELIVERED BLOCKS ARE LEFT ALONE

    Bulk is precisely where you cannot see what you are changing, and dragging a
    delivered shipment backwards into "At Customs" tells a customer their
    completed order is in transit again. Correcting one of those stays a
    single-order action, where the current state is on screen. The result message
    says how many were skipped so it is never silent.
    """
    from accounts.services import log_action, notify_customer

    status = request.POST.get('shipment_status', '')
    if status not in dict(ShipmentStatus.STATUS_CHOICES):
        messages.error(request, 'Choose a shipment status to apply.')
        return redirect(next_url)

    label = dict(ShipmentStatus.STATUS_CHOICES)[status]
    orders = (Order.objects.filter(id__in=order_ids)
              .select_related('customer').prefetch_related('items', 'shipment_statuses'))

    changed_orders = 0
    changed_blocks = 0
    skipped_delivered = 0

    for order in orders:
        # An order is split into shipment blocks by OrderItem.shipment_no. An
        # order whose items carry no block number is a single shipment.
        blocks = sorted({item.shipment_no or 1 for item in order.items.all()}) or [1]
        existing = {s.shipment_no: s for s in order.shipment_statuses.all()}

        touched = 0
        for block in blocks:
            current = existing.get(block)
            if current is not None and current.status == ShipmentStatus.STATUS_DELIVERED:
                skipped_delivered += 1
                continue
            if current is not None and current.status == status:
                continue  # already there; not a change worth reporting
            ShipmentStatus.objects.update_or_create(
                order=order, shipment_no=block, defaults={'status': status},
            )
            touched += 1

        if not touched:
            continue

        changed_orders += 1
        changed_blocks += touched
        log_action(request, 'shipment.status.bulk',
                   target=f'Order #{order.id}', detail=label)
        # One notification per ORDER, not per block: a customer whose order ships
        # in three cartons does not want three identical messages.
        notify_customer(
            order.customer,
            f'Order #{order.id} is now: {label}',
            notification_type='shipment', order=order,
        )

    if changed_orders:
        parts = [f'{changed_blocks} shipment{"" if changed_blocks == 1 else "s"} '
                 f'across {changed_orders} order{"" if changed_orders == 1 else "s"} '
                 f'marked "{label}"']
        if skipped_delivered:
            parts.append(f'{skipped_delivered} already delivered and left unchanged')
        messages.success(request, '. '.join(parts) + '.')
    elif skipped_delivered:
        messages.warning(
            request,
            f'Nothing changed — all {skipped_delivered} selected shipments are already delivered.')
    else:
        messages.info(request, f'Nothing to change; those shipments are already "{label}".')

    return redirect(next_url)


@module_required('orders')
def order_list(request):
    """
    Display the main order management dashboard with statistics and shipment filtering.

    Args:
        request (HttpRequest): The incoming HTTP request from the browser.

    Returns:
        HttpResponse: A rendered HTML page with all orders, customer list, product list,
                      shipping company data, and aggregated statistics.

    Business Logic:
        This is the admin's primary view for managing orders. It shows:
        - All orders with customer and item details (newest first)
        - Summary statistics (total orders, drafts, confirmed, unpaid, partial, paid)
        - Shipping company data as JSON for the frontend calculator
        - Items grouped by air vs sea methods (for the By Air / By Sea tabs)
        This page is the central hub for order tracking and management.

    Django Concepts:
        - Order.objects.select_related('customer').prefetch_related('items__product'):
          Fetches orders with customers and all items/products in optimized queries.
        - .aggregate(): Computes multiple statistics in a single database query.
        - Count('id', filter=Q(...)): Counts orders matching specific conditions.
        - Sum('total', filter=Q(...)): Sums order totals for matching conditions.
        - json.dumps(): Serializes Python dicts to JSON strings for the JavaScript frontend.
    """
    # Fetch all orders with customer and item/product data (optimized queries)
    orders = Order.objects.select_related('customer').prefetch_related('items__product').all().order_by('-date')

    # --- Search ---
    # Runs in the database so it searches every order, not just the 25 rows on the
    # current page. Matches order number, customer name, product name, and notes.
    query = request.GET.get('q', '').strip()
    if query:
        order_filter = (
            Q(customer__name__icontains=query)
            | Q(items__product__name__icontains=query)
            | Q(notes__icontains=query)
        )
        # A bare number is almost always an order ID, so match that too.
        if query.lstrip('#').isdigit():
            order_filter = order_filter | Q(id=int(query.lstrip('#')))
        orders = orders.filter(order_filter).distinct()

    # --- Status filters ---
    # These back the "Needs Attention" links on the dashboard, so a count there
    # lands on exactly the rows it counted rather than the unfiltered list.
    placed_filter = request.GET.get('placed', '')
    if placed_filter == 'no':
        orders = orders.filter(is_placed=False)
    elif placed_filter == 'yes':
        orders = orders.filter(is_placed=True)

    payment_filter = request.GET.get('payment', '')
    if payment_filter in ('unpaid', 'partial', 'paid'):
        orders = orders.filter(payment_status=payment_filter)

    # -------------------------------------------------------------------------
    # WHERE IS IT? — filtering by position in the transit pipeline
    # -------------------------------------------------------------------------
    # The list could be filtered by paid and by placed, but not by the ten-step
    # status the goods actually move through. "What is sitting at customs?" and
    # "what is ready to dispatch?" are the two questions asked every morning and
    # neither could be answered without opening orders one at a time.
    # -------------------------------------------------------------------------
    shipment_filter = request.GET.get('shipment', '')
    if shipment_filter in dict(ShipmentStatus.STATUS_CHOICES):
        orders = orders.filter(shipment_statuses__status=shipment_filter).distinct()

    # Shipments that have not moved in a while. `stale=1` is what the dashboard's
    # attention queue links to, so the two always agree on what counts as stuck.
    stale_days = _stale_shipment_days()
    if request.GET.get('stale') == '1' and stale_days:
        orders = orders.filter(
            id__in=_stale_shipment_order_ids(stale_days)).distinct()

    customers = Customer.objects.all()

    # ---------------------------------------------------------------------
    # ONLY THE FIRST PAGE OF THE CATALOGUE
    # ---------------------------------------------------------------------
    # This page used to embed EVERY product twice - once as a picker row with
    # an image, once as a JavaScript array - so the quotation box could filter
    # client-side. The weight of the busiest screen in the back office was
    # therefore a function of how big the catalogue is: 169 KB at 30 products,
    # 810 KB at 500, and about 5 MB at 3,000.
    #
    # The first 50 are still rendered so the picker is useful the instant it
    # opens; anything past that comes from /orders/product-lookup/, which
    # searches the WHOLE catalogue rather than only what was rendered. That is
    # what staff already assumed the search box did.
    # ---------------------------------------------------------------------
    products = (Product.objects
                .filter(is_draft=False)
                .prefetch_related('images')
                .order_by('name')[:ORDER_BUILDER_PAGE_SIZE])
    product_total = Product.objects.filter(is_draft=False).count()
    shipping_companies = list(ShippingCompany.objects.all())
    settings = CompanySettings.get_settings()

    # Build JSON-safe company data for the frontend JavaScript shipping calculator
    companies_for_js = [{'id': 0, 'name': '— None —', 'rates': None}]
    for sc in shipping_companies:
        companies_for_js.append({
            'id': sc.id,
            'name': sc.name,
            'rates': {
                'standard': {
                    'air': float(sc.air_rate), 'sea': float(sc.sea_rate),
                    'ksa_air': float(sc.ksa_air_rate), 'ksa_sea': float(sc.ksa_sea_rate),
                    'ksa': float(sc.ksa_sea_rate),
                },
                'no_brand_battery': {
                    'air': float(sc.nbb_air_rate), 'sea': float(sc.nbb_sea_rate),
                    'ksa_air': float(sc.nbb_ksa_air_rate), 'ksa_sea': float(sc.nbb_ksa_sea_rate),
                    'ksa': float(sc.nbb_ksa_sea_rate),
                },
            },
        })
    shipping_companies_json = json.dumps(companies_for_js)

    # Stats for summary cards at the top of the page
    totals = orders.aggregate(
        total_count=Count('id'),
        draft_count=Count('id', filter=Q(status='draft')),
        confirmed_count=Count('id', filter=Q(status='confirmed')),
        unpaid_count=Count('id', filter=Q(payment_status='unpaid')),
        partial_count=Count('id', filter=Q(payment_status='partial')),
        paid_count=Count('id', filter=Q(payment_status='paid')),
        unpaid_total=Sum('total', filter=Q(payment_status='unpaid')),
        partial_total=Sum('total', filter=Q(payment_status='partial')),
    )

    # -------------------------------------------------------------------------
    # PAGINATION — must happen BEFORE the shipment tabs are built
    # -------------------------------------------------------------------------
    # The By Air / By Sea tabs below used to be built from
    # `OrderItem.objects.all()` — every line item ever created — with no
    # pagination and no filtering. Pagination protected the main table only, so
    # the page grew without limit: measured at 254 KB of HTML for 10 orders,
    # 2.2 MB at 300, and 7.0 MB at 800. The search box made it worse rather than
    # better, because filtering the table left the tabs showing everything, which
    # looked like the search had silently failed.
    #
    # Paginating first and scoping the tabs to the orders actually on this page
    # makes the page a fixed size at any data volume, and makes the tabs agree
    # with the table and with the search.
    # -------------------------------------------------------------------------
    page_number = request.GET.get('page', 1)
    paginator = Paginator(orders, 25)
    page_obj = paginator.get_page(page_number)
    page_order_ids = [o.id for o in page_obj.object_list]

    # Build grouped shipment rows for the By Air / By Sea tabs
    air_methods = {'air', 'ksa_air'}
    sea_methods = {'sea', 'ksa_sea', 'ksa'}
    all_items = (
        OrderItem.objects
        .select_related('order__customer', 'product', 'shipment_company')
        .filter(order_id__in=page_order_ids)
    )

    # Current transit status per (order, shipment block), so the shipment tabs
    # can show a status dropdown pre-selected with the latest value. Scoped to the
    # same page — this used to load every ShipmentStatus row in the database to
    # populate at most 25 orders' worth of dropdowns.
    status_map = {
        (ss.order_id, ss.shipment_no): ss.status
        for ss in ShipmentStatus.objects.filter(order_id__in=page_order_ids)
    }

    air_items = []
    sea_items = []
    for item in all_items:
        p = item.product
        # Weight/CBM auto-calculation from product data is disabled for now.
        row = {
            'order_id': item.order_id,
            'customer': item.order.customer,
            'shipment_no': item.shipment_no,
            'shipment_name': item.shipment_name,
            'shipment_company': item.shipment_company,
            'product': p,
            'quantity': item.quantity,
            'actual_weight': Decimal('0'),
            'volumetric_weight': _quantize_metric(item.shipment_volumetric_weight) if item.shipment_volumetric_weight else Decimal('0'),
            'cbm': item.shipment_cbm if item.shipment_cbm else Decimal('0'),
            'shipping_cost': item.shipment_shipping_cost,
            'method': item.shipment_method,
            'transit_status': status_map.get((item.order_id, item.shipment_no or 1), ''),
        }
        if item.shipment_method in air_methods:
            air_items.append(row)
        elif item.shipment_method in sea_methods:
            sea_items.append(row)

    return render(request, 'orders/order_list.html', {
        'page_obj': page_obj,
        'query': query,
        'placed_filter': placed_filter,
        'payment_filter': payment_filter,
        'shipment_filter': shipment_filter,
        'stale_filter': request.GET.get('stale') == '1',
        'stale_days': stale_days,
        # True when any filter is active, so the template can offer a "clear" link.
        'has_filters': bool(query or placed_filter or payment_filter),
        'total_count': paginator.count,
        # Lets the shipment tabs say which orders they are showing, instead of
        # silently presenting a partial list as if it were everything.
        'page_order_count': len(page_order_ids),
        'customers': customers,
        'products': products,
        'product_total': product_total,
        'product_page_size': ORDER_BUILDER_PAGE_SIZE,
        'shipping_companies': shipping_companies,
        'shipping_companies_json': shipping_companies_json,
        'currency': settings.currency,
        'default_commission_pct': settings.commission_percentage,
        'air_shipping_rate': settings.air_shipping_rate,
        'sea_shipping_rate': settings.sea_shipping_rate,
        'ksa_shipping_rate': settings.ksa_shipping_rate,
        'ksa_air_shipping_rate': settings.ksa_air_shipping_rate,
        'ksa_sea_shipping_rate': settings.ksa_sea_shipping_rate,
        'nbb_air_shipping_rate': settings.no_brand_battery_air_shipping_rate,
        'nbb_sea_shipping_rate': settings.no_brand_battery_sea_shipping_rate,
        'nbb_ksa_air_shipping_rate': settings.no_brand_battery_ksa_air_shipping_rate,
        'nbb_ksa_sea_shipping_rate': settings.no_brand_battery_ksa_sea_shipping_rate,
        'stats': totals,
        'air_items': air_items,
        'sea_items': sea_items,
        'shipment_status_choices': ShipmentStatus.STATUS_CHOICES,
    })


@module_required('orders')
def amazon_order_list(request):
    """
    Display the order management page filtered to orders containing Amazon-sourced products.

    Args:
        request (HttpRequest): The incoming HTTP request.

    Returns:
        HttpResponse: Rendered order list page with only Amazon marketplace orders.
    """
    # Reuse the main order list view but filter for Amazon products
    amazon_orders = Order.objects.select_related('customer').prefetch_related('items__product').filter(
        items__product__source='amazon'
    ).distinct().order_by('-date')

    customers = Customer.objects.all()
    products = Product.objects.prefetch_related('images').all()
    shipping_companies = list(ShippingCompany.objects.all())
    settings = CompanySettings.get_settings()

    companies_for_js = [{'id': 0, 'name': '— None —', 'rates': None}]
    for sc in shipping_companies:
        companies_for_js.append({
            'id': sc.id,
            'name': sc.name,
            'rates': {
                'standard': {
                    'air': float(sc.air_rate), 'sea': float(sc.sea_rate),
                    'ksa_air': float(sc.ksa_air_rate), 'ksa_sea': float(sc.ksa_sea_rate),
                    'ksa': float(sc.ksa_sea_rate),
                },
                'no_brand_battery': {
                    'air': float(sc.nbb_air_rate), 'sea': float(sc.nbb_sea_rate),
                    'ksa_air': float(sc.nbb_ksa_air_rate), 'ksa_sea': float(sc.nbb_ksa_sea_rate),
                    'ksa': float(sc.nbb_ksa_sea_rate),
                },
            },
        })
    shipping_companies_json = json.dumps(companies_for_js)

    totals = amazon_orders.aggregate(
        total_count=Count('id'),
        draft_count=Count('id', filter=Q(status='draft')),
        confirmed_count=Count('id', filter=Q(status='confirmed')),
        unpaid_count=Count('id', filter=Q(payment_status='unpaid')),
        partial_count=Count('id', filter=Q(payment_status='partial')),
        paid_count=Count('id', filter=Q(payment_status='paid')),
        unpaid_total=Sum('total', filter=Q(payment_status='unpaid')),
        partial_total=Sum('total', filter=Q(payment_status='partial')),
    )

    air_methods = {'air', 'ksa_air'}
    sea_methods = {'sea', 'ksa_sea', 'ksa'}
    amazon_items = OrderItem.objects.select_related('order__customer', 'product', 'shipment_company').filter(
        order__in=amazon_orders
    )
    air_items = []
    sea_items = []
    for item in amazon_items:
        p = item.product
        row = {
            'order_id': item.order_id,
            'customer': item.order.customer,
            'shipment_no': item.shipment_no,
            'shipment_name': item.shipment_name,
            'shipment_company': item.shipment_company,
            'product': p,
            'quantity': item.quantity,
            'actual_weight': Decimal('0'),
            'volumetric_weight': _quantize_metric(item.shipment_volumetric_weight) if item.shipment_volumetric_weight else Decimal('0'),
            'cbm': item.shipment_cbm if item.shipment_cbm else Decimal('0'),
            'shipping_cost': item.shipment_shipping_cost,
            'method': item.shipment_method,
        }
        if item.shipment_method in air_methods:
            air_items.append(row)
        elif item.shipment_method in sea_methods:
            sea_items.append(row)

    page_number = request.GET.get('page', 1)
    paginator = Paginator(amazon_orders, 25)
    page_obj = paginator.get_page(page_number)

    return render(request, 'orders/order_list.html', {
        'orders': amazon_orders,
        'page_obj': page_obj,
        'customers': customers,
        'products': products,
        'shipping_companies': shipping_companies,
        'shipping_companies_json': shipping_companies_json,
        'currency': settings.currency,
        'default_commission_pct': settings.commission_percentage,
        'air_shipping_rate': settings.air_shipping_rate,
        'sea_shipping_rate': settings.sea_shipping_rate,
        'ksa_shipping_rate': settings.ksa_shipping_rate,
        'ksa_air_shipping_rate': settings.ksa_air_shipping_rate,
        'ksa_sea_shipping_rate': settings.ksa_sea_shipping_rate,
        'nbb_air_shipping_rate': settings.no_brand_battery_air_shipping_rate,
        'nbb_sea_shipping_rate': settings.no_brand_battery_sea_shipping_rate,
        'nbb_ksa_air_shipping_rate': settings.no_brand_battery_ksa_air_shipping_rate,
        'nbb_ksa_sea_shipping_rate': settings.no_brand_battery_ksa_sea_shipping_rate,
        'stats': totals,
        'air_items': air_items,
        'sea_items': sea_items,
        'is_amazon_orders': True,
    })


@module_required('orders')
def add_order(request):
    """
    AJAX endpoint: Create a new order from POST data.

    Args:
        request (HttpRequest): The incoming AJAX POST request with order form data.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        The admin fills in the order form (customer, products, quantities, shipping details)
        and submits it. This endpoint creates the order and returns a success message with
        the order total. If the status is 'draft', it's saved as a draft for later editing.
    """
    if request.method == 'POST':
        # transaction.atomic so a failure part-way through leaves no half-built
        # order behind. _build_order creates the Order row first and then adds
        # items one at a time; without this, an exception midway committed an
        # order with only some of its line items and a total that did not match.
        try:
            with transaction.atomic():
                order, error = _build_order(request)
                if error:
                    # Raising rather than returning rolls back the partially
                    # created order; the message is re-surfaced below.
                    raise _OrderBuildError(error)
        except _OrderBuildError as exc:
            return JsonResponse({'success': False, 'message': str(exc)})
        except ValueError as exc:
            return JsonResponse({'success': False, 'message': str(exc)})
        label = 'Draft saved' if order.status == Order.STATUS_DRAFT else f'Order #{order.id} created'
        return JsonResponse({'success': True, 'message': f'{label}! Total: {order.total}'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('orders')
def edit_order(request, order_id):
    """
    AJAX endpoint: Get or update an existing order.

    Args:
        request (HttpRequest): The incoming GET or POST request.
        order_id (int): The primary key of the order to edit.

    Returns:
        JsonResponse (GET): Full order data including items, shipping companies, extra costs.
        JsonResponse (POST): {'success': True/False, 'message': '...'} after saving.

    Business Logic:
        GET: The frontend fetches the order data to populate the edit form.
        POST: The updated form data is processed and the order is rebuilt with new values.

    Django Concepts:
        - Order.objects.prefetch_related('items__product'): Fetches the order with all items and products.
        - order.shipping_companies.values('id', 'name', 'website'): Gets linked shipping companies as dicts.
        - list(order.shipping_companies.values(...)): Converts QuerySet to a list for JSON serialization.
    """
    try:
        order = Order.objects.prefetch_related('items__product').get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)

    if request.method == 'GET':
        # Current transit status per shipment block, so the edit form can
        # pre-select each shipment's status dropdown.
        status_map = {ss.shipment_no: ss.status for ss in order.shipment_statuses.all()}
        # Build a list of item dictionaries for the frontend edit form
        items = [{'product_id': item.product.id, 'quantity': item.quantity, 'shipment_no': item.shipment_no, 'shipment_name': item.shipment_name, 'shipment_method': item.shipment_method, 'cargo_type': item.cargo_type, 'shipment_cbm': str(item.shipment_cbm), 'shipment_weight': str(item.shipment_weight), 'shipment_volumetric_weight': str(item.shipment_volumetric_weight), 'shipment_company_id': item.shipment_company_id or '', 'shipment_shipping_cost': str(item.shipment_shipping_cost), 'is_checked': item.is_checked, 'price': str(item.price), 'shipment_status': status_map.get(item.shipment_no, '')} for item in order.items.all()]
        companies = list(order.shipping_companies.values('id', 'name', 'website'))
        return JsonResponse({
            'id': order.id,
            'customer_id': order.customer.id,
            'status': order.status,
            'shipping_cost': str(order.shipping_cost),
            'shipping_method': order.shipping_method if order.shipping_method != 'manual' else '',
            'cargo_type': order.cargo_type,
            'shipping_rate': str(order.shipping_rate),
            'shipping_company_ids': [c['id'] for c in companies],
            'other_cost': str(order.other_cost),
            'other_cost_reason': order.other_cost_reason,
            'extra_costs': [{'amount': str(ec.amount), 'reason': ec.reason} for ec in order.extra_costs.all()],
            'commission_percentage': str(order.commission_percentage),
            'total_weight': str(order.total_weight),
            'total_cbm': str(order.total_cbm),
            'payment_status': order.payment_status,
            'is_placed': order.is_placed,
            'notes': order.notes,
            'show_shipping_details': order.show_shipping_details,
            'items': items,
        })

    if request.method == 'POST':
        # This is the dangerous path: _build_order does `order.items.all().delete()`
        # before re-creating the items from the submitted form. Without a
        # transaction, any failure after that delete left the order stripped of
        # every line item with no way to recover them. The atomic block makes the
        # edit all-or-nothing — a rejected save leaves the order exactly as it was.
        try:
            with transaction.atomic():
                order, error = _build_order(request, order=order)
                if error:
                    raise _OrderBuildError(error)
        except _OrderBuildError as exc:
            return JsonResponse({'success': False, 'message': str(exc)})
        except ValueError as exc:
            return JsonResponse({'success': False, 'message': str(exc)})
        return JsonResponse({'success': True, 'message': f'Order #{order.id} updated!'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('orders')
def confirm_order(request, order_id):
    """
    AJAX endpoint: Change an order's status from 'draft' to 'confirmed'.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        order_id (int): The primary key of the order to confirm.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        Draft orders are preliminary (still being edited). Once the admin is satisfied,
        they "confirm" the order, which locks it and makes it visible for invoicing and
        shipping. This is a key workflow step in the order lifecycle.
    """
    if request.method == 'POST':
        try:
            order = Order.objects.get(id=order_id)
            order.status = Order.STATUS_CONFIRMED
            order.save()
            _notify_customer_order_status(
                order,
                subject=f'Order #{order.id} Confirmed — {CompanySettings.get_settings().company_name}',
                headline=f'Your order #{order.id} has been confirmed and is being processed.',
            )
            return JsonResponse({'success': True, 'message': f'Order #{order.id} confirmed!'})
        except Order.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Order not found'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('orders')
def order_detail(request, order_id):
    """
    Return detailed order information as JSON (for the customer portal or detail view).

    Args:
        request (HttpRequest): The incoming HTTP request.
        order_id (int): The primary key of the order to retrieve.

    Returns:
        JsonResponse: Full order details including customer, items, totals, shipping, and costs.

    Business Logic:
        This endpoint is used by the customer portal to show order details and by the admin
        to view order information without loading the full edit form. It includes all financial
        breakdowns (subtotals, shipping, commission, extra costs).
    """
    try:
        order = Order.objects.select_related('customer').prefetch_related('items__product', 'shipping_companies').get(id=order_id)
        items = []
        for item in order.items.all():
            items.append({
                'product': item.product.name,
                'quantity': item.quantity,
                'shipment_no': item.shipment_no,
                'shipment_cbm': str(item.shipment_cbm),
                'price': str(item.price),
                'subtotal': str(item.price * item.quantity),
                'weight': None,
            })
        return JsonResponse({
            'customer': order.customer.name,
            'date': order.date.strftime('%b %d, %Y %H:%M'),
            'total': str(order.total),
            'commission_amount': str(order.commission_amount),
            'commission_percentage': str(order.commission_percentage),
            'shipping_cost': str(order.shipping_cost),
            'other_cost': str(order.other_cost),
            'other_cost_reason': order.other_cost_reason,
            'extra_costs': [{'amount': str(ec.amount), 'reason': ec.reason} for ec in order.extra_costs.all()],
            'total_weight': str(order.total_weight),
            'total_cbm': str(order.total_cbm),
            'status': order.status,
            'payment_status': order.payment_status,
            'is_placed': order.is_placed,
            'notes': order.notes,
            'shipping_companies': list(order.shipping_companies.values('id', 'name', 'website')),
            'items': items,
        })
    except Order.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)



def _compute_invoice_data(order, settings=None):
    """
    Compute all invoice data for an order, including per-shipment breakdowns.

    Args:
        order (Order): The order to compute invoice data for.
        settings (CompanySettings, optional): Company settings. If None, fetched automatically.

    Returns:
        dict: A comprehensive dictionary with all invoice data, including:
            - order, settings, shipping_companies, extra_costs
            - grand_total, grand_total_with_commission
            - invoice_items (flat list), invoice_shipments (grouped by shipment_no)
            - multi_shipment flag, effective rates, shipping totals
            - Currency conversion data (if exchange rate is enabled)

    Business Logic:
        This is the most complex calculation in the system. It handles:
        1. Grouping items by shipment number (an order can have multiple shipments)
        2. For each shipment, calculating:
           - Shipping method and cargo type
           - Weight, volumetric weight, chargeable weight (for air)
           - CBM (for sea)
           - Shipping cost (using company-specific rates or global fallbacks)
           - Landed cost per item (unit price + shipping per unit)
        3. Order-level totals and commission
        4. Currency conversion (if dual-currency is enabled)
        5. Effective rates (actual cost per CBM or per KG for reporting)

    Django Concepts:
        - This is a pure Python function (not a view), called by order_invoice and order_excel_export.
        - Decimal is used throughout to avoid floating-point errors in financial calculations.
        - getattr(sc, rate_attr, 0): Dynamically accesses the correct rate field on the ShippingCompany model.
    """
    if settings is None:
        settings = CompanySettings.get_settings()

    # Group items by shipment_no (e.g., shipment 1: air items, shipment 2: sea items)
    shipments_dict = {}
    for item in order.items.all():
        sno = item.shipment_no or 1
        if sno not in shipments_dict:
            shipments_dict[sno] = []
        shipments_dict[sno].append(item)

    # Order-level totals used as fallback values inside the per-shipment loop
    total_order_qty = sum(item.quantity for item in order.items.all())
    order_shipping = Decimal(str(order.shipping_cost)) if order.shipping_cost else Decimal('0')
    total_cbm = Decimal(str(order.total_cbm)) if order.total_cbm else Decimal('0')
    total_weight = Decimal(str(order.total_weight)) if order.total_weight else Decimal('0')
    effective_rate_cbm = _quantize_money(order_shipping / total_cbm) if total_cbm > 0 and order_shipping > 0 else None
    effective_rate_weight = _quantize_money(order_shipping / total_weight) if total_weight > 0 and order_shipping > 0 else None
    # Overall shipping per unit for the order-level totals section
    shipping_per_unit_order = _quantize_money(order_shipping / Decimal(total_order_qty)) if total_order_qty > 0 and order_shipping > 0 else Decimal('0')

    invoice_shipments = []
    invoice_items = []
    for sno in sorted(shipments_dict.keys()):
        items_in_shipment = shipments_dict[sno]
        # Per-shipment method and cargo type (all items in a shipment share the same method)
        shipment_method = items_in_shipment[0].shipment_method if items_in_shipment else 'manual'
        cargo_type = items_in_shipment[0].cargo_type if items_in_shipment else 'standard'
        uses_cbm = shipment_method in {'sea', 'ksa_sea', 'ksa'}
        uses_air = _is_air_method(shipment_method)

        shipment_weight_auto = Decimal('0')
        rows = []
        for item in items_in_shipment:
            first_image = item.product.primary_image
            qty = item.quantity
            product = item.product
            # Auto-calculation of weight from product data is disabled for now.
            piece_weight = Decimal('0')
            item_weight = None
            row = {
                'name': product.name,
                'sku': product.sku or '—',
                'weight': piece_weight,
                'item_weight': item_weight,
                'quantity': qty,
                'price': item.price,
                'subtotal': item.price * qty,
                'image_url': first_image.src if first_image else None,
                'item_cbm': None,
                'is_checked': item.is_checked,
            }
            rows.append(row)
            invoice_items.append(row)

        # Use stored CBM/weight if set. Auto-calculation of CBM and volumetric
        # weight from product dimensions is currently disabled.
        first_cbm = Decimal(str(items_in_shipment[0].shipment_cbm)) if items_in_shipment else Decimal('0')
        shipment_cbm = first_cbm
        first_weight = Decimal(str(items_in_shipment[0].shipment_weight)) if items_in_shipment else Decimal('0')
        shipment_weight = first_weight if first_weight > 0 else shipment_weight_auto
        total_qty_in_shipment = sum(row['quantity'] for row in rows)

        # For air, compute chargeable weight from actual vs volumetric.
        # Volumetric weight is taken from the manual override only.
        stored_vol_weight = Decimal(str(items_in_shipment[0].shipment_volumetric_weight)) if items_in_shipment else Decimal('0')
        shipment_volumetric_weight = stored_vol_weight
        chargeable_weight = shipment_weight
        if uses_air:
            chargeable_weight = max(shipment_weight, shipment_volumetric_weight)

        # Per-shipment shipping cost: use saved value first
        est_ship_cost = _quantize_money(items_in_shipment[0].shipment_shipping_cost) if items_in_shipment and items_in_shipment[0].shipment_shipping_cost else Decimal('0')
        # Determine rate for this shipment (company-specific if available, else global)
        sc = items_in_shipment[0].shipment_company if items_in_shipment else None
        rate = Decimal('0')
        if sc:
            rate_attr = None
            # Choose the correct rate field based on cargo type and shipping method
            if cargo_type == 'no_brand_battery':
                rate_map = {
                    'air': 'nbb_air_rate', 'sea': 'nbb_sea_rate',
                    'ksa_air': 'nbb_ksa_air_rate', 'ksa_sea': 'nbb_ksa_sea_rate', 'ksa': 'nbb_ksa_sea_rate',
                }
                rate_attr = rate_map.get(shipment_method)
            else:
                rate_map = {
                    'air': 'air_rate', 'sea': 'sea_rate',
                    'ksa_air': 'ksa_air_rate', 'ksa_sea': 'ksa_sea_rate', 'ksa': 'ksa_sea_rate',
                }
                rate_attr = rate_map.get(shipment_method)
            if rate_attr:
                rate = Decimal(str(getattr(sc, rate_attr, 0) or 0))
        if rate == Decimal('0') and shipment_method != 'manual':
            # Fall back to global settings if no company-specific rate is found
            global_rate_map = {
                ('standard', 'air'): settings.air_shipping_rate,
                ('standard', 'sea'): settings.sea_shipping_rate,
                ('standard', 'ksa_air'): settings.ksa_air_shipping_rate,
                ('standard', 'ksa_sea'): settings.ksa_sea_shipping_rate,
                ('standard', 'ksa'): settings.ksa_shipping_rate,
                ('no_brand_battery', 'air'): settings.no_brand_battery_air_shipping_rate,
                ('no_brand_battery', 'sea'): settings.no_brand_battery_sea_shipping_rate,
                ('no_brand_battery', 'ksa_air'): settings.no_brand_battery_ksa_air_shipping_rate,
                ('no_brand_battery', 'ksa_sea'): settings.no_brand_battery_ksa_sea_shipping_rate,
                ('no_brand_battery', 'ksa'): settings.no_brand_battery_ksa_sea_shipping_rate,
            }
            rate = Decimal(str(global_rate_map.get((cargo_type, shipment_method), 0) or 0))

        # Calculate shipping cost if not manually provided
        if est_ship_cost == Decimal('0'):
            if rate > 0:
                if uses_cbm:
                    est_ship_cost = _quantize_money(shipment_cbm * rate)
                elif uses_air:
                    est_ship_cost = _quantize_money(chargeable_weight * rate)
                else:
                    est_ship_cost = _quantize_money(shipment_weight * rate)
            elif total_cbm > 0 and order_shipping > 0:
                est_ship_cost = _quantize_money(order_shipping * shipment_cbm / total_cbm)
            elif total_order_qty > 0 and order_shipping > 0:
                est_ship_cost = _quantize_money(order_shipping * Decimal(total_qty_in_shipment) / Decimal(total_order_qty))

        # Per-shipment shipping per unit used for landed cost per item
        per_shipment_spu = _quantize_money(est_ship_cost / Decimal(total_qty_in_shipment)) if total_qty_in_shipment > 0 and est_ship_cost > 0 else Decimal('0')

        # Landed cost = unit price + this shipment's shipping per unit (not the order average)
        for row in rows:
            row['landed_cost'] = _quantize_money(row['price'] + per_shipment_spu)

        # Rate per CBM/KG derived from actual per-shipment cost
        rate_per_cbm = None
        rate_per_kg = None
        if est_ship_cost > 0:
            if uses_cbm and shipment_cbm > 0:
                rate_per_cbm = _quantize_money(est_ship_cost / shipment_cbm)
            elif (uses_air or shipment_method == 'manual') and chargeable_weight > 0:
                rate_per_kg = _quantize_money(est_ship_cost / chargeable_weight)
        elif rate > 0:
            if uses_cbm:
                rate_per_cbm = rate
            elif uses_air:
                rate_per_kg = rate
        # Fallback to order-level effective rates if per-shipment rates couldn't be calculated
        if rate_per_cbm is None and uses_cbm and effective_rate_cbm and shipment_cbm > 0:
            rate_per_cbm = effective_rate_cbm
        if rate_per_kg is None and uses_air and effective_rate_weight and chargeable_weight > 0:
            rate_per_kg = effective_rate_weight

        invoice_shipments.append({
            'shipment_no': sno,
            'shipment_name': items_in_shipment[0].shipment_name if items_in_shipment else '',
            'shipment_company': items_in_shipment[0].shipment_company if items_in_shipment else None,
            'shipment_method': shipment_method,
            'cargo_type': cargo_type,
            'items': rows,
            'weight': _quantize_metric(shipment_weight),
            'volumetric_weight': _quantize_metric(shipment_volumetric_weight) if (uses_air or stored_vol_weight > 0) else None,
            'chargeable_weight': _quantize_metric(chargeable_weight) if uses_air else None,
            'cbm': shipment_cbm,
            'total_qty': total_qty_in_shipment,
            'shipping_per_unit': per_shipment_spu,
            'est_shipping_cost': est_ship_cost,
            'rate_per_cbm': rate_per_cbm,
            'rate_per_kg': rate_per_kg,
        })

    # Invoice-level shipping total is the sum of the per-shipment costs that are
    # actually displayed in the invoice. This ensures the Grand Total always
    # matches the shipping line-items the customer sees (even when order-level
    # shipping_cost is 0 but rates auto-calculate a per-shipment cost).
    # The Decimal('0') start value is required, not cosmetic: a bare sum() over an
    # empty sequence returns the int 0, and _quantize_money() then blows up with
    # "'int' object has no attribute 'quantize'". invoice_shipments is empty for any
    # order with no line items — a draft created from the portal before products are
    # added, for instance — so both /orders/invoice/<id>/ and /orders/export/<id>/
    # returned a 500 for those. khata/views.py already uses this idiom.
    invoice_shipping_total = _quantize_money(
        sum((s['est_shipping_cost'] for s in invoice_shipments), Decimal('0'))
    )
    other_cost = Decimal(str(order.other_cost)) if order.other_cost else Decimal('0')
    grand_total = _quantize_money(order.total + invoice_shipping_total + other_cost)
    grand_total_with_commission = _quantize_money(grand_total + Decimal(str(order.commission_amount)))
    effective_rate_cbm = _quantize_money(invoice_shipping_total / total_cbm) if total_cbm > 0 and invoice_shipping_total > 0 else None
    effective_rate_weight = _quantize_money(invoice_shipping_total / total_weight) if total_weight > 0 and invoice_shipping_total > 0 else None
    shipping_per_unit_order = _quantize_money(invoice_shipping_total / Decimal(total_order_qty)) if total_order_qty > 0 and invoice_shipping_total > 0 else Decimal('0')

    # Exchange rate conversion (dual-currency display)
    fx_enabled = settings.exchange_rate_enabled and settings.exchange_rate and settings.exchange_rate > 0
    fx_rate = Decimal(str(settings.exchange_rate)) if fx_enabled else Decimal('0')
    fx_from = settings.exchange_rate_from if fx_enabled else ''
    fx_to = settings.exchange_rate_to if fx_enabled else ''
    if fx_enabled:
        for shipment_dict in invoice_shipments:
            for row in shipment_dict['items']:
                row['price_converted'] = _quantize_money(row['price'] / fx_rate)
                row['subtotal_converted'] = _quantize_money(row['subtotal'] / fx_rate)
                row['landed_cost_converted'] = _quantize_money(row['landed_cost'] / fx_rate)
            if shipment_dict['est_shipping_cost']:
                shipment_dict['est_shipping_cost_converted'] = _quantize_money(shipment_dict['est_shipping_cost'] / fx_rate)
            else:
                shipment_dict['est_shipping_cost_converted'] = None
        grand_total_converted = _quantize_money(grand_total / fx_rate)
        grand_total_with_commission_converted = _quantize_money(grand_total_with_commission / fx_rate)
        commission_amount_converted = _quantize_money(Decimal(str(order.commission_amount)) / fx_rate) if order.commission_amount and str(order.commission_amount) != '0.00' else None
    else:
        for shipment_dict in invoice_shipments:
            shipment_dict['est_shipping_cost_converted'] = None
        grand_total_converted = None
        grand_total_with_commission_converted = None
        commission_amount_converted = None

    return {
        'order': order,
        'settings': settings,
        'shipping_companies': order.shipping_companies.all(),
        'extra_costs': order.extra_costs.all(),
        'grand_total': grand_total,
        'grand_total_with_commission': grand_total_with_commission,
        'invoice_items': invoice_items,
        'invoice_shipments': invoice_shipments,
        'multi_shipment': len(invoice_shipments) > 1,
        'effective_rate_cbm': effective_rate_cbm,
        'effective_rate_weight': effective_rate_weight,
        'shipping_per_unit': shipping_per_unit_order,
        'shipping_total': invoice_shipping_total,
        'fx_enabled': fx_enabled,
        'fx_rate': fx_rate,
        'fx_from': fx_from,
        'fx_to': fx_to,
        'grand_total_converted': grand_total_converted,
        'grand_total_with_commission_converted': grand_total_with_commission_converted,
        'commission_amount_converted': commission_amount_converted,
    }


@module_required('orders')
def order_invoice(request, order_id):
    """
    Render the invoice HTML page for an order.

    Args:
        request (HttpRequest): The incoming HTTP request.
        order_id (int): The primary key of the order to invoice.

    Returns:
        HttpResponse: A rendered HTML invoice page, or a 404 JSON error.

    Business Logic:
        This is the primary invoice view. It shows the complete financial breakdown
        with all shipments, line items, shipping costs, extra costs, commission, and
        grand total. If exchange rate is enabled, prices are shown in both currencies.

    Django Concepts:
        - Order.objects.select_related('customer').prefetch_related(...): Optimized query.
        - _compute_invoice_data(): The shared logic function that calculates all invoice data.
        - render(): Combines the invoice template with the computed context.
    """
    try:
        order = Order.objects.select_related('customer').prefetch_related('items__product__images', 'shipping_companies').get(id=order_id)
        # Allocate the invoice reference on first view. Doing it here rather than
        # at order creation means draft orders that are never invoiced do not
        # consume numbers and leave gaps in the sequence. Once assigned it is
        # frozen on the order, so re-opening this page never changes it.
        order.ensure_invoice_number()
        context = _compute_invoice_data(order)
        return render(request, 'orders/invoice.html', context)
    except Order.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)


@module_required('orders')
def delete_order(request, order_id):
    """
    AJAX endpoint: Delete an order from the system.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        order_id (int): The primary key of the order to delete.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        If an order was created by mistake or the customer cancels, the admin deletes it.
        This also removes all associated OrderItems and OrderExtraCosts (cascade delete).
    """
    if request.method == 'POST':
        try:
            order = Order.objects.get(id=order_id)
            order.delete()
            return JsonResponse({'success': True, 'message': 'Order deleted!'})
        except Order.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Order not found'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('orders')
def duplicate_order(request, order_id):
    """
    AJAX endpoint: Duplicate an existing order as a new draft.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        order_id (int): The primary key of the order to duplicate.

    Returns:
        JsonResponse: {'success': True, 'message': '...', 'id': new_order_id}

    Business Logic:
        When a customer wants to reorder the same products, or the admin wants to create
        a similar order, they duplicate the existing order. The new order starts as a DRAFT
        with all items, shipping settings, and costs copied. The admin can then modify it
        before confirming. This saves time compared to creating an order from scratch.

    Django Concepts:
        - Order.objects.create(): Creates a new order with copied fields.
        - OrderItem.objects.create(): Recreates each item for the new order.
        - new_order.shipping_companies.set(): Copies the Many-to-Many relationship.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})
    try:
        order = Order.objects.prefetch_related('items__product', 'shipping_companies', 'extra_costs').get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found'}, status=404)
    # Create a new order as a DRAFT with all fields copied from the original
    new_order = Order.objects.create(
        customer=order.customer,
        total=order.total,
        commission_amount=order.commission_amount,
        commission_percentage=order.commission_percentage,
        cargo_type=order.cargo_type,
        shipping_method=order.shipping_method,
        shipping_rate=order.shipping_rate,
        shipping_cost=order.shipping_cost,
        other_cost=order.other_cost,
        other_cost_reason=order.other_cost_reason,
        total_weight=order.total_weight,
        total_cbm=order.total_cbm,
        status=Order.STATUS_DRAFT,  # Always start as draft
        payment_status='unpaid',     # Reset payment status
        is_placed=False,             # Not yet placed with supplier
        notes=order.notes,
    )
    # Copy all order items
    for item in order.items.all():
        OrderItem.objects.create(
            order=new_order,
            product=item.product,
            quantity=item.quantity,
            price=item.price,
            shipment_no=item.shipment_no,
            shipment_name=item.shipment_name,
            shipment_company=item.shipment_company,
            shipment_method=item.shipment_method,
            cargo_type=item.cargo_type,
            shipment_cbm=item.shipment_cbm,
            shipment_weight=item.shipment_weight,
            shipment_volumetric_weight=item.shipment_volumetric_weight,
            shipment_shipping_cost=item.shipment_shipping_cost,
            is_checked=item.is_checked,
            label_mark=item.label_mark,
            carton_mark=item.carton_mark,
            carton_asn=item.carton_asn,
            carton_quantity=item.carton_quantity,
            shipping_label=item.shipping_label,
            carton_label=item.carton_label,
        )
    # Copy extra costs
    for ec in order.extra_costs.all():
        OrderExtraCost.objects.create(order=new_order, amount=ec.amount, reason=ec.reason)
    # Copy shipping companies (Many-to-Many relationship)
    new_order.shipping_companies.set(order.shipping_companies.all())
    return JsonResponse({'success': True, 'message': f'Order #{order_id} duplicated as Draft #{new_order.id}', 'id': new_order.id})


@module_required('orders')
def toggle_payment_status(request, order_id):
    """
    AJAX endpoint: Update or cycle the payment status of an order.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        order_id (int): The primary key of the order to update.

    Returns:
        JsonResponse: {'success': True, 'payment_status': 'unpaid'|'partial'|'paid'}

    Business Logic:
        The admin tracks whether the customer has paid. If a specific status is provided
        in the POST data, it sets that status. Otherwise, it cycles through: unpaid -> partial -> paid -> unpaid.
        This is useful for quick toggling without a dropdown menu.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found'}, status=404)
    valid = {'unpaid', 'partial', 'paid'}
    new_status = request.POST.get('status', '').strip()
    if new_status in valid:
        order.payment_status = new_status
    else:
        # Cycle through the three states if no specific status is provided
        cycle = {'unpaid': 'partial', 'partial': 'paid', 'paid': 'unpaid'}
        order.payment_status = cycle.get(order.payment_status, 'unpaid')
    order.save(update_fields=['payment_status'])
    return JsonResponse({'success': True, 'payment_status': order.payment_status})


@module_required('orders')
def toggle_placed(request, order_id):
    """
    AJAX endpoint: Toggle whether an order has been placed with the supplier.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        order_id (int): The primary key of the order to update.

    Returns:
        JsonResponse: {'success': True, 'is_placed': True/False}

    Business Logic:
        "Placed" means the admin has sent the order to the supplier for fulfillment.
        This is a binary flag that helps track which orders have been actioned vs
        which are still pending admin action. It can be toggled directly or set explicitly.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found'}, status=404)
    new_status = request.POST.get('is_placed', '').strip()
    if new_status == 'true':
        order.is_placed = True
    elif new_status == 'false':
        order.is_placed = False
    else:
        # Toggle the current state if no explicit value is provided
        order.is_placed = not order.is_placed
    order.save(update_fields=['is_placed'])

    if order.is_placed:
        _notify_customer_order_status(
            order,
            subject=f'Order #{order.id} Placed with Supplier — {CompanySettings.get_settings().company_name}',
            headline=f'Your order #{order.id} has been placed with the supplier for fulfillment.',
        )

    return JsonResponse({'success': True, 'is_placed': order.is_placed})


@module_required('orders')
def download_order_labels_zip(request, order_id):
    """
    Download a ZIP archive containing all shipping and carton labels uploaded
    for ready-to-ship marketplace items in an order.

    Args:
        request (HttpRequest): The incoming request.
        order_id (int): The order primary key.

    Returns:
        HttpResponse: A FileResponse with the ZIP archive, or a 404/403 response.
    """
    order = get_object_or_404(Order, id=order_id)
    items = order.items.select_related('product').filter(
        product__ready_to_ship=True,
        product__source__in=['amazon', 'noon'],
    )

    files_to_zip = []
    for item in items:
        if item.shipping_label:
            files_to_zip.append((
                f'order_{order.id}/item_{item.id}_{item.product.name[:40]}_shipping_label{item.shipping_label.name[-4:] if "." in item.shipping_label.name else ""}',
                item.shipping_label.path,
            ))
        if item.carton_label:
            ext = item.carton_label.name[-4:] if '.' in item.carton_label.name else ''
            files_to_zip.append((
                f'order_{order.id}/item_{item.id}_{item.product.name[:40]}_carton_label{ext}',
                item.carton_label.path,
            ))

    if not files_to_zip:
        # Was a 200 carrying 'No labels available for this order.' as
        # text/plain. The browser has been told to expect a download, so a bare
        # string under a success status either opens a blank-looking tab or
        # saves a stray text file - and nothing distinguishes it from an export
        # that broke. The operator belongs back on the order, told why.
        # Back to the orders list, NOT order_detail: that route is a JSON API
        # for the page's own fetch() calls, so redirecting a browser there
        # would land the operator on raw JSON.
        messages.warning(request, f'Order #{order.id}: no labels have been uploaded yet.')
        return redirect('order_list')

    zip_buffer = BytesIO()
    written = 0
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for arcname, fpath in files_to_zip:
            if os.path.exists(fpath):
                zf.write(fpath, arcname)
                written += 1

    if not written:
        # Labels are recorded against the items but no file is on disk - a
        # restore that skipped MEDIA_ROOT, or storage cleared by hand. This used
        # to send the empty archive it had just built, which looks exactly like
        # a working export containing nothing: the hardest kind of failure for
        # someone to report, and the easiest to miss until a shipment is late.
        messages.error(
            request,
            f'{len(files_to_zip)} label file(s) are recorded for this order but '
            'are missing from storage, so there is nothing to download.')
        return redirect('order_list')

    zip_buffer.seek(0)
    response = FileResponse(zip_buffer, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="order_{order.id}_labels.zip"'
    return response


@module_required('orders')
def generate_quotation_excel(request):
    """
    Generate a customer quotation Excel file from selected products.

    Args:
        request (HttpRequest): The incoming POST request with customer_id and product_ids.

    Returns:
        HttpResponse: A downloadable Excel quotation file.

    Business Logic:
        The admin selects a customer and multiple products, then generates a quotation Excel.
        The customer fills in the "Quantity" column and returns the file. The file can then be
        imported back via import_quotation_excel to create a draft order.

    Django Concepts:
        - request.POST.getlist('product_ids'): Gets multiple selected product IDs.
        - Product.objects.filter(id__in=product_ids): Fetches all selected products in one query.
        - PIL (Pillow): Resizes images before embedding them in the Excel file.
    """
    if request.method != 'POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])

    from django.http import HttpResponse
    from io import BytesIO
    from datetime import date as today_date
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    customer_id = request.POST.get('customer_id', '').strip()
    product_ids  = request.POST.getlist('product_ids')

    customer = None
    if customer_id:
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            pass

    # Fetch selected products (only published, not drafts), with images, ordered by name
    products_qs = Product.objects.filter(
        id__in=product_ids, is_draft=False
    ).prefetch_related('images').order_by('name')

    settings = CompanySettings.get_settings()

    import os
    from django.conf import settings as djsettings
    from openpyxl.drawing.image import Image as XlImage
    from PIL import Image as PilImage

    # --- Workbook setup ---
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Quotation'

    DARK_BLUE   = '1B3A5C'
    STRIPE      = 'EAF1FB'
    QTY_YELLOW  = 'FFFDE7'
    IMG_SIZE    = 56  # px

    def solid(hex_color):
        return PatternFill('solid', fgColor=hex_color)

    thin_side   = Side(style='thin', color='BBBBBB')
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    left   = Alignment(horizontal='left',   vertical='center', wrap_text=True)

    # Column layout: # | Photo | Product Name | Unit Price | MOQ | Quantity | Line Total | Notes | Product ID
    COLUMNS    = ['#', 'Photo', 'Product Name', f'Unit Price ({settings.currency})', 'MOQ', 'Quantity', f'Line Total ({settings.currency})', 'Notes', 'Product ID']
    COL_WIDTHS = [5, 10, 36, 20, 10, 14, 18, 28, 12]
    NUM_COLS   = len(COLUMNS)
    last_col   = get_column_letter(NUM_COLS)

    cur_row = 1

    # Row 1 – Company name
    ws.merge_cells(f'A{cur_row}:{last_col}{cur_row}')
    c = ws.cell(cur_row, 1, settings.company_name)
    c.font = Font(bold=True, size=16, color=DARK_BLUE)
    c.alignment = center
    ws.row_dimensions[cur_row].height = 32
    cur_row += 1

    # Row 2 – Date
    ws.cell(cur_row, 1, 'Date:').font = Font(bold=True, size=10)
    ws.cell(cur_row, 2, today_date.today().strftime('%B %d, %Y'))
    ws.row_dimensions[cur_row].height = 18
    cur_row += 1

    # Row 3 – Customer (optional)
    if customer:
        ws.cell(cur_row, 1, 'Customer:').font = Font(bold=True, size=10)
        ws.cell(cur_row, 2, customer.name)
        ws.row_dimensions[cur_row].height = 18
        cur_row += 1

    cur_row += 1  # blank spacer

    # Header row
    header_row = cur_row
    for col_idx, (title, width) in enumerate(zip(COLUMNS, COL_WIDTHS), 1):
        c = ws.cell(cur_row, col_idx, title)
        c.font = Font(bold=True, color='FFFFFF', size=11)
        c.fill = solid(DARK_BLUE)
        c.alignment = center
        c.border = cell_border
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    # Product ID header – subtle gray to indicate it's metadata
    pid_header = ws.cell(header_row, NUM_COLS)
    pid_header.font = Font(bold=True, color='AAAAAA', size=9)
    pid_header.fill = solid('2C2C2C')
    ws.row_dimensions[cur_row].height = 22
    cur_row += 1

    data_first_row = cur_row  # Track for the SUM formula at the bottom

    # Data rows – one per product
    for i, product in enumerate(products_qs, 1):
        row_fill = solid(STRIPE) if i % 2 == 0 else None
        # Column values: #, (image placeholder), name, price, moq, qty, (formula), notes, product_id
        row_data = [i, '', product.name, float(product.price), product.moq, '', None, '', product.id]
        for col_idx, value in enumerate(row_data, 1):
            if col_idx == 7:  # Line Total – auto formula (Price × Quantity)
                c = ws.cell(cur_row, col_idx, f'=D{cur_row}*F{cur_row}')
                c.number_format = '#,##0.00'
                c.font = Font(size=10, bold=True)
                c.fill = solid('E6F4EA')  # Light green background
                c.border = cell_border
                c.alignment = center
                continue
            c = ws.cell(cur_row, col_idx, value)
            c.border = cell_border
            c.alignment = left if col_idx == 3 else center
            if col_idx == 6:       # Quantity column – yellow highlight (editable by customer)
                c.font = Font(size=10)
                c.fill = solid(QTY_YELLOW)
            elif col_idx == 9:     # Product ID – metadata column
                c.font = Font(size=9, color='AAAAAA')
                c.fill = solid('F0F0F0')
            else:
                c.font = Font(size=10)
                if col_idx != 2 and row_fill:
                    c.fill = row_fill

        # Embed product image in column B using PIL to resize first
        has_image = False
        first_img = product.primary_image
        if first_img:
            try:
                img_path = os.path.join(str(djsettings.MEDIA_ROOT), str(first_img.image))
                pil_img = PilImage.open(img_path).convert('RGB')
                pil_img.thumbnail((IMG_SIZE, IMG_SIZE), PilImage.LANCZOS)
                img_buf = BytesIO()
                pil_img.save(img_buf, format='PNG')
                img_buf.seek(0)
                xl_img = XlImage(img_buf)
                xl_img.width  = IMG_SIZE
                xl_img.height = IMG_SIZE
                ws.add_image(xl_img, f'B{cur_row}')
                has_image = True
            except Exception:
                pass  # Missing or corrupt image – skip gracefully

        ws.row_dimensions[cur_row].height = int(IMG_SIZE * 0.75) if has_image else 20
        cur_row += 1

    data_last_row = cur_row - 1

    # Freeze panes below header so header stays visible when scrolling
    ws.freeze_panes = ws.cell(header_row + 1, 1)

    # Totals row
    cur_row += 1
    ws.merge_cells(f'A{cur_row}:F{cur_row}')
    lbl = ws.cell(cur_row, 1, 'TOTAL')
    lbl.font = Font(bold=True, size=12, color='FFFFFF')
    lbl.fill = solid(DARK_BLUE)
    lbl.alignment = center
    lbl.border = cell_border

    tot = ws.cell(cur_row, 7, f'=SUM(G{data_first_row}:G{data_last_row})')
    tot.font = Font(bold=True, size=12, color='FFFFFF')
    tot.fill = solid(DARK_BLUE)
    tot.alignment = center
    tot.border = cell_border
    tot.number_format = '#,##0.00'

    for col_idx in range(8, NUM_COLS + 1):
        c = ws.cell(cur_row, col_idx)
        c.fill = solid(DARK_BLUE)
        c.border = cell_border
    ws.row_dimensions[cur_row].height = 24
    cur_row += 1

    # Footer note
    cur_row += 1
    ws.merge_cells(f'A{cur_row}:{last_col}{cur_row}')
    note = ws.cell(cur_row, 1, '* Fill in the "Quantity" column (yellow) and import this file back using the Import button.')
    note.font = Font(italic=True, size=9, color='888888')
    note.alignment = left

    # --- Stream response ---
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"quotation_{today_date.today().strftime('%Y%m%d')}.xlsx"
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


def _normalize_header(value):
    """
    Normalize a header cell value for matching during Excel parsing.

    Args:
        value: Any cell value (could be None, str, int, etc.).

    Returns:
        str: Normalized header string (lowercase, single spaces, no newlines).

    Business Logic:
        When parsing customer-filled Excel files, headers might have extra spaces,
        different cases, or newline characters. This function normalizes them so
        we can reliably match 'Order Qty', 'Order Qty (fill in)', and 'order qty'.
    """
    if value is None:
        return ''
    text = str(value).strip().lower().replace('\n', ' ')
    return ' '.join(text.split())


def _parse_quotation_workbook(ws):
    """
    Parse an order or customer quotation workbook to extract product quantities.

    Args:
        ws (openpyxl.Worksheet): The worksheet to parse.

    Returns:
        list[dict]: Each dict contains 'product_id', 'product_name', and 'quantity'.

    Business Logic:
        The customer fills in quantities in the quotation Excel and returns it.
        This function scans the worksheet to find the header row, then extracts
        all rows with non-zero quantities. It handles both 'Quantity' and 'Order Qty' headers.
    """
    qty_col = None
    name_col = None
    id_col = None
    header_row_idx = None

    for row_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
        if not row:
            continue
        col_by_header = {}
        for col_idx, cell in enumerate(row):
            key = _normalize_header(cell)
            if key:
                col_by_header[key] = col_idx
                col_by_header[key.split('(')[0].strip()] = col_idx  # Also match without parenthetical text

        row_qty_col = None
        row_name_col = col_by_header.get('product name')
        row_id_col = col_by_header.get('product id')

        for key, idx in col_by_header.items():
            if key == 'quantity' or key.startswith('order qty'):
                row_qty_col = idx

        # A valid header row must have a quantity column AND either a name or product ID column
        if row_qty_col is not None and (row_name_col is not None or row_id_col is not None):
            header_row_idx = row_idx
            qty_col = row_qty_col
            name_col = row_name_col
            id_col = row_id_col
            break

    if header_row_idx is None:
        return []

    parsed_items = []
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        row = list(row) if row else []
        max_needed = max([qty_col] + ([name_col] if name_col is not None else []) + ([id_col] if id_col is not None else []))
        if len(row) <= max_needed:
            continue

        name = ''
        if name_col is not None and row[name_col] is not None:
            name = str(row[name_col]).strip()
        if name.upper() in ('TOTAL', 'TOTALS'):
            break  # Stop at the totals row
        if not name and id_col is None:
            continue  # Skip rows with no name and no ID

        qty_raw = row[qty_col]
        if qty_raw in (None, ''):
            continue  # Skip rows with no quantity
        try:
            quantity = int(float(qty_raw))
        except (TypeError, ValueError):
            continue  # Skip rows with invalid quantity
        if quantity <= 0:
            continue  # Skip zero or negative quantities

        product_id = None
        if id_col is not None and row[id_col] not in (None, ''):
            try:
                product_id = int(float(row[id_col]))
            except (TypeError, ValueError):
                product_id = None

        parsed_items.append({
            'product_id': product_id,
            'product_name': name,
            'quantity': quantity,
        })

    return parsed_items


def _resolve_quotation_items(parsed_items):
    """
    Turn parsed sheet rows into (Product, quantity) pairs by resolving product IDs and names.

    Args:
        parsed_items (list[dict]): The items parsed from the Excel workbook.

    Returns:
        tuple: (valid_items, unmatched) where valid_items is a list of (Product, quantity)
               tuples and unmatched is a list of product names that couldn't be resolved.

    Business Logic:
        After parsing the Excel, we need to match each row to an actual Product in the database.
        We try two methods:
        1. Product ID (most reliable – the ID was embedded in the quotation)
        2. Product name (fallback – if the customer deleted the ID column or the ID changed)
        Any rows that can't be matched are returned as 'unmatched' for the admin to review.
    """
    product_ids = [item['product_id'] for item in parsed_items if item['product_id']]
    products_by_id = {
        p.id: p for p in Product.objects.filter(id__in=product_ids, is_draft=False)
    }

    products_by_name = {}
    names_needed = {
        ' '.join(item['product_name'].strip().lower().split())
        for item in parsed_items
        if not item['product_id'] and item['product_name']
    }
    if names_needed:
        for product in Product.objects.filter(is_draft=False):
            key = ' '.join(product.name.strip().lower().split())
            if key in names_needed and key not in products_by_name:
                products_by_name[key] = product

    valid_items = []
    unmatched = []
    for item in parsed_items:
        product = None
        if item['product_id']:
            product = products_by_id.get(item['product_id'])
            if not product:
                unmatched.append(item['product_name'] or f'ID {item["product_id"]}')
        elif item['product_name']:
            key = ' '.join(item['product_name'].strip().lower().split())
            product = products_by_name.get(key)
            if not product:
                unmatched.append(item['product_name'])

        if product:
            valid_items.append((product, item['quantity']))

    return valid_items, unmatched


@module_required('orders')
def import_quotation_excel(request):
    """
    AJAX endpoint: Import a customer-filled quotation Excel and create a draft order.

    Args:
        request (HttpRequest): The incoming POST request with customer_id and excel_file.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...', 'order_id': ...}

    Business Logic:
        The customer receives a quotation Excel, fills in quantities, and returns it.
        The admin uploads the file here. The system:
        1. Parses the Excel to find product names/IDs and quantities
        2. Resolves each row to a Product in the database
        3. Creates a new DRAFT order with the customer and products
        4. Calculates commission and total
        This automates order creation from customer responses, saving hours of manual entry.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})

    customer_id = request.POST.get('customer_id', '').strip()
    excel_file  = request.FILES.get('excel_file')

    if not customer_id:
        return JsonResponse({'success': False, 'message': 'Please select a customer.'})
    if not excel_file:
        return JsonResponse({'success': False, 'message': 'Please upload an Excel file.'})

    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Customer not found.'}, status=404)

    try:
        import openpyxl
        wb = openpyxl.load_workbook(excel_file, data_only=True)
        ws = wb.active
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid or unreadable Excel file.'})

    parsed_items = _parse_quotation_workbook(ws)
    if not parsed_items:
        return JsonResponse({
            'success': False,
            'message': 'No items with quantity found. Fill in the Quantity / Order Qty column and try again.',
        })

    valid_items, unmatched = _resolve_quotation_items(parsed_items)
    if not valid_items:
        sample = ', '.join(unmatched[:3])
        extra = f' Unmatched: {sample}' if sample else ''
        return JsonResponse({'success': False, 'message': f'No valid products matched in the file.{extra}'})

    settings = CompanySettings.get_settings()

    # Create a new draft order for this customer
    order = Order.objects.create(
        customer=customer,
        status=Order.STATUS_DRAFT,
        payment_status='unpaid',
        shipping_method='manual',
        commission_percentage=settings.commission_percentage,
    )

    total = Decimal('0')
    for product, quantity in valid_items:
        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=quantity,
            price=product.price,
            shipment_no=1,
        )
        total += product.price * quantity

    commission_pct = order.commission_percentage / Decimal('100')
    commission_amount = _quantize_money(total * commission_pct)
    order.total = _quantize_money(total)
    order.commission_amount = commission_amount
    order.save(update_fields=['total', 'commission_amount'])

    msg = f'Draft Order #{order.id} created with {len(valid_items)} item(s) for {customer.name}.'
    if unmatched:
        msg += f' ({len(unmatched)} product(s) could not be matched and were skipped.)'

    return JsonResponse({
        'success': True,
        'message': msg,
        'order_id': order.id,
    })


@module_required('orders')
def packing_list_view(request):
    """
    Manager page — filterable list of orders for generating packing lists.

    Args:
        request (HttpRequest): The incoming GET request with optional filters.

    Returns:
        HttpResponse: A rendered HTML page with filtered orders.

    Business Logic:
        Before shipping, the warehouse needs a packing list. This page lets the admin
        filter orders by customer and shipping method (air/sea) to find which orders
        need to be packed. It's the first step in the fulfillment workflow.

    Django Concepts:
        - request.GET.get('customer'): Extracts query parameters from the URL (filter values).
        - orders.filter(customer_id=int(selected_customer)): Filters the QuerySet by customer.
        - orders.filter(shipping_method__in=['air', 'ksa_air']): Filters by multiple methods.
    """
    orders = Order.objects.select_related('customer').prefetch_related('items').order_by('-date')
    customers = Customer.objects.all().order_by('name')

    selected_customer = request.GET.get('customer', '').strip()
    selected_method = request.GET.get('method', '').strip()

    if selected_customer:
        try:
            orders = orders.filter(customer_id=int(selected_customer))
        except ValueError:
            selected_customer = ''

    if selected_method == 'air':
        orders = orders.filter(shipping_method__in=['air', 'ksa_air'])
    elif selected_method == 'sea':
        orders = orders.filter(shipping_method__in=['sea', 'ksa_sea', 'ksa'])
    elif selected_method in {'air', 'sea', 'ksa_air', 'ksa_sea', 'ksa', 'manual'}:
        orders = orders.filter(shipping_method=selected_method)

    return render(request, 'orders/packing_list.html', {
        'orders': orders,
        'customers': customers,
        'selected_customer': selected_customer,
        'selected_method': selected_method,
    })


@module_required('orders')
def packing_list_print(request, order_id):
    """
    Printable packing list for a single order — grouped by shipment.

    Args:
        request (HttpRequest): The incoming HTTP request.
        order_id (int): The primary key of the order to generate the packing list for.

    Returns:
        HttpResponse: A rendered HTML page optimized for printing.

    Business Logic:
        The warehouse prints this page and uses it to physically pack the order.
        It shows:
        - Customer info and shipping method
        - Products grouped by shipment number
        - Carton quantities and carton counts
        - Weight and CBM totals per shipment
        - Grand totals for the entire order

    Django Concepts:
        - Order.objects.select_related('customer').prefetch_related('items__product__images'):
          Fetches all necessary data in optimized queries.
        - Ceiling division: -(-qty // carton_qty) calculates the number of cartons needed.
        - Http404: Raised if the order doesn't exist, which Django renders as a 404 page.
    """
    try:
        order = Order.objects.select_related('customer').prefetch_related(
            'items__product__images', 'items__shipment_company'
        ).get(id=order_id)
    except Order.DoesNotExist:
        from django.http import Http404
        raise Http404

    settings = CompanySettings.get_settings()

    # Group items by shipment_no
    shipments_dict = {}
    for item in order.items.all():
        sno = item.shipment_no or 1
        if sno not in shipments_dict:
            shipments_dict[sno] = []
        shipments_dict[sno].append(item)

    shipments = []
    grand_cartons = 0
    grand_qty = 0
    grand_weight = Decimal('0')
    grand_cbm = Decimal('0')

    for sno in sorted(shipments_dict.keys()):
        items_in_shipment = shipments_dict[sno]
        rows = []
        s_cartons = 0
        s_qty = 0
        s_weight_auto = Decimal('0')
        s_cbm_auto = Decimal('0')

        for item in items_in_shipment:
            p = item.product
            qty = item.quantity
            carton_qty = p.carton_qty if p.carton_qty and p.carton_qty > 0 else None
            num_cartons = -(-qty // carton_qty) if carton_qty else None  # Ceiling division for cartons

            # Auto-calculation of weight/CBM from product data is disabled for now.
            first_img = p.images.all()[0] if p.images.all() else None
            image_url = first_img.src if first_img else None

            rows.append({
                'name': p.name,
                'image_url': image_url,
                'carton_qty': carton_qty,
                'num_cartons': num_cartons,
                'quantity': qty,
                'carton_weight': None,
                'weight_per_unit': None,
                'total_weight': None,
                'dims': None,
                'cbm_per_carton': None,
                'total_cbm': None,
            })

        # Use stored override values only (auto-calculation disabled).
        stored_cbm = Decimal(str(items_in_shipment[0].shipment_cbm)) if items_in_shipment[0].shipment_cbm else Decimal('0')
        stored_weight = Decimal(str(items_in_shipment[0].shipment_weight)) if items_in_shipment[0].shipment_weight else Decimal('0')
        s_cbm_final = stored_cbm
        s_weight_final = stored_weight

        grand_cartons += s_cartons
        grand_qty += s_qty
        grand_weight += s_weight_final
        grand_cbm += s_cbm_final

        shipments.append({
            'shipment_no': sno,
            'shipment_name': items_in_shipment[0].shipment_name,
            'shipment_company': items_in_shipment[0].shipment_company,
            'rows': rows,
            'total_cartons': s_cartons,
            'total_qty': s_qty,
            'total_weight': _quantize_metric(s_weight_final),
            'total_cbm': _quantize_metric(s_cbm_final),
        })

    # Human-readable shipping method label for the packing list
    method_label = {
        'air': 'Air Freight', 'sea': 'Sea Freight',
        'ksa_air': 'KSA Air Freight', 'ksa_sea': 'KSA Sea Freight',
        'ksa': 'KSA Freight', 'manual': 'Manual / Not Set',
    }.get(order.shipping_method or 'manual', order.shipping_method or '—')

    return render(request, 'orders/packing_list_print.html', {
        'order': order,
        'settings': settings,
        'shipments': shipments,
        'multi_shipment': len(shipments) > 1,
        'method_label': method_label,
        'grand_cartons': grand_cartons,
        'grand_qty': grand_qty,
        'grand_weight': _quantize_metric(grand_weight),
        'grand_cbm': _quantize_metric(grand_cbm),
    })


@module_required('orders')
def order_excel_export(request, order_id):
    """
    Export a single order as a styled Excel (.xlsx) invoice.

    Args:
        request (HttpRequest): The incoming HTTP request.
        order_id (int): The primary key of the order to export.

    Returns:
        HttpResponse: A downloadable Excel invoice file.

    Business Logic:
        The admin can export any order as a professional Excel invoice. This is useful for:
        - Sending to customers via email/WhatsApp
        - Accounting records
        - Supplier communication
        The invoice includes all shipments, line items, shipping costs, extra costs, commission, and grand total.
        If dual-currency is enabled, both currencies are shown.

    Django Concepts:
        - Order.objects.select_related('customer').prefetch_related('items__product__images', 'shipping_companies', 'extra_costs'):
          Fetches all related data in optimized queries.
        - _compute_invoice_data(): Reuses the shared invoice calculation logic.
        - openpyxl: Creates a professional Excel file with multiple sections.
    """
    from io import BytesIO
    from django.http import HttpResponse
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    order = Order.objects.select_related('customer').prefetch_related(
        'items__product__images', 'shipping_companies', 'extra_costs'
    ).get(pk=order_id)

    ctx = _compute_invoice_data(order)
    settings = ctx['settings']
    currency = settings.currency or 'RMB'
    fx_enabled = ctx['fx_enabled']
    fx_from = ctx['fx_from']
    fx_to = ctx['fx_to']

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f'Order #{order.id}'

    # Color palette
    DARK = '1B3A5C'
    LIGHT_HEADER = 'EAF1FB'
    STRIPE = 'F7FAFF'

    def solid(hex_color):
        return PatternFill('solid', fgColor=hex_color)

    thin = Side(style='thin', color='CCCCCC')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    left = Alignment(horizontal='left', vertical='center', wrap_text=True)

    def hdr_cell(row, col, text, bold=True, size=10, color='FFFFFF', fill=DARK):
        c = ws.cell(row, col, text)
        c.font = Font(bold=bold, size=size, color=color)
        c.fill = solid(fill)
        c.alignment = center
        c.border = border
        return c

    def data_cell(row, col, value, bold=False, align=center, fill_hex=None, num_format=None):
        c = ws.cell(row, col, value)
        c.font = Font(bold=bold, size=10)
        c.alignment = align
        c.border = border
        if fill_hex:
            c.fill = solid(fill_hex)
        if num_format:
            c.number_format = num_format
        return c

    def _to_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # Column layout
    columns = [
        ('#', 5),
        ('Product Name', 34),
        ('SKU / Barcode', 16),
        ('Weight/PC (KG)', 14),
        ('Total Weight (KG)', 14),
        ('Qty', 8),
        (f'Unit Price ({currency})', 14),
        (f'Subtotal ({currency})', 16),
        (f'Landed Cost/PC ({currency})', 16),
        ('CBM', 12),
    ]
    if fx_enabled:
        columns += [
            (f'Unit Price ({fx_from})', 14),
            (f'Subtotal ({fx_from})', 16),
            (f'Landed Cost/PC ({fx_from})', 16),
        ]
    num_cols = len(columns)
    last_col = get_column_letter(num_cols)
    second_last_col = get_column_letter(num_cols - 1) if num_cols > 1 else 'A'
    for i, (title, width) in enumerate(columns, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    r = 1

    # Company header
    ws.merge_cells(f'A{r}:{last_col}{r}')
    c = ws.cell(r, 1, settings.company_name or 'Invoice')
    c.font = Font(bold=True, size=14, color='FFFFFF')
    c.fill = solid(DARK)
    c.alignment = center
    ws.row_dimensions[r].height = 28
    r += 1

    if settings.company_phone or settings.company_address:
        ws.merge_cells(f'A{r}:{last_col}{r}')
        parts = [p for p in [settings.company_phone, settings.company_address] if p]
        c = ws.cell(r, 1, '  |  '.join(parts))
        c.font = Font(size=9, color='666666')
        c.alignment = center
        ws.row_dimensions[r].height = 16
        r += 1

    r += 1

    # Invoice title
    ws.merge_cells(f'A{r}:{last_col}{r}')
    c = ws.cell(r, 1, 'INVOICE')
    c.font = Font(bold=True, size=13, color=DARK)
    c.alignment = center
    ws.row_dimensions[r].height = 22
    r += 1

    # Human-readable shipping method label
    method_label = {
        'air': 'Air Freight', 'sea': 'Sea Freight',
        'ksa_air': 'KSA Air Freight', 'ksa_sea': 'KSA Sea Freight',
        'ksa': 'KSA Freight', 'manual': 'Manual',
    }.get(order.shipping_method or 'manual', order.shipping_method or '—')
    shipping_companies = ', '.join(c.name for c in ctx['shipping_companies']) or '—'

    # Info rows: order metadata
    info_rows = [
        ('Order #:', f'#{order.id}'),
        ('Date:', order.date.strftime('%B %d, %Y') if order.date else '—'),
        ('Customer:', order.customer.name if order.customer else '—'),
        ('Customer Phone:', (getattr(order.customer, 'phone', '') or '—') if order.customer else '—'),
        ('Customer Address:', (getattr(order.customer, 'address', '') or '—') if order.customer else '—'),
        ('Shipping Method:', method_label),
        ('Shipping Companies:', shipping_companies),
    ]
    for label, value in info_rows:
        ws.merge_cells(f'B{r}:{last_col}{r}')
        ws.cell(r, 1, label).font = Font(bold=True, size=10)
        ws.cell(r, 2, value).font = Font(size=10)
        ws.cell(r, 1).alignment = left
        ws.cell(r, 2).alignment = left
        ws.row_dimensions[r].height = 16
        r += 1

    r += 1

    # Shipments section
    for shipment in ctx['invoice_shipments']:
        s_method_label = {
            'air': 'Air Freight', 'sea': 'Sea Freight',
            'ksa_air': 'KSA Air Freight', 'ksa_sea': 'KSA Sea Freight',
            'ksa': 'KSA Freight', 'manual': 'Manual',
        }.get(shipment['shipment_method'] or 'manual', shipment['shipment_method'] or '—')
        s_company = shipment['shipment_company'].name if shipment['shipment_company'] else '—'
        s_name = shipment['shipment_name'] or f"Shipment {shipment['shipment_no']}"

        header_parts = [
            s_name,
            f"Company: {s_company}",
            f"Method: {s_method_label}",
        ]
        show_weight = (shipment['weight'] or 0) > 0 or (shipment['volumetric_weight'] or 0) > 0
        if show_weight:
            if (shipment['weight'] or 0) > 0:
                header_parts.append(f"Weight: {shipment['weight']} KG")
            if (shipment['volumetric_weight'] or 0) > 0:
                header_parts.append(f"Volumetric: {shipment['volumetric_weight']} KG")
            if (shipment['chargeable_weight'] or 0) > 0:
                header_parts.append(f"Chargeable: {shipment['chargeable_weight']} KG")
        if (shipment['cbm'] or 0) > 0:
            header_parts.append(f"CBM: {shipment['cbm']}")
        ship_cost_text = f"Shipping Cost: {currency} {shipment['est_shipping_cost'] or 0}"
        if fx_enabled and shipment.get('est_shipping_cost_converted') is not None:
            ship_cost_text += f"  /  {fx_to} {shipment['est_shipping_cost_converted']}"
        header_parts.append(ship_cost_text)

        ws.merge_cells(f'A{r}:{last_col}{r}')
        c = ws.cell(r, 1, '  |  '.join(header_parts))
        c.font = Font(bold=True, size=10, color='FFFFFF')
        c.fill = solid(DARK)
        c.alignment = left
        c.border = border
        ws.row_dimensions[r].height = 20
        r += 1

        # Product header row for this shipment
        for col_idx, (title, _width) in enumerate(columns, 1):
            hdr_cell(r, col_idx, title)
        ws.row_dimensions[r].height = 20
        r += 1

        # Product rows for this shipment
        for i, row_data in enumerate(shipment['items'], 1):
            fill = STRIPE if i % 2 == 0 else None
            price = _to_float(row_data['price'])
            subtotal = _to_float(row_data['subtotal'])
            landed = _to_float(row_data.get('landed_cost'))
            weight = _to_float(row_data.get('weight'))
            item_weight = _to_float(row_data.get('item_weight'))
            cbm = _to_float(row_data.get('item_cbm'))
            qty = row_data['quantity']

            values = [
                i,
                row_data['name'],
                row_data.get('sku') or '—',
                weight,
                item_weight,
                qty,
                price,
                subtotal,
                landed,
                cbm,
            ]
            if fx_enabled:
                values += [
                    _to_float(row_data.get('price_converted')),
                    _to_float(row_data.get('subtotal_converted')),
                    _to_float(row_data.get('landed_cost_converted')),
                ]

            checked = row_data.get('is_checked')
            name_fill = 'D1FAE5' if checked else fill  # Green-100 background for checked products
            for col_idx, value in enumerate(values, 1):
                num_format = None
                if col_idx in (4, 5, 10):
                    num_format = '#,##0.000'
                elif col_idx in (7, 8, 9):
                    num_format = '#,##0.00'
                elif fx_enabled and col_idx in (11, 12, 13):
                    num_format = '#,##0.00'
                if col_idx == 2:
                    data_cell(r, col_idx, value, align=left, fill_hex=name_fill, num_format=num_format)
                else:
                    data_cell(r, col_idx, value, fill_hex=fill, num_format=num_format)
            ws.row_dimensions[r].height = 18
            r += 1

        r += 1

    # Totals section
    def total_row(label, value, label_fill=LIGHT_HEADER, label_color=DARK, value_bold=False, converted_value=None):
        nonlocal r
        ws.merge_cells(f'A{r}:{second_last_col}{r}')
        lc = ws.cell(r, 1, label)
        lc.font = Font(bold=True, size=10, color=label_color)
        lc.fill = solid(label_fill)
        lc.alignment = Alignment(horizontal='right', vertical='center')
        lc.border = border
        cell_value = value if value is not None else 0
        vc = ws.cell(r, num_cols, cell_value)
        vc.font = Font(bold=value_bold, size=10)
        vc.fill = solid(label_fill)
        vc.alignment = center
        vc.border = border
        vc.number_format = '#,##0.00'
        ws.row_dimensions[r].height = 18
        r += 1
        if fx_enabled and converted_value is not None:
            ws.merge_cells(f'A{r}:{second_last_col}{r}')
            base_label = label.rsplit(' (', 1)[0] if ' (' in label else label
            lc2 = ws.cell(r, 1, f'{base_label} ({fx_from})')
            lc2.font = Font(bold=True, size=10, color=label_color)
            lc2.fill = solid(label_fill)
            lc2.alignment = Alignment(horizontal='right', vertical='center')
            lc2.border = border
            vc2 = ws.cell(r, num_cols, converted_value)
            vc2.font = Font(size=10)
            vc2.fill = solid(label_fill)
            vc2.alignment = center
            vc2.border = border
            vc2.number_format = '#,##0.00'
            ws.row_dimensions[r].height = 18
            r += 1

    total_row(f'Items Subtotal ({currency})', ctx['order'].total, value_bold=True)
    total_row(f'Shipping Cost ({currency})', ctx['shipping_total'], label_fill=LIGHT_HEADER, label_color=DARK)
    for ec in ctx['extra_costs']:
        total_row(f'Extra: {ec.reason or ""} ({currency})', ec.amount, label_fill=LIGHT_HEADER, label_color=DARK)
    if ctx['order'].commission_amount and ctx['order'].commission_amount > 0:
        pct = f" ({ctx['order'].commission_percentage}%)" if ctx['order'].commission_percentage else ''
        total_row(f'Commission{pct} ({currency})', ctx['order'].commission_amount, label_fill=LIGHT_HEADER, label_color=DARK, converted_value=ctx.get('commission_amount_converted'))
    total_row(f'GRAND TOTAL ({currency})', ctx['grand_total'], value_bold=True, converted_value=ctx.get('grand_total_converted'))
    if ctx['order'].commission_amount and ctx['order'].commission_amount > 0:
        total_row(f'GRAND TOTAL WITH COMMISSION ({currency})', ctx['grand_total_with_commission'], value_bold=True, converted_value=ctx.get('grand_total_with_commission_converted'))

    if ctx['order'].notes:
        r += 1
        ws.merge_cells(f'A{r}:{last_col}{r}')
        nc = ws.cell(r, 1, f'Notes: {ctx["order"].notes}')
        nc.font = Font(italic=True, size=9)
        nc.alignment = left
        ws.row_dimensions[r].height = 18

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f'order_{order.id}_{(order.customer.name if order.customer else "export").replace(" ", "_")}.xlsx'
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@module_required('orders')
def reports(request):
    """
    Display comprehensive business reports with charts and date range filtering.

    Args:
        request (HttpRequest): The incoming GET request with optional
                               start_date and end_date query parameters.

    Returns:
        HttpResponse: A rendered HTML page with chart data and summary statistics.

    Business Logic:
        This is the admin analytics hub. It shows:
        - Revenue trends over time (monthly aggregation)
        - Top products by quantity ordered
        - Top customers by revenue and order count
        - Shipping method distribution
        - Payment status breakdown
        - Order status summary

        The admin can filter by any date range to analyze specific periods
        (e.g., "How did Q2 perform?" or "What were last month's top products?").

    Django Concepts:
        - TruncMonth: Groups DateTimeField values by month in the database.
        - annotate() + aggregate(): Computes per-group sums and counts.
        - request.GET.get(): Safely reads optional query parameters.
        - json.dumps(): Serializes chart data for JavaScript consumption.
    """
    # -------------------------------------------------------------------------
    # DATE RANGE FILTERING
    # -------------------------------------------------------------------------
    # Default to the last 12 months if no dates are provided.
    # This gives the admin a full year view immediately upon loading the page.
    today = date.today()
    default_start = (today.replace(day=1) - timedelta(days=365)).replace(day=1)
    default_end = today

    # Parse start_date from the query string (format: YYYY-MM-DD)
    start_str = request.GET.get('start_date', '').strip()
    end_str = request.GET.get('end_date', '').strip()

    try:
        start_date = date.fromisoformat(start_str) if start_str else default_start
    except ValueError:
        start_date = default_start

    try:
        end_date = date.fromisoformat(end_str) if end_str else default_end
    except ValueError:
        end_date = default_end

    # Ensure start_date is not after end_date (swap if user entered them backwards)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    # Base queryset: all orders within the selected date range
    orders_qs = Order.objects.filter(date__date__gte=start_date, date__date__lte=end_date)
    items_qs = OrderItem.objects.filter(order__date__date__gte=start_date, order__date__date__lte=end_date)

    settings = CompanySettings.get_settings()

    # -------------------------------------------------------------------------
    # SUMMARY STATISTICS
    # -------------------------------------------------------------------------
    # High-level KPIs for the summary card row at the top of the reports page.
    totals = orders_qs.aggregate(
        total_orders=Count('id'),
        total_revenue=Sum('total'),
        total_shipping=Sum('shipping_cost'),
        total_commission=Sum('commission_amount'),
    )

    summary = {
        'total_orders': totals['total_orders'] or 0,
        'total_revenue': float(totals['total_revenue'] or 0),
        'total_shipping': float(totals['total_shipping'] or 0),
        'total_commission': float(totals['total_commission'] or 0),
    }

    # -------------------------------------------------------------------------
    # REVENUE OVER TIME (monthly aggregation)
    # -------------------------------------------------------------------------
    # TruncMonth rounds each order's date down to the first of the month.
    # We then annotate each month group with the sum of order totals.
    # This produces a time series for the line/bar chart.
    monthly_revenue = list(
        orders_qs
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(revenue=Sum('total'), order_count=Count('id'))
        .order_by('month')
    )

    # Build complete month range (fill in missing months with zero)
    revenue_labels = []
    revenue_data = []
    revenue_order_counts = []

    # Generate all months in the range
    current = date(start_date.year, start_date.month, 1)
    while current <= end_date:
        label = current.strftime('%b %Y')
        revenue_labels.append(label)
        # Find matching month in the query results
        match = next(
            (m for m in monthly_revenue if m['month'] and m['month'].year == current.year and m['month'].month == current.month),
            None
        )
        revenue_data.append(float(match['revenue'] or 0) if match else 0)
        revenue_order_counts.append(match['order_count'] if match else 0)
        # Advance to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    # -------------------------------------------------------------------------
    # TOP PRODUCTS
    # -------------------------------------------------------------------------
    # Aggregate OrderItem quantities by product name.
    # Only include products that actually have sales in the date range.
    top_products = list(
        items_qs
        .values(product_name=F('product__name'))
        .annotate(total_qty=Sum('quantity'), total_revenue=Sum(F('price') * F('quantity')))
        .order_by('-total_qty')[:10]
    )
    top_product_names = [p['product_name'] for p in top_products]
    top_product_qtys = [int(p['total_qty'] or 0) for p in top_products]
    top_product_revenues = [float(p['total_revenue'] or 0) for p in top_products]

    # -------------------------------------------------------------------------
    # TOP CUSTOMERS
    # -------------------------------------------------------------------------
    # Aggregate orders by customer: total revenue and number of orders.
    top_customers = list(
        orders_qs
        .values(customer_name=F('customer__name'))
        .annotate(total_revenue=Sum('total'), order_count=Count('id'))
        .order_by('-total_revenue')[:10]
    )
    top_customer_names = [c['customer_name'] for c in top_customers]
    top_customer_revenues = [float(c['total_revenue'] or 0) for c in top_customers]
    top_customer_counts = [c['order_count'] for c in top_customers]

    # -------------------------------------------------------------------------
    # SHIPPING METHOD DISTRIBUTION
    # -------------------------------------------------------------------------
    # Count orders per shipping method for a pie/doughnut chart.
    method_dist = list(
        orders_qs
        .values('shipping_method')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    # Human-readable labels for shipping methods
    method_labels_map = {m[0]: m[1] for m in SHIPPING_METHOD_CHOICES}
    method_labels = [method_labels_map.get(m['shipping_method'], m['shipping_method']) for m in method_dist]
    method_counts = [m['count'] for m in method_dist]

    # -------------------------------------------------------------------------
    # PAYMENT STATUS BREAKDOWN
    # -------------------------------------------------------------------------
    # Count orders by payment status for a secondary chart.
    payment_dist = list(
        orders_qs
        .values('payment_status')
        .annotate(count=Count('id'))
        .order_by('payment_status')
    )
    payment_labels_map = {'unpaid': 'Unpaid', 'partial': 'Partial', 'paid': 'Paid'}
    payment_labels = [payment_labels_map.get(p['payment_status'], p['payment_status']) for p in payment_dist]
    payment_counts = [p['count'] for p in payment_dist]

    # -------------------------------------------------------------------------
    # ORDER STATUS BREAKDOWN
    # -------------------------------------------------------------------------
    status_dist = list(
        orders_qs
        .values('status')
        .annotate(count=Count('id'))
        .order_by('status')
    )
    status_labels_map = {'draft': 'Draft', 'confirmed': 'Confirmed'}
    status_labels = [status_labels_map.get(s['status'], s['status']) for s in status_dist]
    status_counts = [s['count'] for s in status_dist]

    # -------------------------------------------------------------------------
    # CONTEXT BUILDING
    # -------------------------------------------------------------------------
    context = {
        'summary': summary,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'currency': settings.currency or 'RMB',

        # Revenue chart data
        'revenue_labels': json.dumps(revenue_labels),
        'revenue_data': json.dumps(revenue_data),
        'revenue_order_counts': json.dumps(revenue_order_counts),

        # Top products chart data
        'top_product_names': json.dumps(top_product_names),
        'top_product_qtys': json.dumps(top_product_qtys),
        'top_product_revenues': json.dumps(top_product_revenues),

        # Top customers chart data
        'top_customer_names': json.dumps(top_customer_names),
        'top_customer_revenues': json.dumps(top_customer_revenues),
        'top_customer_counts': json.dumps(top_customer_counts),

        # Shipping method distribution
        'method_labels': json.dumps(method_labels),
        'method_counts': json.dumps(method_counts),

        # Payment status distribution
        'payment_labels': json.dumps(payment_labels),
        'payment_counts': json.dumps(payment_counts),

        # Order status distribution
        'status_labels': json.dumps(status_labels),
        'status_counts': json.dumps(status_counts),
    }

    return render(request, 'orders/reports.html', context)


@module_required('orders')
def reports_export_excel(request):
    """
    Export a comprehensive business report to an Excel file for the selected date range.

    Args:
        request (HttpRequest): The incoming GET request with start_date and end_date.

    Returns:
        HttpResponse: A downloadable Excel (.xlsx) file with multiple worksheets.

    Business Logic:
        The admin can export the exact same data shown in the reports page charts
        into a professional Excel workbook. This is useful for:
        - Sharing with accountants or business partners
        - Archiving monthly/quarterly performance
        - Further analysis in Excel or Google Sheets
    """
    from django.http import HttpResponse
    from io import BytesIO
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    # Parse the same date range as the reports view
    today = date.today()
    default_start = (today.replace(day=1) - timedelta(days=365)).replace(day=1)
    start_str = request.GET.get('start_date', '').strip()
    end_str = request.GET.get('end_date', '').strip()
    try:
        start_date = date.fromisoformat(start_str) if start_str else default_start
    except ValueError:
        start_date = default_start
    try:
        end_date = date.fromisoformat(end_str) if end_str else today
    except ValueError:
        end_date = today
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    orders_qs = Order.objects.filter(date__date__gte=start_date, date__date__lte=end_date)
    items_qs = OrderItem.objects.filter(order__date__date__gte=start_date, order__date__date__lte=end_date)
    settings = CompanySettings.get_settings()
    currency = settings.currency or 'RMB'

    DARK = '1B3A5C'
    LIGHT_HEADER = 'EAF1FB'
    STRIPE = 'F7FAFF'

    def solid(hex_color):
        return PatternFill('solid', fgColor=hex_color)

    thin = Side(style='thin', color='CCCCCC')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    left = Alignment(horizontal='left', vertical='center', wrap_text=True)
    right = Alignment(horizontal='right', vertical='center')

    wb = openpyxl.Workbook()

    # -------------------------------------------------------------------------
    # WORKSHEET 1: Summary
    # -------------------------------------------------------------------------
    ws_summary = wb.active
    ws_summary.title = 'Summary'

    totals = orders_qs.aggregate(
        total_orders=Count('id'),
        total_revenue=Sum('total'),
        total_shipping=Sum('shipping_cost'),
        total_commission=Sum('commission_amount'),
    )

    # Header row
    ws_summary.merge_cells('A1:D1')
    c = ws_summary.cell(1, 1, f'Business Report — {start_date} to {end_date}')
    c.font = Font(bold=True, size=14, color='FFFFFF')
    c.fill = solid(DARK)
    c.alignment = center
    ws_summary.row_dimensions[1].height = 28

    summary_data = [
        ('Total Orders', totals['total_orders'] or 0),
        (f'Total Revenue ({currency})', float(totals['total_revenue'] or 0)),
        (f'Total Shipping ({currency})', float(totals['total_shipping'] or 0)),
        (f'Total Commission ({currency})', float(totals['total_commission'] or 0)),
    ]
    r = 3
    for label, value in summary_data:
        ws_summary.cell(r, 1, label).font = Font(bold=True, size=11)
        ws_summary.cell(r, 1).alignment = left
        ws_summary.cell(r, 1).border = border
        ws_summary.cell(r, 2, value).font = Font(size=11)
        ws_summary.cell(r, 2).alignment = right
        ws_summary.cell(r, 2).border = border
        ws_summary.cell(r, 2).number_format = '#,##0.00' if isinstance(value, float) else '#,##0'
        r += 1

    ws_summary.column_dimensions['A'].width = 28
    ws_summary.column_dimensions['B'].width = 22

    # -------------------------------------------------------------------------
    # WORKSHEET 2: Revenue by Month
    # -------------------------------------------------------------------------
    ws_rev = wb.create_sheet('Revenue by Month')
    ws_rev.append(['Month', f'Revenue ({currency})', 'Orders'])
    for col in range(1, 4):
        ws_rev.cell(1, col).font = Font(bold=True, color='FFFFFF')
        ws_rev.cell(1, col).fill = solid(DARK)
        ws_rev.cell(1, col).alignment = center
        ws_rev.cell(1, col).border = border
    ws_rev.column_dimensions['A'].width = 18
    ws_rev.column_dimensions['B'].width = 22
    ws_rev.column_dimensions['C'].width = 14

    monthly = list(
        orders_qs
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(revenue=Sum('total'), order_count=Count('id'))
        .order_by('month')
    )
    for m in monthly:
        label = m['month'].strftime('%b %Y') if m['month'] else '—'
        row = [label, float(m['revenue'] or 0), m['order_count'] or 0]
        ws_rev.append(row)
        for col_idx in range(1, 4):
            ws_rev.cell(ws_rev.max_row, col_idx).border = border
            ws_rev.cell(ws_rev.max_row, col_idx).alignment = center
        ws_rev.cell(ws_rev.max_row, 2).number_format = '#,##0.00'

    # -------------------------------------------------------------------------
    # WORKSHEET 3: Top Products
    # -------------------------------------------------------------------------
    ws_prod = wb.create_sheet('Top Products')
    ws_prod.append(['Product', 'Category', 'Total Qty', f'Revenue ({currency})'])
    for col in range(1, 5):
        ws_prod.cell(1, col).font = Font(bold=True, color='FFFFFF')
        ws_prod.cell(1, col).fill = solid(DARK)
        ws_prod.cell(1, col).alignment = center
        ws_prod.cell(1, col).border = border
    ws_prod.column_dimensions['A'].width = 40
    ws_prod.column_dimensions['B'].width = 24
    ws_prod.column_dimensions['C'].width = 14
    ws_prod.column_dimensions['D'].width = 22

    # A product belongs to exactly one category, so adding it to .values()
    # widens the GROUP BY without regrouping anything: the same rows, now
    # saying what kind of thing sold. Matches the PDF export, which reads from
    # this same query shape.
    top_products = list(
        items_qs
        .values(product_name=F('product__name'),
                category_name=F('product__category__name'))
        .annotate(total_qty=Sum('quantity'), total_revenue=Sum(F('price') * F('quantity')))
        .order_by('-total_qty')[:50]
    )
    for i, p in enumerate(top_products, 1):
        row = [
            p['product_name'],
            p['category_name'] or 'Uncategorised',
            int(p['total_qty'] or 0),
            float(p['total_revenue'] or 0),
        ]
        ws_prod.append(row)
        for col_idx in range(1, 5):
            ws_prod.cell(ws_prod.max_row, col_idx).border = border
            ws_prod.cell(ws_prod.max_row, col_idx).alignment = left if col_idx <= 2 else center
        ws_prod.cell(ws_prod.max_row, 4).number_format = '#,##0.00'

    # -------------------------------------------------------------------------
    # WORKSHEET 4: Revenue by Category
    # -------------------------------------------------------------------------
    # The same line items rolled up one level, and the sheet that makes the
    # workbook say the same thing as the PDF. A report that answers "which part
    # of the catalogue is carrying the quarter" in one format and not the other
    # is the kind of difference that gets noticed in a meeting.
    ws_cat = wb.create_sheet('Revenue by Category')
    ws_cat.append(['Category', 'Units', f'Revenue ({currency})', 'Share'])
    for col in range(1, 5):
        ws_cat.cell(1, col).font = Font(bold=True, color='FFFFFF')
        ws_cat.cell(1, col).fill = solid(DARK)
        ws_cat.cell(1, col).alignment = center
        ws_cat.cell(1, col).border = border
    ws_cat.column_dimensions['A'].width = 32
    ws_cat.column_dimensions['B'].width = 14
    ws_cat.column_dimensions['C'].width = 22
    ws_cat.column_dimensions['D'].width = 12

    by_category = list(
        items_qs
        .values(category_name=F('product__category__name'))
        .annotate(total_qty=Sum('quantity'), total_revenue=Sum(F('price') * F('quantity')))
        .order_by('-total_revenue')
    )
    category_total = sum(float(c['total_revenue'] or 0) for c in by_category)
    for c in by_category:
        revenue = float(c['total_revenue'] or 0)
        # Guarded: a period with orders but nothing charged - samples, or
        # everything at zero - would divide by zero here.
        share = (revenue / category_total) if category_total else 0
        ws_cat.append([
            c['category_name'] or 'Uncategorised',
            int(c['total_qty'] or 0),
            revenue,
            share,
        ])
        for col_idx in range(1, 5):
            ws_cat.cell(ws_cat.max_row, col_idx).border = border
            ws_cat.cell(ws_cat.max_row, col_idx).alignment = left if col_idx == 1 else center
        ws_cat.cell(ws_cat.max_row, 3).number_format = '#,##0.00'
        # A real percentage rather than a string, so the column can be summed
        # and charted in Excel.
        ws_cat.cell(ws_cat.max_row, 4).number_format = '0.0%'

    # -------------------------------------------------------------------------
    # WORKSHEET 5: Top Customers
    # -------------------------------------------------------------------------
    ws_cust = wb.create_sheet('Top Customers')
    ws_cust.append(['Customer', f'Total Revenue ({currency})', 'Orders'])
    for col in range(1, 4):
        ws_cust.cell(1, col).font = Font(bold=True, color='FFFFFF')
        ws_cust.cell(1, col).fill = solid(DARK)
        ws_cust.cell(1, col).alignment = center
        ws_cust.cell(1, col).border = border
    ws_cust.column_dimensions['A'].width = 36
    ws_cust.column_dimensions['B'].width = 22
    ws_cust.column_dimensions['C'].width = 14

    top_customers = list(
        orders_qs
        .values(customer_name=F('customer__name'))
        .annotate(total_revenue=Sum('total'), order_count=Count('id'))
        .order_by('-total_revenue')[:50]
    )
    for c in top_customers:
        row = [c['customer_name'], float(c['total_revenue'] or 0), c['order_count'] or 0]
        ws_cust.append(row)
        for col_idx in range(1, 4):
            ws_cust.cell(ws_cust.max_row, col_idx).border = border
            ws_cust.cell(ws_cust.max_row, col_idx).alignment = center if col_idx > 1 else left
        ws_cust.cell(ws_cust.max_row, 2).number_format = '#,##0.00'

    # -------------------------------------------------------------------------
    # WORKSHEET 6: Shipping Methods
    # -------------------------------------------------------------------------
    ws_ship = wb.create_sheet('Shipping Methods')
    ws_ship.append(['Method', 'Orders'])
    for col in range(1, 3):
        ws_ship.cell(1, col).font = Font(bold=True, color='FFFFFF')
        ws_ship.cell(1, col).fill = solid(DARK)
        ws_ship.cell(1, col).alignment = center
        ws_ship.cell(1, col).border = border
    ws_ship.column_dimensions['A'].width = 24
    ws_ship.column_dimensions['B'].width = 14

    method_labels_map = {m[0]: m[1] for m in SHIPPING_METHOD_CHOICES}
    for m in orders_qs.values('shipping_method').annotate(count=Count('id')).order_by('-count'):
        row = [method_labels_map.get(m['shipping_method'], m['shipping_method']), m['count']]
        ws_ship.append(row)
        for col_idx in range(1, 3):
            ws_ship.cell(ws_ship.max_row, col_idx).border = border
            ws_ship.cell(ws_ship.max_row, col_idx).alignment = center

    # Stream response
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f'report_{start_date}_{end_date}.xlsx'
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


@module_required('orders')
def reports_export_pdf(request):
    """
    Export a comprehensive business report to a PDF file for the selected date range.

    Args:
        request (HttpRequest): The incoming GET request with start_date and end_date.

    Returns:
        HttpResponse: A downloadable PDF file with formatted tables and summary.

    Business Logic:
        PDF reports are ideal for printing, emailing, or presenting to stakeholders.
        This view uses ReportLab to generate a professional document with:
        - Summary statistics
        - Revenue by month table
        - Top products and customers tables
        - Shipping method distribution
    """
    from django.http import HttpResponse
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm

    # Parse date range
    today = date.today()
    default_start = (today.replace(day=1) - timedelta(days=365)).replace(day=1)
    start_str = request.GET.get('start_date', '').strip()
    end_str = request.GET.get('end_date', '').strip()
    try:
        start_date = date.fromisoformat(start_str) if start_str else default_start
    except ValueError:
        start_date = default_start
    try:
        end_date = date.fromisoformat(end_str) if end_str else today
    except ValueError:
        end_date = today
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    orders_qs = Order.objects.filter(date__date__gte=start_date, date__date__lte=end_date)
    items_qs = OrderItem.objects.filter(order__date__date__gte=start_date, order__date__date__lte=end_date)
    settings = CompanySettings.get_settings()
    currency = settings.currency or 'RMB'

    totals = orders_qs.aggregate(
        total_orders=Count('id'),
        total_revenue=Sum('total'),
        total_shipping=Sum('shipping_cost'),
        total_commission=Sum('commission_amount'),
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1B3A5C'),
        spaceAfter=12,
        alignment=1,  # center
    )
    elements.append(Paragraph(f'Business Report — {start_date} to {end_date}', title_style))
    elements.append(Paragraph(f'<b>Company:</b> {settings.company_name or "LogiManager"}', styles['Normal']))
    elements.append(Spacer(1, 0.5*cm))

    # Summary Table
    summary_data = [
        ['Metric', 'Value'],
        ['Total Orders', str(totals['total_orders'] or 0)],
        [f'Total Revenue ({currency})', f'{float(totals["total_revenue"] or 0):,.2f}'],
        [f'Total Shipping ({currency})', f'{float(totals["total_shipping"] or 0):,.2f}'],
        [f'Total Commission ({currency})', f'{float(totals["total_commission"] or 0):,.2f}'],
    ]
    summary_table = Table(summary_data, colWidths=[8*cm, 8*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B3A5C')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F7FAFF')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.8*cm))

    # Revenue by Month
    elements.append(Paragraph('Revenue by Month', styles['Heading2']))
    elements.append(Spacer(1, 0.3*cm))
    monthly = list(
        orders_qs
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(revenue=Sum('total'), order_count=Count('id'))
        .order_by('month')
    )
    rev_data = [['Month', f'Revenue ({currency})', 'Orders']]
    for m in monthly:
        label = m['month'].strftime('%b %Y') if m['month'] else '—'
        rev_data.append([label, f'{float(m["revenue"] or 0):,.2f}', str(m['order_count'] or 0)])
    rev_table = Table(rev_data, colWidths=[6*cm, 6*cm, 4*cm])
    rev_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B3A5C')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F7FAFF')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))
    elements.append(rev_table)
    elements.append(Spacer(1, 0.8*cm))

    # Top Products
    elements.append(Paragraph('Top Products', styles['Heading2']))
    elements.append(Spacer(1, 0.3*cm))
    # Category comes along for the ride. A product belongs to exactly one
    # category, so adding it to .values() widens the GROUP BY without changing
    # how the rows group - the totals are the same, they just say what kind of
    # thing sold.
    top_products = list(
        items_qs
        .values(product_name=F('product__name'),
                category_name=F('product__category__name'))
        .annotate(total_qty=Sum('quantity'), total_revenue=Sum(F('price') * F('quantity')))
        .order_by('-total_qty')[:20]
    )
    prod_data = [['Product', 'Category', 'Qty', f'Revenue ({currency})']]
    for p in top_products:
        prod_data.append([
            p['product_name'][:38],
            (p['category_name'] or 'Uncategorised')[:22],
            str(int(p['total_qty'] or 0)),
            f'{float(p["total_revenue"] or 0):,.2f}',
        ])
    prod_table = Table(prod_data, colWidths=[6.6*cm, 3.6*cm, 2.2*cm, 3.6*cm])
    prod_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B3A5C')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F7FAFF')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
    ]))
    elements.append(prod_table)
    elements.append(Spacer(1, 0.8*cm))

    # Revenue by Category
    #
    # The same line items as Top Products, rolled up one level. Twenty product
    # rows tell you what sold; this tells you which part of the catalogue is
    # carrying the quarter, which is the question a sourcing business actually
    # asks before deciding what to go and buy more of.
    elements.append(Paragraph('Revenue by Category', styles['Heading2']))
    elements.append(Spacer(1, 0.3*cm))
    by_category = list(
        items_qs
        .values(category_name=F('product__category__name'))
        .annotate(total_qty=Sum('quantity'), total_revenue=Sum(F('price') * F('quantity')))
        .order_by('-total_revenue')
    )
    cat_total = sum(float(c['total_revenue'] or 0) for c in by_category)
    cat_data = [['Category', 'Units', f'Revenue ({currency})', 'Share']]
    for c in by_category:
        revenue = float(c['total_revenue'] or 0)
        # Guarded because a period with orders but no revenue - everything
        # given away, or priced at zero - would divide by zero here.
        share = f'{revenue / cat_total * 100:.1f}%' if cat_total else '\u2014'
        cat_data.append([
            (c['category_name'] or 'Uncategorised')[:30],
            str(int(c['total_qty'] or 0)),
            f'{revenue:,.2f}',
            share,
        ])
    if len(cat_data) == 1:
        cat_data.append(['No sales in this period', '\u2014', '\u2014', '\u2014'])
    cat_table = Table(cat_data, colWidths=[7*cm, 2.6*cm, 3.6*cm, 2.8*cm])
    cat_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B3A5C')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F7FAFF')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
    ]))
    elements.append(cat_table)
    elements.append(Spacer(1, 0.8*cm))

    # Top Customers
    elements.append(Paragraph('Top Customers', styles['Heading2']))
    elements.append(Spacer(1, 0.3*cm))
    top_customers = list(
        orders_qs
        .values(customer_name=F('customer__name'))
        .annotate(total_revenue=Sum('total'), order_count=Count('id'))
        .order_by('-total_revenue')[:20]
    )
    cust_data = [['Customer', f'Total Revenue ({currency})', 'Orders']]
    for c in top_customers:
        cust_data.append([
            c['customer_name'][:45],
            f'{float(c["total_revenue"] or 0):,.2f}',
            str(c['order_count'] or 0),
        ])
    cust_table = Table(cust_data, colWidths=[9*cm, 4*cm, 3*cm])
    cust_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B3A5C')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F7FAFF')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
    ]))
    elements.append(cust_table)
    elements.append(Spacer(1, 0.8*cm))

    # Shipping Methods
    elements.append(Paragraph('Shipping Method Distribution', styles['Heading2']))
    elements.append(Spacer(1, 0.3*cm))
    method_labels_map = {m[0]: m[1] for m in SHIPPING_METHOD_CHOICES}
    ship_data = [['Method', 'Orders']]
    for m in orders_qs.values('shipping_method').annotate(count=Count('id')).order_by('-count'):
        ship_data.append([method_labels_map.get(m['shipping_method'], m['shipping_method']), str(m['count'])])
    ship_table = Table(ship_data, colWidths=[8*cm, 8*cm])
    ship_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B3A5C')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F7FAFF')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    elements.append(ship_table)

    doc.build(elements)
    buf.seek(0)
    fname = f'report_{start_date}_{end_date}.pdf'
    response = HttpResponse(buf.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


@module_required('orders')
def admin_stats(request):
    """
    AJAX endpoint: Returns real-time admin KPI statistics.

    Args:
        request (HttpRequest): The incoming AJAX GET request.

    Returns:
        JsonResponse: {'success': True, 'product_count': int, 'customer_count': int,
                       'order_count': int, 'ledger_count': int,
                       'pending_requests': int, 'pending_orders': int}

    Business Logic:
        The admin stats bar at the top of every admin page needs real-time data.
        Instead of requiring every view to pass these counts in context, this
        endpoint provides them on-demand via AJAX. The frontend fetches them on
        page load and populates the mini stat widgets.

    Django Concepts:
        - Model.objects.count(): Efficient database-level COUNT query.
        - Order.objects.filter(is_placed=False): Counts orders not yet placed with supplier.
        - ProductRequest.objects.filter(status='pending'): Counts unreviewed requests.
    """
    from products.models import Product
    from customers.models import Customer
    from khata.models import LedgerEntry
    from portal.models import ProductRequest

    return JsonResponse({
        'success': True,
        'product_count': Product.objects.count(),
        'customer_count': Customer.objects.count(),
        'order_count': Order.objects.count(),
        'ledger_count': LedgerEntry.objects.count(),
        'pending_requests': ProductRequest.objects.filter(status='pending').count(),
        'pending_orders': Order.objects.filter(is_placed=False).count(),
    })



# =============================================================================
# SHIPMENT STATUS TRACKING
# =============================================================================

@module_required('orders')
def set_shipment_status(request, order_id):
    """
    POST: set the transit status of one shipment block of an order.

    Expects ``shipment_no`` and ``status`` in the POST body. Creates or updates
    the ShipmentStatus row, notifies the customer in-portal, and audits the
    change. Returns to the orders list (or the referring page).
    """
    from accounts.services import log_action, notify_customer

    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        try:
            shipment_no = int(request.POST.get('shipment_no', 1))
        except (TypeError, ValueError):
            shipment_no = 1
        status = request.POST.get('status', '')
        if status in dict(ShipmentStatus.STATUS_CHOICES):
            note = request.POST.get('note', '').strip()
            obj, _created = ShipmentStatus.objects.update_or_create(
                order=order, shipment_no=shipment_no,
                defaults={'status': status, 'note': note},
            )
            log_action(request, 'shipment.status', target=f'Order #{order.id} shipment {shipment_no}',
                       detail=obj.get_status_display())
            notify_customer(
                order.customer,
                f'Shipment {shipment_no} of order #{order.id} is now: {obj.get_status_display()}',
                notification_type='shipment', order=order,
            )
            messages.success(request, f'Shipment {shipment_no} of order #{order.id} marked "{obj.get_status_display()}".')
        else:
            messages.error(request, 'Invalid shipment status.')
    return redirect(request.META.get('HTTP_REFERER') or '/orders/')


# =============================================================================
# PAYMENT RECORDING
# =============================================================================

@module_required('orders')
def record_payment(request, order_id):
    """
    Record a payment received against an order.

    Creates a credit LedgerEntry linked to the order, recomputes the order's
    payment_status from the sum of linked credits vs the order total, notifies
    the customer, and audits the action. GET shows the small form + history.
    """
    from decimal import Decimal, InvalidOperation
    from khata.models import LedgerEntry
    from accounts.services import log_action, notify_customer

    order = get_object_or_404(Order.objects.select_related('customer'), id=order_id)
    company = CompanySettings.get_settings()

    linked = LedgerEntry.objects.filter(order=order, entry_type='credit').order_by('-date')
    paid_total = linked.aggregate(s=Sum('amount'))['s'] or Decimal('0')

    if request.method == 'POST':
        raw_amount = request.POST.get('amount', '').strip()
        currency = request.POST.get('currency', company.currency or 'RMB').strip() or 'RMB'
        note = request.POST.get('description', '').strip()
        try:
            amount = Decimal(raw_amount)
            if amount <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError):
            messages.error(request, 'Please enter a valid positive amount.')
            return redirect('record_payment', order_id=order.id)

        LedgerEntry.objects.create(
            customer=order.customer,
            entry_type='credit',
            amount=amount,
            currency=currency,
            description=note or f'Payment for Order #{order.id}',
            order=order,
        )

        # Recompute payment status from everything linked to this order.
        paid_total = (LedgerEntry.objects.filter(order=order, entry_type='credit')
                      .aggregate(s=Sum('amount'))['s'] or Decimal('0'))
        if paid_total >= (order.total or Decimal('0')) and order.total:
            order.payment_status = 'paid'
        elif paid_total > 0:
            order.payment_status = 'partial'
        else:
            order.payment_status = 'unpaid'
        order.save(update_fields=['payment_status'])

        log_action(request, 'payment.recorded', target=f'Order #{order.id} ({order.customer.name})',
                   detail=f'{currency} {amount}')
        notify_customer(
            order.customer,
            f'Payment of {currency} {amount} recorded for order #{order.id}. Thank you!',
            notification_type='payment', order=order,
        )
        messages.success(request, f'Payment of {currency} {amount} recorded for order #{order.id}.')
        return redirect('record_payment', order_id=order.id)

    return render(request, 'orders/record_payment.html', {
        'order': order,
        'company': company,
        'linked_payments': linked,
        'paid_total': paid_total,
        'outstanding': (order.total or Decimal('0')) - paid_total,
    })


@module_required('orders')
def manage_shipments(request, order_id):
    """
    Per-order shipment management: every shipment block of the order (including
    'manual' method blocks, which the By Air / By Sea tabs don't show) with a
    status selector and optional note. Status changes POST to
    ``set_shipment_status`` and land back here.
    """
    order = get_object_or_404(Order.objects.select_related('customer'), id=order_id)
    items = order.items.select_related('product').all()

    # Group items into shipment blocks (same grouping the customer portal uses).
    blocks_map = {}
    for item in items:
        sno = item.shipment_no or 1
        blocks_map.setdefault(sno, []).append(item)

    status_by_no = {ss.shipment_no: ss for ss in order.shipment_statuses.all()}

    blocks = []
    for sno in sorted(blocks_map.keys()):
        block_items = blocks_map[sno]
        ss = status_by_no.get(sno)
        blocks.append({
            'shipment_no': sno,
            'name': block_items[0].shipment_name or '',
            'method': block_items[0].shipment_method or 'manual',
            'items': block_items,
            'total_qty': sum(i.quantity for i in block_items),
            'status': ss.status if ss else '',
            'note': ss.note if ss else '',
            'updated_at': ss.updated_at if ss else None,
        })

    return render(request, 'orders/manage_shipments.html', {
        'order': order,
        'blocks': blocks,
        'status_choices': ShipmentStatus.STATUS_CHOICES,
    })


# =============================================================================
# PUBLIC SHIPMENT TRACKING  (no login)
# =============================================================================
# One page, reachable by anyone holding a tracking number, that answers "where
# are my goods?".
#
# WHAT IT DELIBERATELY DOES NOT SHOW
#   The number is a bearer credential: whoever has it sees the page, and numbers
#   get forwarded, screenshotted and pasted into group chats. So the page carries
#   only what tracking actually needs - what is in each shipment block and where
#   that block has got to.
#
#   Excluded, and each for its own reason:
#     * customer name, phone, email, address - the explicit requirement, and the
#       thing that would turn a forwarded number into a data leak
#     * every price, the order total, shipping cost and commission - a tracking
#       page has no use for money, and what someone paid is nobody else's
#       business
#     * the supplier listing URL - staff-only everywhere else in this project;
#       it is where the goods are bought and would let a buyer skip us
#     * the order id and invoice number - sequential, so printing them tells a
#       reader how many orders exist and lets them guess neighbours
#     * internal notes - written for staff, by staff
#
#   The view builds an explicit dict per row rather than handing the template an
#   Order. Passing the model and trusting the template not to render
#   `order.customer.phone` is a rule nobody can enforce; a whitelist is checkable
#   in one screen and cannot leak a field added to the model later.
# =============================================================================

def track_shipment(request):
    """
    Public tracking page.

    Args:
        request (HttpRequest): Anonymous. ``?number=`` carries the reference;
            without it the page is just the search form.

    Returns:
        HttpResponse: The form, the result, or a not-found message.
    """
    raw = (request.GET.get('number') or '').strip()

    context = {
        'settings': CompanySettings.get_settings(),
        'query': raw,
        'searched': bool(raw),
        'result': None,
    }
    if not raw:
        return render(request, 'orders/track.html', context)

    # Case- and separator-insensitive. The number is read off a phone screen and
    # typed back by hand: "mlk 7f3k9qx2vb4t" is the same reference as
    # "MLK-7F3K-9QX2-VB4T" and refusing it teaches nobody anything.
    normalised = re.sub(r'[^A-Z0-9]', '', raw.upper())

    # Two indexed lookups, never a scan. This endpoint is public and
    # unauthenticated, so walking every order per request would hand anyone a
    # cheap way to load the database by holding down a key.
    #
    # First the reference exactly as stored, then the canonical form rebuilt from
    # the stripped input, which is what turns "mlk 7f3k9qx2vb4t" into a hit.
    candidates = [raw.upper()]
    if normalised.startswith(Order.TRACKING_PREFIX):
        body = normalised[len(Order.TRACKING_PREFIX):]
        if len(body) == 12:
            grouped = '-'.join(body[i:i + 4] for i in range(0, 12, 4))
            candidates.append(f'{Order.TRACKING_PREFIX}-{grouped}')

    order = (
        Order.objects.filter(tracking_number__in=candidates).first()
        if normalised else None
    )

    # A freight-only job carries the same kind of reference, so the customer
    # should not have to know which sort of job theirs is before they can track
    # it. Checked second because product orders are the common case.
    if order is None and normalised:
        from .models import LogisticsOrder
        job = LogisticsOrder.objects.filter(tracking_number__in=candidates).first()
        if job is not None:
            context['result'] = _build_logistics_tracking_view(job)
            return render(request, 'orders/track.html', context)

    if order is None:
        # Same message whether the number never existed or belongs to an order
        # this visitor should not see. Distinguishing them would confirm which
        # references are real and make guessing worthwhile.
        context['not_found'] = True
        return render(request, 'orders/track.html', context)

    context['result'] = _build_tracking_view(order)
    return render(request, 'orders/track.html', context)


def _tracking_timeline(status_value, note='', updated_at=None, confirmed=False):
    """
    Build the status block that track.html renders, for either kind of job.

    Args:
        status_value (str): A ShipmentStatus.STATUS_* value.
        note (str): Optional free text from the office.
        updated_at (datetime|None): When somebody last set the status.
        confirmed (bool): True only when a human actually set it. The template
            uses this to avoid printing a confident "Last update" for a stage
            that was inferred rather than recorded.

    Returns:
        dict: label, note, updated_at, step_index, is_delivered, confirmed, steps.

    WHY THIS IS SHARED

    Both tracking builders used to assemble this dict themselves, and the
    freight one quietly stopped: it passed a bare status string where the
    template expected an object, so {{ block.status.label }} and
    {% for step in block.status.steps %} rendered nothing at all. A customer
    tracking a freight job saw an empty badge over an empty timeline.

    Two copies of a shape that a template reads by attribute name will drift,
    and nothing fails loudly when they do — Django templates resolve a missing
    attribute to the empty string. One builder is the fix.
    """
    choices = list(ShipmentStatus.STATUS_CHOICES)
    try:
        step_index = ShipmentStatus.STATUS_ORDER.index(status_value)
    except ValueError:
        # An unrecognised value pins to the first rung rather than raising. The
        # page is public and unauthenticated; a stray status in the database
        # should degrade to "Preparing", not to a 500.
        step_index = 0
        status_value = ShipmentStatus.STATUS_PREPARING

    return {
        'label': dict(choices).get(status_value, ''),
        'note': note,
        'updated_at': updated_at,
        'step_index': step_index,
        'is_delivered': status_value == ShipmentStatus.STATUS_DELIVERED,
        'confirmed': confirmed,
        # The whole ladder, so the template draws a timeline rather than one
        # word with no sense of how far along it is.
        'steps': [
            {'label': label, 'done': index <= step_index}
            for index, (_value, label) in enumerate(choices)
        ],
    }


def _build_logistics_tracking_view(job):
    """
    Shape a freight-only job into what the public page renders.

    Deliberately the SAME contract as _build_tracking_view, so track.html does
    not need to know which kind of job it is showing - and deliberately just as
    sparse. The customer's name, phone and what they paid are not on this page:
    the reference is shareable, so anyone holding it can see it, and it must
    therefore carry only what a courier's tracking page would.
    """
    # A freight job's status IS set by hand — there is no separate
    # ShipmentStatus row that may or may not exist — so it is always confirmed.
    status = _tracking_timeline(
        job.status,
        note=job.notes,
        updated_at=job.updated_at,
        confirmed=True,
    )

    # The photo the office uploaded when the job was booked. It is the only
    # picture a freight job has: these are the customer's own goods, so there is
    # no catalogue product behind them to borrow an image from.
    photo = job.photo.url if job.photo else ''

    return {
        'tracking_number': job.tracking_number,
        'placed_on': job.created_at,
        'status_label': job.status_label,
        'progress': job.progress_percent,
        'total_items': job.carton_qty or 0,
        'all_delivered': job.status == ShipmentStatus.STATUS_DELIVERED,
        'is_logistics': True,
        'blocks': [{
            'number': 1,
            'name': job.description,
            'image': photo,
            'cartons': job.carton_qty or 0,
            'weight': job.weight_kg,
            'cbm': job.cbm,
            'status': status,
            'items': [{
                'name': job.description,
                'variant': '',
                'quantity': job.carton_qty or 1,
                'image': photo,
            }],
        }],
    }


def _build_tracking_view(order):
    """
    Shape one order into exactly what the public page may render.

    Args:
        order (Order): The matched order.

    Returns:
        dict: Only whitelisted, non-identifying fields. See the section header
        above for what is excluded and why.
    """
    statuses = {s.shipment_no: s for s in order.shipment_statuses.all()}

    # 'product__images' is prefetched because every item now asks its product
    # for a picture. Without it that is one query per line on a public,
    # unauthenticated page.
    items = (
        order.items.select_related('product', 'variant')
        .prefetch_related('product__images')
        .order_by('shipment_no', 'id')
    )

    blocks = {}
    for item in items:
        block = blocks.setdefault(item.shipment_no, {
            'number': item.shipment_no,
            'name': item.shipment_name or f'Shipment {item.shipment_no}',
            'method': item.get_shipment_method_display(),
            'cargo_type': item.get_cargo_type_display(),
            # Weight and CBM describe the goods, not the buyer, and are what a
            # customer checks against their own freight expectations.
            'weight': item.shipment_weight,
            'cbm': item.shipment_cbm,
            'cartons': 0,
            'items': [],
            'status': None,
            # Filled from the first item that has a picture, below.
            'image': '',
        })
        block['cartons'] += item.carton_quantity or 0

        # A variation's own photo when it has one, otherwise the product's.
        # A customer who ordered the blue one should see the blue one.
        #
        # .src rather than .image.url throughout: src returns '' when the file is
        # missing and NEVER the supplier's CDN, so a failed import renders a
        # clean placeholder here instead of a broken frame. See ProductImage.src.
        image = ''
        if item.variant_id and getattr(item.variant, 'src', ''):
            image = item.variant.src
        else:
            primary = item.product.primary_image
            if primary is not None:
                image = primary.src

        if image and not block['image']:
            block['image'] = image

        block['items'].append({
            'name': item.product.name,
            'variant': item.variant.name if item.variant_id else '',
            'quantity': item.quantity,
            'image': image,
            # NO price. See the section header.
        })

    for number, block in blocks.items():
        status = statuses.get(number)

        # A shipment with no ShipmentStatus row still gets a timeline, pinned to
        # the first rung.
        #
        # This used to `continue`, which meant the template's `{% if block.status %}`
        # skipped the timeline entirely — so a customer who tracked a real order
        # saw its contents and weight and no progress whatsoever, until somebody
        # in the office happened to set a status by hand. "Where is my shipment"
        # is the only question the page exists to answer, and for every
        # not-yet-touched order it answered nothing.
        #
        # Defaulting to Preparing is honest rather than optimistic: an order that
        # exists and has not been dispatched IS being prepared, and it is the
        # same value ShipmentStatus.status defaults to.
        block['status'] = _tracking_timeline(
            status.status if status else ShipmentStatus.STATUS_PREPARING,
            note=status.note if status else '',
            updated_at=status.updated_at if status else None,
            # True only when the office has actually set a status.
            confirmed=status is not None,
        )

    ordered_blocks = [blocks[key] for key in sorted(blocks)]

    return {
        'tracking_number': order.tracking_number,
        'placed_on': order.date,
        'status_label': order.get_status_display(),
        'blocks': ordered_blocks,
        'total_items': sum(len(b['items']) for b in ordered_blocks),
        # True when every block that has a status has reached Delivered, so the
        # page can say so at the top instead of making the reader check each one.
        'all_delivered': bool(ordered_blocks) and all(
            b['status'] and b['status']['is_delivered'] for b in ordered_blocks
        ),
    }


# =============================================================================
# LOGISTICS ORDERS (freight-only jobs)
# =============================================================================

@module_required('orders')
def logistics_order_list(request):
    """Every freight-only job, newest first."""
    from .models import LogisticsOrder

    jobs = LogisticsOrder.objects.select_related('customer')
    query = (request.GET.get('q') or '').strip()
    if query:
        jobs = jobs.filter(
            Q(tracking_number__icontains=query)
            | Q(description__icontains=query)
            | Q(customer__name__icontains=query)
            | Q(contact_name__icontains=query)
        )
    status = (request.GET.get('status') or '').strip()
    if status:
        jobs = jobs.filter(status=status)

    return render(request, 'orders/logistics_list.html', {
        'jobs': jobs,
        'customers': Customer.objects.filter(is_active=True).order_by('name'),
        'status_choices': LogisticsOrder.STATUS_CHOICES,
        'query': query,
        'active_status': status,
        'settings': CompanySettings.get_settings(),
    })


@module_required('orders')
def logistics_order_save(request, job_id=None):
    """
    Create or update a freight-only job.

    The tracking number is never taken from the form - it is assigned by the
    model on first save and then immutable. Letting staff type one would allow
    two jobs to collide, and the reference is already printed on the customer's
    paperwork by the time anyone thinks to edit it.
    """
    from .models import LogisticsOrder

    if request.method != 'POST':
        return redirect('logistics_order_list')

    job = get_object_or_404(LogisticsOrder, id=job_id) if job_id else LogisticsOrder()

    raw_customer = (request.POST.get('customer_id') or '').strip()
    job.customer = Customer.objects.filter(id=raw_customer).first() if raw_customer else None
    job.contact_name = (request.POST.get('contact_name') or '').strip()[:200]
    job.contact_phone = (request.POST.get('contact_phone') or '').strip()[:50]
    job.description = (request.POST.get('description') or '').strip()[:255]
    job.notes = (request.POST.get('notes') or '').strip()

    job.weight_kg = _to_decimal(request.POST.get('weight_kg'), '0')
    job.shipping_price = _to_decimal(request.POST.get('shipping_price'), '0')

    raw_cartons = (request.POST.get('carton_qty') or '').strip()
    job.carton_qty = int(raw_cartons) if raw_cartons.isdigit() else None
    raw_cbm = (request.POST.get('cbm') or '').strip()
    job.cbm = _to_decimal(raw_cbm, '0') if raw_cbm else None

    status = (request.POST.get('status') or '').strip()
    if status in dict(LogisticsOrder.STATUS_CHOICES):
        job.status = status

    if not job.description:
        messages.error(request, 'Describe what is being shipped.')
        return redirect('logistics_order_list')

    photo = request.FILES.get('photo')
    if photo:
        job.photo = photo

    job.save()
    messages.success(
        request,
        f'Logistics order {job.tracking_number} saved.' if job_id is None
        else f'{job.tracking_number} updated.'
    )
    return redirect('logistics_order_list')


@module_required('orders')
def logistics_order_status(request, job_id):
    """Move one job along the status ladder, from the list screen."""
    from .models import LogisticsOrder

    job = get_object_or_404(LogisticsOrder, id=job_id)
    status = (request.POST.get('status') or '').strip()
    if status not in dict(LogisticsOrder.STATUS_CHOICES):
        return JsonResponse({'success': False, 'message': 'Unknown status.'}, status=400)
    job.status = status
    job.save(update_fields=['status', 'updated_at'])
    return JsonResponse({
        'success': True,
        'status': job.status,
        'label': job.status_label,
        'progress': job.progress_percent,
    })


@module_required('orders')
def logistics_order_delete(request, job_id):
    from .models import LogisticsOrder
    if request.method == 'POST':
        job = get_object_or_404(LogisticsOrder, id=job_id)
        ref = job.tracking_number
        job.delete()
        messages.success(request, f'Logistics order {ref} deleted.')
    return redirect('logistics_order_list')


# =============================================================================
# PRODUCT LOOKUP (order builder + quotation picker)
# =============================================================================

# How many products the order list renders without being asked. Enough that the
# picker is useful the moment it opens, small enough that the page weight no
# longer tracks the size of the catalogue.
ORDER_BUILDER_PAGE_SIZE = 50


def _product_lookup_payload(products):
    """
    The fields the order builder and the quotation picker actually use.

    Deliberately NOT the whole model: this is read by two bits of JavaScript
    that need a price, a weight and the carton dimensions to compute freight.
    Serialising everything would put cost prices and supplier notes into a
    response the browser can read.
    """
    rows = []
    for product in products:
        image = ''
        first_image = next(iter(product.images.all()), None)
        if first_image is not None and getattr(first_image, 'image', None):
            try:
                image = first_image.image.url
            except ValueError:
                image = ''
        rows.append({
            'id': product.id,
            'name': product.name,
            'sku': product.sku or '',
            'price': str(product.price or 0),
            'weight': str(product.weight or ''),
            'carton_qty': str(product.carton_qty or ''),
            'carton_length': str(product.carton_length or ''),
            'carton_width': str(product.carton_width or ''),
            'carton_height': str(product.carton_height or ''),
            'image': image,
        })
    return rows


@module_required('orders')
def product_lookup(request):
    """
    Search the catalogue for the order builder, as JSON.

    Args:
        request (HttpRequest): ``?q=`` search text, ``?ids=`` comma-separated
            ids to fetch regardless of the search.

    Returns:
        JsonResponse: {'products': [...], 'total': n, 'truncated': bool}

    WHY THIS EXISTS

    The order list used to render the ENTIRE catalogue into its HTML twice over
    — once as a picker row per product and once as a JavaScript array — so that
    the quotation picker could filter client-side. That made the weight of the
    busiest page in the back office a function of how many products exist:
    169 KB at 30 products, 810 KB at 500, and roughly 5 MB at 3,000.

    Searching on the server keeps that page a constant size. It also searches
    the whole catalogue rather than only what happened to be rendered, which is
    what staff assumed the box did already.

    ``ids`` exists so a selection survives a new search: the picker re-asks for
    the products the user has already ticked and re-renders them as checked,
    instead of losing them the moment the result list is replaced.
    """
    query = (request.GET.get('q') or '').strip()
    raw_ids = (request.GET.get('ids') or '').strip()

    base = (Product.objects
            .filter(is_draft=False)
            .prefetch_related('images')
            .order_by('name'))

    if raw_ids:
        wanted = [int(i) for i in raw_ids.split(',') if i.strip().isdigit()][:200]
        selected = base.filter(id__in=wanted)
        return JsonResponse({'products': _product_lookup_payload(selected),
                             'total': len(wanted), 'truncated': False})

    # Every word must appear in the name or the SKU, in any order. Matching the
    # whole query as one substring missed real products: "red bag" found
    # nothing for "Red Leather Bag", and names imported from supplier pages
    # often carry doubled or odd spacing that a typed query never reproduces.
    for word in query.split():
        base = base.filter(Q(name__icontains=word) | Q(sku__icontains=word))

    total = base.count()
    page = base[:ORDER_BUILDER_PAGE_SIZE]
    return JsonResponse({
        'products': _product_lookup_payload(page),
        'total': total,
        # The picker says so rather than quietly showing a partial list — a
        # truncated result the user believes is complete is how a product gets
        # left off a quotation.
        'truncated': total > ORDER_BUILDER_PAGE_SIZE,
    })
