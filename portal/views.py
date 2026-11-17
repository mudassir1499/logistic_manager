"""
portal/views.py
================================================================================
Customer Portal Views for the Logistics Management System
================================================================================

This module handles ALL customer-facing and public-facing views for the logistics
portal. It is divided into sections:

  1. Session Authentication (custom decorator)
  2. Public Pages (landing, about, services, contact, portfolio)
  3. Customer Authentication (login, logout, register, forgot password, reset password)
  4. Customer Dashboard (orders, ledger, products, profile)
  5. Product Quotation Requests (customers request product quotes with images)
  6. Admin Customer Management (list, add, edit, delete customers)
  7. Admin Product Request Management (review, convert, reject requests)
  8. Admin Portfolio Management (curate public-facing portfolio)

Business Context:
  - This is a B2B logistics platform where customers (importers/exporters) can
    log in to view their orders, track shipments, view their financial ledger,
    request quotations for new products, and browse the company's portfolio.
  - Admins manage customers, review product quotation requests, and curate the
    public portfolio that showcases the company's work and capabilities.
  - The system uses Django's built-in session framework for customer authentication
    instead of Django's default auth system because customers are separate entities
    from staff users (who use Django's standard login_required).
"""

# ==============================================================================
# IMPORTS
# ==============================================================================

# functools.wraps is a Python utility that preserves the original function's
# metadata (name, docstring, etc.) when it is wrapped by a decorator.
from functools import wraps

# Django's shortcut functions for common view operations:
#   - render: renders a template with context and returns an HttpResponse
#   - redirect: returns an HTTP redirect response to a URL
#   - get_object_or_404: fetches a database object or raises a 404 error
from django.shortcuts import render, redirect, get_object_or_404

# reverse() builds a URL from its route name, so redirect targets never hardcode
# a path that could later change.
from django.urls import reverse

# JsonResponse is a Django HttpResponse subclass that serializes data to JSON.
# Used for AJAX endpoints (login, register, profile update) so the frontend
# can receive structured data without a full page reload.
from django.http import Http404, JsonResponse

# Sum is a Django ORM aggregation function that adds up values across a queryset.
# Used in the ledger to calculate total credit and debit amounts per currency.
from django.db.models import Sum, Count, Q

# Paginator splits a long queryset across numbered pages. Used by the public blog
# index so a growing archive never renders every article in one enormous response.
from django.core.paginator import Paginator

# Django's messages framework provides a one-time notification system
# that persists across redirects. Used by admin views to show success/error
# flash messages (e.g., "Customer created successfully").
from django.contrib import messages

# Decimal is Python's fixed-point arithmetic type. Critical for financial
# calculations (ledger balances, order totals) to avoid floating-point
# rounding errors that would cause discrepancies in money calculations.
from decimal import Decimal, InvalidOperation

# json is used to read the JSON request bodies posted by the shipping
# calculator. (One older view imports it locally; this module-level import is
# the one new code should use.)
import json

# Django's built-in login_required decorator. This checks the standard Django
# session auth (for staff/admin users). It is DIFFERENT from our custom
# customer_login_required decorator which checks customer session auth.
from django.contrib.auth.decorators import login_required, user_passes_test, user_passes_test

# Unified auth building blocks:
#   customer_required  - the Django-auth customer guard (aliased below as
#                        customer_login_required so existing views are untouched).
#   module_required    - gates the admin-management views by back-office module.
#   sync_customer_user - keeps a Customer's Django User login in step when admins
#                        create or edit customers.
from accounts.decorators import customer_required, module_required
from accounts.services import sync_customer_user

# Import timezone and timedelta for rate limiting and token expiry calculations.
from django.utils import timezone
from datetime import timedelta

# Typed email helper selects the correct SMTP profile (security, order_status, news)
# from CompanySettings so transactional emails use the right sender account.
from utils.email_utils import send_typed_email

# ==============================================================================
# MODEL IMPORTS
# ==============================================================================
# We import models from various apps so we can query the database.
# Each app is responsible for a domain of the business:

# customers: Customer accounts and product assignments
from customers.models import Customer, CustomerProduct

# products: Product catalog, SKUs, images, carton specs
from products.models import Category, Product, ProductImage

# orders: Purchase orders, line items, shipment tracking
from orders.models import Order, OrderItem

# khata: Ledger / financial entries (credit/debit transactions per customer)
from khata.models import LedgerEntry

# settings_manager: Company-wide settings (name, logo, phone, currency, etc.)
from portal import antispam
from portal import captcha
from settings_manager.models import (CargoType, CompanySettings,
                                     ShippingCompany, ShippingDestination,
                                     TeamMember)

# The freight maths behind the public shipping calculator. It lives in its own
# module because the same rules have to serve this page, the staff rate screen
# and eventually the order flow - see settings_manager/quoting.py.
from settings_manager import quoting

# portal models: Product quotation requests, portfolio items, password reset requests,
# cart items, and contact form submissions.
from .checkout import create_order_from_cart, requires_labels
from .models import ProductRequest, ProductRequestImage, PortfolioItem, PasswordResetRequest, CartItem, ContactMessage

# support models: customer-raised tickets and their message threads.
from support.models import Ticket, TicketMessage, TicketAttachment


# ==============================================================================
# SECTION 1: CUSTOMER AUTHENTICATION DECORATOR (unified Django auth)
# ==============================================================================
# Customer auth is no longer a bespoke session hack. Every customer now has a
# Django ``User`` (created/linked by the accounts app), and this decorator is a
# thin alias of ``accounts.decorators.customer_required``: it enforces a logged-in
# Django user with the ``customer`` role and attaches the linked ``Customer`` to
# ``request.customer`` — exactly the contract the views below already rely on. The
# old ``@customer_login_required`` name is kept so none of those views change.

customer_login_required = customer_required


# ==============================================================================
# SECTION 2: PUBLIC PAGES (No login required)
# ==============================================================================
# These pages are accessible to anyone on the internet. They serve as the
# company's public storefront — showing services, portfolio, and contact info.
# Even if the visitor is not logged in, we still try to show them as a
# recognized customer so the navbar can show their name/logout link.


def front_page(request):
    """
    Renders the public landing page (homepage) of the logistics portal.
    
    Args:
        request (HttpRequest): The incoming HTTP request from the browser.
    
    Returns:
        HttpResponse: A rendered HTML page for the homepage with company settings,
                      customer info (if logged in), and featured portfolio items.
    
    Business Logic:
        The front page is the company's digital storefront. It showcases the
        business to potential customers. We display up to 4 active portfolio items
        (e.g., photos of shipped cargo, warehouse operations) to build trust.
        If the visitor is already logged in, we pass their Customer object so
        the navbar can show "Welcome, [Name]" instead of "Login".
    """
    # Fetch company-wide settings (business name, phone, address, logo).
    # CompanySettings uses a singleton pattern (get_settings) because there's
    # only one row of settings for the entire company.
    settings = CompanySettings.get_settings()
    
    # Start with customer = None (not logged in).
    # If the visitor has a customer_id session, try to fetch their profile
    # so the template can show personalized UI elements (greeting, logout link).
    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            # Customer no longer exists; ignore the stale session silently.
            pass
    
    # Fetch the 4 most recently created active portfolio items to showcase
    # on the homepage. The [:4] slice limits the queryset to 4 records,
    # which is efficient because Django only queries the database for those 4.
    portfolio_items = PortfolioItem.objects.filter(is_active=True)[:4]

    # Real products for the marketplace section, which until now was a single
    # card linking to the catalogue — a storefront homepage that showed no
    # stock. Newest first, matching what /shop/ opens on, so a visitor who
    # clicks through sees the products they just saw.
    #
    # Products WITH a photo are preferred: a homepage grid of placeholder icons
    # looks broken in a way an empty section does not. The fallback keeps the
    # section populated on a catalogue whose images have not been fetched yet
    # (see `fetch_remote_images`).
    # `images__image__gt=''` rather than `images__isnull=False`: a product can
    # have image ROWS that hold only a supplier URL and no downloaded file, and
    # those render nothing at all (see ProductImage.src), so they would put empty
    # placeholder tiles on the homepage. This keeps products with at least one
    # image whose file is actually stored.
    featured = list(
        _public_products().filter(images__image__gt='').distinct().order_by('-id')
        [:HOMEPAGE_PRODUCT_COUNT]
    )
    if not featured:
        featured = list(_public_products().order_by('-id')[:HOMEPAGE_PRODUCT_COUNT])

    # The card partial is shared with /shop/, so it is handed the same shape.
    # `in_cart` is always False here: this section is a shop window, and the
    # homepage should not run a cart query for every visitor to decorate it.
    featured_products = [
        {'product': p, 'first_image': p.primary_image, 'cbm': None, 'in_cart': False}
        for p in featured
    ]

    # Drives the card's Order / "Sign in to order" button. Read from the profile
    # rather than the legacy session above, so it agrees with what /shop/ shows.
    is_customer = bool(
        request.user.is_authenticated
        and getattr(getattr(request.user, 'profile', None), 'customer', None)
    )

    # Render the front_page.html template, passing context variables that the
    # template can use: settings (company info), customer (if logged in),
    # and portfolio_items (featured gallery).
    return render(request, 'portal/front_page.html', {
        'settings': settings,
        'customer': customer,
        'portfolio_items': portfolio_items,
        'featured_products': featured_products,
        'is_customer': is_customer,
        # The homepage sourcing form posts to contact_page, so it carries the
        # same spam defences as the contact form.
        'antispam_field': antispam_field_name(),
        'form_started_at': _form_timestamp_value(request),
        'captcha': captcha.new_challenge(),
    })


# ==============================================================================
# SECTION 3: CUSTOMER AUTHENTICATION (delegated to the unified accounts app)
# ==============================================================================
# Login, logout, registration and password reset now live in the accounts app so
# there is a single Django-auth flow for every role. These thin shims preserve the
# historical portal URL names (portal_login, portal_register, ...) by redirecting
# to their accounts equivalents, so existing links and bookmarks keep working.


def customer_login(request):
    """Legacy portal login URL — redirect to the unified login."""
    return redirect('account_login')


def customer_logout(request):
    """Legacy portal logout URL — redirect to the unified logout."""
    return redirect('account_logout')


def customer_register(request):
    """Legacy portal registration URL — redirect to the unified registration."""
    return redirect('account_register')


def forgot_password(request):
    """Legacy forgot-password URL — redirect to the unified password reset."""
    return redirect('account_password_reset')


def forgot_password_done(request):
    """Legacy confirmation page — the unified flow messages the user on login."""
    return redirect('account_login')


def reset_password(request):
    """Legacy reset URL — redirect to request a fresh (signed) reset link."""
    return redirect('account_password_reset')


# ==============================================================================
# SECTION 4: CUSTOMER DASHBOARD
# ==============================================================================
# These views are protected by @customer_login_required. They provide customers
# with a self-service dashboard where they can view their orders, track shipments,
# check their financial balance, browse assigned products, and manage their profile.
# This reduces the admin team's support burden by empowering customers to find
# their own information 24/7.


@customer_login_required
def customer_dashboard(request):
    """
    Renders the main customer dashboard with summary statistics and quick links.
    
    Args:
        request (HttpRequest): The incoming request, with request.customer set
                                by the customer_login_required decorator.
    
    Returns:
        HttpResponse: A rendered HTML dashboard page with summary cards.
    
    Business Logic:
        The dashboard is the customer's command center. It shows at a glance:
          - How many orders they've placed (order_count)
          - Their financial balance per currency (from the ledger)
          - Their 5 most recent orders (recent_orders)
          - How many products are assigned to them (product_count)
          - How many product quotation requests are pending (pending_requests)
        This gives the customer a quick health check of their business relationship
        with the logistics company without needing to dig into detailed reports.
    """
    # request.customer is attached by the customer_login_required decorator.
    # It is the Customer model instance for the currently logged-in user.
    customer = request.customer
    
    # Fetch all orders belonging to this customer, ordered by date descending.
    # The minus sign (-date) means newest orders first. This is a Django ORM
    # queryset — it is lazy, meaning the database is NOT queried until we use
    # the data (e.g., .count() or iterate over it).
    orders = Order.objects.filter(customer=customer).order_by('-date')
    order_count = orders.count()  # Efficient COUNT query in the database.
    
    # Fetch all ledger entries for this customer to calculate their balance.
    # The ledger is a financial record of all money owed and paid (credit/debit).
    entries = LedgerEntry.objects.filter(customer=customer)
    
    # Find all unique currencies used in this customer's ledger. A customer may
    # deal in multiple currencies (e.g., USD, EUR, CNY) depending on their trade.
    # values_list('currency', flat=True) returns a flat list of currency strings.
    # .distinct() ensures each currency appears only once.
    currencies_used = entries.values_list('currency', flat=True).distinct()
    
    # Calculate the net balance for each currency.
    # Credit = money the customer has paid (reduces their debt).
    # Debit  = money the customer owes for orders/services.
    # Balance = Credit - Debit. Positive = customer overpaid; Negative = customer owes.
    balances = {}
    for cur in currencies_used:
        # aggregate() runs a database-level aggregation. Sum('amount') adds up
        # all the 'amount' values. The result is a dict like {'s': Decimal('500.00')}.
        # If no entries match, 's' is None, so we use 'or Decimal('0')' as a fallback.
        credit = entries.filter(currency=cur, entry_type='credit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        debit = entries.filter(currency=cur, entry_type='debit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        bal = credit - debit
        # Only include currencies with a non-zero balance to keep the UI clean.
        if bal != 0:
            balances[cur] = bal
    
    # Slice the queryset to get only the 5 most recent orders for the dashboard.
    # This is efficient because the database handles the slicing (LIMIT 5).
    # Each row carries the same all-in total the orders list and order detail show,
    # so the same order does not appear with three different values depending on
    # which page the customer happens to be looking at.
    recent_orders = [
        {
            'order': o,
            'grand_total': ((o.total or Decimal('0')) + (o.shipping_cost or Decimal('0'))
                            + (o.other_cost or Decimal('0')) + (o.commission_amount or Decimal('0'))),
        }
        for o in orders[:5]
    ]
    
    # Count how many products are assigned to this customer through the
    # CustomerProduct junction table. This tells the customer how many SKUs
    # they can order from the catalog.
    product_count = customer.assigned_products.count()
    
    # Count pending product quotation requests. The customer submits requests for
    # products not yet in the catalog; this number tells them how many are still
    # being reviewed by the admin team.
    pending_requests = customer.product_requests.filter(status='pending').count()
    
    # Fetch company settings for the template (logo, business name, contact info).
    settings = CompanySettings.get_settings()
    
    # Render the dashboard template with all the summary data.
    return render(request, 'portal/dashboard.html', {
        'customer': customer,
        'order_count': order_count,
        'balances': balances,
        'recent_orders': recent_orders,
        'product_count': product_count,
        'pending_requests': pending_requests,
        'settings': settings,
    })


@customer_login_required
def customer_orders(request):
    """
    Lists all orders placed by the logged-in customer.
    
    Args:
        request (HttpRequest): The incoming request with request.customer set.
    
    Returns:
        HttpResponse: A rendered HTML page showing all customer orders.
    
    Business Logic:
        Customers need to see their complete order history in one place, and the
        number they actually care about is what each order costs them all-in —
        goods, freight, extras and commission together. The template used to print
        order.total under both a "Total" and a "Grand Total" heading, so the two
        columns always agreed and both were wrong whenever an order carried any
        shipping or commission. The arithmetic now happens here, once, using the
        same formula as the order detail page and the admin invoice.
    """
    customer = request.customer

    # annotate(item_count=...) instead of prefetching every OrderItem and its
    # Product: the list only ever prints how many lines an order has, so counting
    # in the database avoids dragging the whole catalogue into memory per page.
    orders_qs = (Order.objects.filter(customer=customer)
                 .annotate(item_count=Count('items'))
                 .order_by('-date'))

    # The template has always included the pagination partial, but no view ever
    # supplied page_obj, so the controls silently rendered nothing and a customer
    # with a long history downloaded every order they had ever placed.
    paginator = Paginator(orders_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    settings = CompanySettings.get_settings()

    # Each row carries its own money so the template stays free of arithmetic.
    # Decimal('0') fallbacks matter here: the columns are nullable in older rows,
    # and None would poison the sum rather than behaving like zero.
    rows = []
    for order in page_obj.object_list:
        shipping = order.shipping_cost or Decimal('0')
        other = order.other_cost or Decimal('0')
        commission = order.commission_amount or Decimal('0')
        subtotal = order.total or Decimal('0')
        rows.append({
            'order': order,
            'subtotal': subtotal,
            'shipping': shipping,
            'commission': commission,
            'grand_total': subtotal + shipping + other + commission,
        })

    return render(request, 'portal/orders.html', {
        'customer': customer,
        'rows': rows,
        'page_obj': page_obj,
        'order_count': paginator.count,
        'settings': settings,
    })


@customer_login_required
def customer_order_detail(request, order_id):
    """
    Displays the full details of a single order, including an invoice preview.
    
    Args:
        request (HttpRequest): The incoming request with request.customer set.
        order_id (int): The primary key (ID) of the Order to display.
    
    Returns:
        HttpResponse: A rendered HTML page with order details and invoice data.
    
    Business Logic:
        Customers need to verify the specifics of each order: what was ordered,
        how much it cost, shipping fees, and when it was shipped. This view also
        groups order items by shipment number so the customer can see which items
        arrived in which shipment — critical for international logistics where
        orders are often split across multiple containers or vessels.
    """
    customer = request.customer
    
    # get_object_or_404 fetches the Order with the given ID, but only if it
    # belongs to the current customer. If the order doesn't exist OR belongs to
    # another customer, Django raises Http404 (page not found), which prevents
    # customers from viewing each other's orders (a security/privacy measure).
    order = get_object_or_404(Order, id=order_id, customer=customer)
    
    settings = CompanySettings.get_settings()
    
    # Group order items by shipment number. In logistics, a single order may be
    # split into multiple shipments (e.g., partial shipments via different vessels).
    # Each OrderItem has a shipment_no field. We build a dictionary where keys
    # are shipment numbers and values are lists of items in that shipment.
    shipments_dict = {}
    # select_related/prefetch_related here because the template renders each
    # item's product name and thumbnail. Without them every line item costs two
    # extra queries, so a 40-item order issued 80 queries to draw one page.
    for item in order.items.select_related('product').prefetch_related('product__images'):
        # If shipment_no is None, default to 1 (treat as a single shipment).
        sno = item.shipment_no or 1
        if sno not in shipments_dict:
            shipments_dict[sno] = []
        shipments_dict[sno].append(item)
    
    # Transit status per shipment block (set by the back office). The portal
    # renders these as a step timeline so the customer can see exactly where
    # each shipment is without opening a support ticket.
    from orders.models import ShipmentStatus
    status_by_no = {ss.shipment_no: ss for ss in order.shipment_statuses.all()}
    timeline_steps = ShipmentStatus.STATUS_CHOICES  # ordered (value, label) pairs

    # Build a structured list of shipment groups for the template.
    # For each shipment, we calculate the total quantity and subtotal of items.
    invoice_shipments = []
    for sno in sorted(shipments_dict.keys()):
        items = shipments_dict[sno]
        # Sum the quantity of all items in this shipment.
        total_qty = sum(item.quantity for item in items)
        # Calculate the subtotal: price * quantity for each item, summed.
        subtotal = sum(item.price * item.quantity for item in items)
        ss = status_by_no.get(sno)
        invoice_shipments.append({
            'shipment_no': sno,
            'shipment_name': items[0].shipment_name if items else '',
            'items': items,
            'total_qty': total_qty,
            'subtotal': subtotal,
            'method': items[0].shipment_method if items else 'manual',
            'transit': ss,                                   # ShipmentStatus or None
            'transit_step': ss.step_index if ss else -1,     # -1 = not yet tracked
        })
    
    # Calculate the invoice totals. Order.total is the sum of all line items.
    # Additional costs are added on top: shipping, other fees, and commission.
    total = order.total or Decimal('0')
    shipping = order.shipping_cost or Decimal('0')
    other = order.other_cost or Decimal('0')
    commission = order.commission_amount or Decimal('0')
    grand_total = total + shipping + other + commission

    # The rate is shown next to the amount so the commission reads as a rule the
    # customer can check ("5% of 1,200.00") rather than an unexplained fee.
    # Older orders were saved before the percentage was recorded, so fall back to
    # deriving it from the amount rather than printing a misleading "0%".
    commission_pct = order.commission_percentage or Decimal('0')
    if not commission_pct and commission and total:
        commission_pct = (commission / total * Decimal('100')).quantize(Decimal('0.01'))

    return render(request, 'portal/order_detail.html', {
        # Click-to-chat handoff. Empty when no WhatsApp number is configured, so
        # the template hides the button rather than linking to a broken chat.
        'whatsapp_url': order.whatsapp_url(settings),
        # Set by the redirect straight after checkout; the page auto-opens the
        # chat once, and only then. Revisiting the order later shows the button
        # without hijacking the tab.
        'whatsapp_autoopen': request.GET.get('whatsapp') == '1',
        'customer': customer,
        'order': order,
        'shipments': invoice_shipments,
        'timeline_steps': timeline_steps,
        'total': total,
        'shipping': shipping,
        'other': other,
        'commission': commission,
        'commission_pct': commission_pct,
        'grand_total': grand_total,
        'settings': settings,
    })


# =============================================================================
# CATALOGUE SEARCH AND CATEGORY FILTERING
# =============================================================================
# Four portal pages list products — My Products, Marketplace, Amazon and Noon —
# and all four offer the same search box and category filter. The helpers below
# hold that shared behaviour so the four views stay thin and, more importantly,
# so the filters cannot drift apart between pages.
#
# Query parameters, consistent across all four pages:
#   ?q=            free-text search over product name and SKU
#   ?category=     category slug
#   ?subcategory=  subcategory slug
#
# Slugs are used rather than primary keys so the URLs a customer might bookmark
# or share stay readable and survive a database rebuild.


def _parse_catalog_filters(request):
    """
    Read the search and category parameters off the query string.

    Returns:
        dict: {'q': str, 'category': str, 'subcategory': str} — always strings,
        empty when absent, so callers never have to juggle None.
    """
    def _money(key):
        """A positive decimal from the query string, or '' when absent/nonsense."""
        raw = (request.GET.get(key) or '').strip()
        if not raw:
            return ''
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError):
            return ''
        return value if value >= 0 else ''

    sort = (request.GET.get('sort') or '').strip()
    source = (request.GET.get('source') or '').strip().lower()
    return {
        'q': (request.GET.get('q') or '').strip(),
        'category': (request.GET.get('category') or '').strip(),
        'subcategory': (request.GET.get('subcategory') or '').strip(),
        # Price bounds and sort order, added for the public catalogue's sidebar.
        # The other pages pass them through untouched and simply never set them.
        'min_price': _money('min_price'),
        'max_price': _money('max_price'),
        'sort': sort if sort in CATALOG_SORTS else '',
        # Marketplace channel: 'amazon', 'noon' or 'general'.
        #
        # /products/amazon/ and /products/noon/ have redirected here as
        # ?source=amazon / ?source=noon since those pages were retired, but
        # nothing read the parameter — so both redirects landed on the
        # unfiltered catalogue.
        #
        # Validated against the model's own choices rather than a list repeated
        # here, so adding a marketplace to Product.SOURCE_CHOICES is enough. An
        # unrecognised value becomes '' instead of reaching the ORM.
        'source': source if source in CATALOG_SOURCES else '',
    }


# The marketplace channels a customer may filter by, taken straight from the
# model so the two cannot disagree.
CATALOG_SOURCES = {key: label for key, label in Product.SOURCE_CHOICES}


# Sort options offered in the catalogue, mapped to the ORM ordering they apply.
# Kept as a dict so an unrecognised ?sort= value is silently ignored rather than
# reaching the ORM, where an attacker-supplied field name would be a data leak.
CATALOG_SORTS = {
    'price_asc': ('price', 'Price: low to high'),
    'price_desc': ('-price', 'Price: high to low'),
    'name': ('name', 'Name: A to Z'),
    'newest': ('-id', 'Newest first'),
}


def _apply_catalog_filters(queryset, filters, prefix=''):
    """
    Narrow a queryset by the parsed search and category filters.

    Args:
        queryset: Either a Product queryset or one of a model that points at
            Product (CustomerProduct, on the My Products page).
        filters (dict): The output of _parse_catalog_filters.
        prefix (str): Relation path to reach Product from the queryset's model.
            Empty for Product itself; 'product__' for CustomerProduct. This is
            what lets My Products reuse the same code as the other three pages
            despite querying a different table.

    Returns:
        The filtered queryset.

    Business Logic:
        Multi-word searches are ANDed: "nail spray" returns only products
        matching BOTH terms, so adding words narrows the result set the way a
        customer expects. Each individual term may match either the name or the
        SKU, which lets staff paste a SKU straight into the same box.

        Selecting a subcategory alone is sufficient — the category filter is
        not also required, since a subcategory already implies its parent.
    """
    q = filters['q']
    if q:
        for term in q.split():
            queryset = queryset.filter(
                Q(**{f'{prefix}name__icontains': term})
                | Q(**{f'{prefix}sku__icontains': term})
            )

    # The subcategory is the more specific statement, so when both are present
    # it alone decides the result and the category filter adds nothing.
    if filters['subcategory']:
        queryset = queryset.filter(
            **{f'{prefix}subcategory__slug': filters['subcategory']}
        )
    elif filters['category']:
        queryset = queryset.filter(**{f'{prefix}category__slug': filters['category']})

    # Marketplace channel. Independent of category: "Amazon" and "Photo Frames"
    # narrow along different axes and combine rather than replace one another.
    if filters.get('source'):
        queryset = queryset.filter(**{f'{prefix}source': filters['source']})

    # Price bounds. Compared against Product.price, which for a product with
    # variations is its cheapest option — so a "under 50" filter keeps anything
    # that has *something* under 50, which is what a shopper means by it.
    if filters.get('min_price') != '' and filters.get('min_price') is not None:
        queryset = queryset.filter(**{f'{prefix}price__gte': filters['min_price']})
    if filters.get('max_price') != '' and filters.get('max_price') is not None:
        queryset = queryset.filter(**{f'{prefix}price__lte': filters['max_price']})

    if filters.get('sort'):
        ordering, _label = CATALOG_SORTS[filters['sort']]
        queryset = queryset.order_by(f'{prefix}{ordering.lstrip("-")}' if not ordering.startswith('-')
                                     else f'-{prefix}{ordering[1:]}')

    return queryset


def _build_filter_context(scope_queryset, filters, prefix=''):
    """
    Build everything the filter bar template needs.

    Args:
        scope_queryset: The page's full, UNFILTERED queryset. Counts are taken
            from this rather than from the filtered set so that the number
            beside each category still reflects what is available — a count
            computed after filtering would read "1" next to every category.
        filters (dict): The output of _parse_catalog_filters.
        prefix (str): Relation path to Product, as in _apply_catalog_filters.

    Returns:
        dict: Template context — the categories to offer (each with a count and
        its subcategories), the subcategories of the active category, the
        currently selected objects, and whether any filter is active at all.
    """
    # One grouped query for the counts instead of a COUNT per category.
    #
    # .order_by() is essential, not cosmetic. Django appends any existing
    # ordering to the GROUP BY clause, so an ordered source queryset (My
    # Products orders by assigned_at) groups by (slug, assigned_at) and returns
    # one row per product, every count landing at 1. Clearing the ordering
    # first is what makes this group by category alone.
    counts = dict(
        scope_queryset
        .order_by()
        .exclude(**{f'{prefix}category__isnull': True})
        .values_list(f'{prefix}category__slug')
        .annotate(total=Count('id'))
    )

    categories = []
    for category in Category.objects.filter(is_active=True).prefetch_related('subcategories'):
        count = counts.get(category.slug, 0)
        # Hide categories with nothing in them on this page. The Amazon page
        # should not offer a "Photo Frames" filter that returns an empty grid.
        if not count:
            continue
        categories.append({
            'obj': category,
            'count': count,
            'is_active': filters['category'] == category.slug,
        })

    # Subcategories are only listed once a category is chosen; showing all 22 at
    # once would be a wall of options with no useful grouping.
    selected_category = None
    subcategories = []
    if filters['category']:
        selected_category = next(
            (c['obj'] for c in categories if c['obj'].slug == filters['category']),
            None,
        )
    if selected_category:
        # .order_by() for the same GROUP BY reason as the category counts above.
        sub_counts = dict(
            scope_queryset
            .order_by()
            .filter(**{f'{prefix}category': selected_category})
            .exclude(**{f'{prefix}subcategory__isnull': True})
            .values_list(f'{prefix}subcategory__slug')
            .annotate(total=Count('id'))
        )
        for sub in selected_category.subcategories.filter(is_active=True):
            count = sub_counts.get(sub.slug, 0)
            if not count:
                continue
            subcategories.append({
                'obj': sub,
                'count': count,
                'is_active': filters['subcategory'] == sub.slug,
            })

    # Marketplace counts, on the same one-grouped-query pattern as the
    # categories above (and needing the same .order_by() reset for the same
    # GROUP BY reason).
    source_counts = dict(
        scope_queryset
        .order_by()
        .values_list(f'{prefix}source')
        .annotate(total=Count('id'))
    )
    sources = [
        {'key': key, 'label': label, 'count': source_counts.get(key, 0),
         'is_active': filters.get('source') == key}
        for key, label in CATALOG_SOURCES.items()
        if source_counts.get(key, 0)
    ]

    return {
        'filter_q': filters['q'],
        'filter_category': filters['category'],
        'filter_subcategory': filters['subcategory'],
        'filter_source': filters.get('source', ''),
        'filter_sources': sources,
        # Offer the facet only once there is a choice to make. Every product the
        # sourcing extension imports is 'general', so on a catalogue that has
        # never had an Amazon or Noon product this would otherwise be a heading
        # above a single row that filters nothing away.
        'filter_show_sources': len(sources) > 1,
        'filter_source_total': sum(entry['count'] for entry in sources),
        'filter_categories': categories,
        'filter_subcategories': subcategories,
        'filter_selected_category': selected_category,
        # Total across the page's whole scope, for the sidebar's "All products"
        # row. Summing the per-category counts rather than issuing another
        # COUNT query — and it deliberately excludes uncategorised products so
        # the total always equals the sum of the rows beneath it.
        'filter_total_count': sum(entry['count'] for entry in categories),
        # False when the page has nothing to filter, so the templates can drop
        # the category rail and search box entirely rather than showing an
        # empty rail reading "All products 0" beside an empty grid. Filters
        # already applied keep the chrome visible — otherwise a search that
        # matched nothing would remove the very box needed to clear it.
        'catalog_show_filters': bool(categories) or filters['q'] != '' or bool(
            filters['category'] or filters['subcategory'] or filters.get('source')
        ),
        # Drives the "clear filters" button and the empty-state wording, which
        # should say something different when a search returned nothing than
        # when the catalogue is genuinely empty.
        'filters_active': bool(
            filters['q'] or filters['category'] or filters['subcategory']
            or filters.get('source')
            or filters.get('min_price') != '' or filters.get('max_price') != ''
        ),
        # Sidebar price inputs and sort dropdown.
        'filter_min_price': filters.get('min_price', ''),
        'filter_max_price': filters.get('max_price', ''),
        'filter_sort': filters.get('sort', ''),
        'filter_sort_options': [
            {'key': key, 'label': label, 'is_active': filters.get('sort') == key}
            for key, (_ordering, label) in CATALOG_SORTS.items()
        ],
    }


# =============================================================================
# PUBLIC CATALOGUE (no login) — the SEO surface
# =============================================================================
# These two views are the only product pages a search engine can reach. Everything
# under /portal/ is Disallowed in robots.txt (it is the authenticated area and
# duplicates the public marketing pages), so a catalogue mounted there could never
# be indexed no matter how good the markup was. They live at the root instead.
#
# BROWSING IS PUBLIC, ORDERING IS NOT. Anyone — including Googlebot — may read the
# listing and the detail pages. Adding to a cart still requires a customer login;
# the button becomes a "Sign in to order" link for anonymous visitors, and
# `add_to_cart` independently rejects them, so the UI is a convenience rather than
# the control.
# =============================================================================

PUBLIC_CATALOGUE_PAGE_SIZE = 24

# Products shown in the homepage shop window. Eight fills two rows of four on a
# desktop grid and one column of eight on a phone, without turning the landing
# page into the catalogue.
HOMEPAGE_PRODUCT_COUNT = 8


def _public_products():
    """
    The base queryset for everything a stranger may see.

    Drafts are unreviewed scrapes and private products are deliberately withheld,
    so neither belongs in a public, indexable listing.
    """
    return (
        Product.objects
        .filter(is_draft=False, is_private=False)
        .select_related('category', 'subcategory')
        .prefetch_related('images', 'variants')
    )


def shop_index(request):
    """
    The public marketplace: a filterable, paginated, indexable product grid.

    Args:
        request (HttpRequest): Anonymous or authenticated. Supports the catalogue
            filters (q, category, subcategory, min_price, max_price, sort) plus
            `page`.

    Returns:
        HttpResponse: The rendered catalogue.
    """
    settings = CompanySettings.get_settings()
    filters = _parse_catalog_filters(request)

    scope = _public_products()
    filter_context = _build_filter_context(scope, filters)
    products_qs = _apply_catalog_filters(scope, filters)
    if not filters['sort']:
        # Default order: newest first, so a fresh import is the first thing both a
        # returning visitor and a re-crawl see.
        products_qs = products_qs.order_by('-id')

    paginator = Paginator(products_qs, PUBLIC_CATALOGUE_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Only logged-in customers have a cart, so only they need the "already in
    # cart" state. An anonymous visitor gets an empty set and no extra query.
    cart_product_ids = set()
    customer = getattr(getattr(request.user, 'profile', None), 'customer', None) \
        if request.user.is_authenticated else None
    if customer is not None:
        cart_product_ids = set(
            CartItem.objects.filter(customer=customer).values_list('product_id', flat=True)
        )

    products_data = []
    for p in page_obj.object_list:
        cbm = None
        if p.carton_length and p.carton_width and p.carton_height:
            cbm = round(float(p.carton_length) * float(p.carton_width)
                        * float(p.carton_height) / 1_000_000, 4)
        products_data.append({
            'product': p,
            'cbm': cbm,
            'first_image': p.primary_image,
            'in_cart': p.id in cart_product_ids,
        })

    return render(request, 'portal/shop_index.html', {
        'settings': settings,
        'products_data': products_data,
        'page_obj': page_obj,
        'paginator': paginator,
        'result_count': paginator.count,
        'is_customer': customer is not None,
        'canonical_path': request.path,
        **filter_context,
    })


def shop_product_detail(request, slug):
    """
    A single product, publicly readable and marked up for search engines.

    Args:
        request (HttpRequest): Anonymous or authenticated.
        slug (str): The product's URL slug.

    Returns:
        HttpResponse: The rendered product page.

    Raises:
        Http404: For a draft, a private product, or an unknown slug — all three
            give the same answer, so the page cannot be used to confirm that a
            withheld product exists.
    """
    product = get_object_or_404(_public_products(), slug=slug)
    settings = CompanySettings.get_settings()

    cbm = None
    if product.carton_length and product.carton_width and product.carton_height:
        cbm = round(float(product.carton_length) * float(product.carton_width)
                    * float(product.carton_height) / 1_000_000, 4)

    customer = getattr(getattr(request.user, 'profile', None), 'customer', None) \
        if request.user.is_authenticated else None

    variants = product.active_variants
    price_span = product.price_range

    # Pre-select the CHEAPEST option, not whichever happens to be first in
    # display order. Product.display_price - the figure the catalogue card
    # headlines - is defined as the low end of the span, so a card reading
    # "FROM AED 20.51" used to open a page headlined 22.30: a price that appears
    # to have moved between the click and the page. It also made the figure
    # flicker, because the template rendered price_low and the script then
    # overwrote it with the checked variant's price on load.
    default_variant = min(
        (v for v in variants if v.price is not None),
        key=lambda v: v.price, default=None)

    # A handful of siblings, so the page has somewhere to send a visitor who is
    # not convinced — and so it is not a crawl dead end.
    related_qs = _public_products().exclude(pk=product.pk)
    if product.category_id:
        related_qs = related_qs.filter(category=product.category)
    # Shaped exactly like the listing's rows so the same card partial renders it.
    related = [
        {'product': p, 'first_image': p.primary_image, 'cbm': None, 'in_cart': False}
        for p in related_qs[:4]
    ]

    return render(request, 'portal/shop_product_detail.html', {
        'settings': settings,
        'product': product,
        'images': product.displayable_images,
        'attributes': list(product.attributes.all()),
        'variants': variants,
        'default_variant_id': default_variant.id if default_variant else None,
        'price_low': price_span[0] if price_span else None,
        'price_high': price_span[1] if price_span else None,
        'cbm': cbm,
        'related': related,
        'is_customer': customer is not None,
        'in_cart': (
            CartItem.objects.filter(customer=customer, product=product).exists()
            if customer else False
        ),
        # Absolute, because Facebook fetches this URL server-side and a share
        # sheet passes it to another app — neither can resolve a relative path.
        'share_url': f'{settings.base_url}{product.get_absolute_url()}',
        # The full message: product name, the marketplaces served, a number to
        # reply to, then the link. Composed server-side so the copy and the
        # share-sheet paths cannot drift apart, and so the wording stays editable
        # in Settings rather than baked into a template.
        'share_text': settings.build_share_message(
            product.name, f'{settings.base_url}{product.get_absolute_url()}'
        ),
    })


@customer_login_required
def customer_products(request):
    """
    Displays all products assigned to the logged-in customer.
    
    Args:
        request (HttpRequest): The incoming request with request.customer set.
    
    Returns:
        HttpResponse: A rendered HTML page showing the customer's product catalog.
    
    Business Logic:
        In this logistics platform, not all customers see the same product catalog.
        Admins assign specific products to each customer (via CustomerProduct).
        This view shows the customer only their assigned products, along with
        useful logistics data like CBM (cubic meter) calculations for carton sizing,
        which helps customers plan container space.
    """
    customer = request.customer
    
    # Fetch all CustomerProduct assignments for this customer, eager-loading the
    # related Product and its images. select_related('product') joins the Product
    # table; prefetch_related('product__images') fetches all images in one query.
    assigned = customer.assigned_products.select_related(
        'product', 'product__category', 'product__subcategory'
    ).prefetch_related('product__images', 'product__variants').order_by('-assigned_at')

    # Counts in the filter bar come from the customer's full assigned catalogue,
    # not the filtered view — see _build_filter_context.
    filters = _parse_catalog_filters(request)
    filter_context = _build_filter_context(assigned, filters, prefix='product__')
    assigned = _apply_catalog_filters(assigned, filters, prefix='product__')

    settings = CompanySettings.get_settings()

    # IDs of products already in the customer's cart, used to disable "Add to Cart" buttons.
    cart_product_ids = set(
        CartItem.objects.filter(customer=customer).values_list('product_id', flat=True)
    )
    
    # Build a list of enriched product dictionaries for the template.
    # We add the CBM (cubic meter) calculation and the first image to each item.
    products_data = []
    for cp in assigned:
        p = cp.product  # The actual Product model instance.
        
        # Calculate CBM (cubic meters) for the carton if all dimensions are available.
        # CBM = (length * width * height) / 1,000,000 because dimensions are in mm
        # and we need the result in cubic meters (m³). This helps customers and
        # warehouse staff estimate container/vessel space requirements.
        cbm = None
        if p.carton_length and p.carton_width and p.carton_height:
            cbm = round(float(p.carton_length) * float(p.carton_width) * float(p.carton_height) / 1_000_000, 4)
        
        # Append a dictionary with the assignment, product, CBM, and first image.
        # The template uses this to render a product card with photo, specs, and CBM.
        products_data.append({
            'assignment': cp,            # The CustomerProduct record (for notes, etc.)
            'product': p,                # The Product record (name, price, SKU, etc.)
            'cbm': cbm,                  # Calculated cubic meter value (or None)
            'first_image': p.primary_image,  # First image for the thumbnail
            'in_cart': p.id in cart_product_ids,
        })
    
    return render(request, 'portal/products.html', {
        'customer': customer,
        'products_data': products_data,
        'settings': settings,
        'result_count': len(products_data),
        **filter_context,
    })


def customer_amazon_products(request):
    """
    Retired — permanently redirects to the public catalogue.

    These three pages split one catalogue by `source`, which is 'general' on
    every product the sourcing extension imports — so two of them were always
    empty and the third duplicated /shop/. They are no longer linked anywhere;
    this keeps old bookmarks and any indexed URL landing somewhere useful.

    A 301 rather than a 302: the move is permanent, and it tells Google to
    transfer whatever ranking these URLs had to the catalogue instead of
    keeping them in the index as duplicates.
    """
    return redirect(f'{reverse('shop_index')}?source=amazon', permanent=True)


def customer_noon_products(request):
    """
    Retired — permanently redirects to the public catalogue.

    These three pages split one catalogue by `source`, which is 'general' on
    every product the sourcing extension imports — so two of them were always
    empty and the third duplicated /shop/. They are no longer linked anywhere;
    this keeps old bookmarks and any indexed URL landing somewhere useful.

    A 301 rather than a 302: the move is permanent, and it tells Google to
    transfer whatever ranking these URLs had to the catalogue instead of
    keeping them in the index as duplicates.
    """
    return redirect(f'{reverse('shop_index')}?source=noon', permanent=True)


def customer_marketplace(request):
    """
    Retired — permanently redirects to the public catalogue.

    These three pages split one catalogue by `source`, which is 'general' on
    every product the sourcing extension imports — so two of them were always
    empty and the third duplicated /shop/. They are no longer linked anywhere;
    this keeps old bookmarks and any indexed URL landing somewhere useful.

    A 301 rather than a 302: the move is permanent, and it tells Google to
    transfer whatever ranking these URLs had to the catalogue instead of
    keeping them in the index as duplicates.
    """
    return redirect(f'{reverse('shop_index')}', permanent=True)


@customer_login_required
def customer_product_detail(request, product_id):
    """
    One product in full: gallery, pricing, carton/shipping specs, and the free-form
    attribute list staff maintain on it.

    Args:
        request (HttpRequest): Must belong to a logged-in customer.
        product_id (int): Primary key of the product to show.

    Returns:
        HttpResponse: The rendered detail page.

    Raises:
        Http404: If this customer may not see this product.

    Business Logic:
        The cards in the catalogue only have room for a name, a price and an MOQ,
        so anything a buyer actually decides on — dimensions, material, model
        number, what is in the box — had nowhere to live. This page is where the
        attributes go.

        VISIBILITY mirrors the listing pages exactly, so nothing becomes reachable
        here that was not already reachable by browsing:

          - A product ASSIGNED to this customer is visible, matching
            ``customer_products``. That includes drafts and private products,
            because assignment is a deliberate act by staff.
          - Anything else must be published and public (``is_draft=False`` and
            ``is_private=False``), matching the marketplace and source lists.

        Supplier information is deliberately absent from the template. ``source_url``
        is where the goods are bought, and showing a customer the factory is showing
        them how to skip us.
    """
    from django.http import Http404

    customer = request.customer

    product = (
        Product.objects
        .select_related('category', 'subcategory')
        .prefetch_related('images', 'attributes', 'variants')
        .filter(id=product_id)
        .first()
    )
    if product is None:
        raise Http404('No such product.')

    assignment = (
        CustomerProduct.objects
        .filter(customer=customer, product=product)
        .select_related('product')
        .first()
    )
    if assignment is None and (product.is_draft or product.is_private):
        # Same answer as a product that does not exist: confirming that a private
        # product exists tells the asker something they should not learn.
        raise Http404('No such product.')

    # Carton volume in m³, the figure customers plan container space with. Carton
    # dimensions are in CM, so the divisor is 1,000,000.
    cbm = None
    if product.carton_length and product.carton_width and product.carton_height:
        cbm = round(
            float(product.carton_length) * float(product.carton_width)
            * float(product.carton_height) / 1_000_000,
            4,
        )

    variants = product.active_variants
    price_span = product.price_range

    # The PUBLIC url, not this page's. Sharing a /portal/ link would send the
    # recipient to a login screen; the shop page is the shareable one. Empty for
    # drafts and private products, which 404 publicly — offering to share a link
    # that dead-ends is worse than offering nothing.
    company_settings = CompanySettings.get_settings()
    share_url = (
        f'{company_settings.base_url}{product.get_absolute_url()}'
        if not (product.is_draft or product.is_private) else ''
    )

    return render(request, 'portal/product_detail.html', {
        'customer': customer,
        'settings': company_settings,
        'product': product,
        'assignment': assignment,
        'images': product.displayable_images,
        'attributes': list(product.attributes.all()),
        'variants': variants,
        # Pre-computed rather than called from the template: Django templates
        # cannot unpack a tuple, and price_range would otherwise run twice.
        'price_low': price_span[0] if price_span else None,
        'price_high': price_span[1] if price_span else None,
        'cbm': cbm,
        'in_cart': CartItem.objects.filter(customer=customer, product=product).exists(),
        # The PUBLIC url, not this page's. Sharing a /portal/ link would send the
        # recipient to a login screen; the shop page is the shareable one.
        'share_url': share_url,
        # Empty alongside an empty share_url: the buttons are not rendered at all
        # for a draft or private product, so there is nothing to compose.
        'share_text': (
            company_settings.build_share_message(product.name, share_url)
            if share_url else ''
        ),
        # Only orderable products get an add-to-cart button; add_to_cart itself
        # re-checks this, so the button is a courtesy rather than the guard.
        'can_add_to_cart': not product.is_draft,
    })


def _get_cart_items(request):
    """
    Return the cart items for the current logged-in customer.

    Args:
        request (HttpRequest): The incoming request with request.customer set.

    Returns:
        QuerySet: CartItem queryset for the customer, prefetched with product and images.
    """
    return CartItem.objects.filter(customer=request.customer).select_related('product', 'variant').prefetch_related('product__images')


def _cart_total(items):
    """Calculate the total cart value from a list/QuerySet of CartItem objects."""
    return sum((item.subtotal for item in items), Decimal('0'))


def _currency_totals(items, settings):
    """
    Return a dict of approximate cart totals in supported currencies.

    Uses CompanySettings fx_rates to convert the base-currency total.
    """
    if not items:
        return {}
    base_total = _cart_total(items)
    totals = {settings.currency: base_total}
    for cur, rate in (settings.fx_rates or {}).items():
        try:
            totals[cur] = (base_total * Decimal(str(rate))).quantize(Decimal('0.01'))
        except Exception:
            continue
    return totals


@customer_login_required
def add_to_cart(request):
    """
    AJAX endpoint: Add a product to the customer's cart.

    Expects POST data:
        product_id (int): The product to add.
        quantity (int, optional): Quantity to add. Defaults to 1 or the product MOQ.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...', 'cart_count': N}
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})

    product_id = request.POST.get('product_id')
    quantity = request.POST.get('quantity', '1')
    variant_id = (request.POST.get('variant_id') or '').strip()

    try:
        product = Product.objects.get(id=product_id, is_draft=False)
    except (Product.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Product not found.'})

    # A private product may only be added by a customer it was assigned to.
    #
    # customer_product_detail has always enforced this; this endpoint did not, so
    # posting a guessed product_id put another customer's private product in your
    # cart - and the reply named it, which leaked the product name on its own.
    # Ids are sequential, so that was a loop over integers.
    #
    # The message is deliberately the SAME "Product not found." used for an id
    # that does not exist. Saying "you are not allowed to order this" would
    # confirm the product is real, which is the thing being protected - the same
    # reasoning as the 404 in customer_product_detail.
    if product.is_private and not CustomerProduct.objects.filter(
        customer=request.customer, product=product
    ).exists():
        return JsonResponse({'success': False, 'message': 'Product not found.'})

    # Which variation, for products that sell several. Looked up scoped to this
    # product so an id belonging to a different product cannot be attached here.
    variant = None
    if variant_id:
        variant = product.variants.filter(id=variant_id, is_active=True).first()
        if variant is None:
            return JsonResponse({'success': False, 'message': 'That option is no longer available.'})
    elif product.has_variants:
        # Every variation has its own price, so an order line with no variation
        # named does not say what was bought or what it costs.
        return JsonResponse({'success': False, 'message': 'Please choose an option first.'})

    try:
        quantity = int(quantity)
    except (ValueError, TypeError):
        quantity = 1

    if quantity < product.moq:
        quantity = product.moq

    # Keyed on the variation as well as the product: two variations of one product
    # are two lines, because they are different things at different prices.
    cart_item, created = CartItem.objects.get_or_create(
        customer=request.customer,
        product=product,
        variant=variant,
        defaults={'quantity': quantity},
    )
    if not created:
        cart_item.quantity += quantity
        cart_item.save(update_fields=['quantity'])

    label = f'{product.name} — {variant.name}' if variant else product.name
    cart_count = CartItem.objects.filter(customer=request.customer).count()

    # Ad-platform tracking payload, built HERE rather than in JavaScript.
    #
    # The price has to come from the database, not from parsing the rendered
    # card: a variation's price differs from its parent's, the DOM shows a
    # "from" figure for multi-variation products, and a mis-read value teaches
    # Meta and TikTok to bid for the wrong basket size. content_id is the primary
    # key, which is what the product feed exports, so catalogue and dynamic
    # retargeting ads have something to join on.
    unit_price = variant.price if (variant and variant.price is not None) else product.price
    return JsonResponse({
        'success': True,
        'message': f'Added {label} to cart.',
        'cart_count': cart_count,
        'tracking': {
            'content_ids': [str(product.id)],
            'content_name': label,
            'content_type': 'product',
            'quantity': quantity,
            'unit_price': float(unit_price),
            'value': round(float(unit_price) * quantity, 2),
        },
    })


@customer_login_required
def cart_view(request):
    """
    Display the customer's shopping cart.

    Returns:
        HttpResponse: Rendered cart.html with cart items, totals, and currency conversions.
    """
    customer = request.customer
    items = _get_cart_items(request)
    settings = CompanySettings.get_settings()
    cart_total = _cart_total(items)
    currency_totals = _currency_totals(items, settings)

    return render(request, 'portal/cart.html', {
        'customer': customer,
        'items': items,
        'cart_total': cart_total,
        'currency_totals': currency_totals,
        'settings': settings,
    })


@customer_login_required
def remove_from_cart(request, item_id):
    """
    Remove a cart item.

    Args:
        request (HttpRequest): The incoming request.
        item_id (int): The CartItem primary key to remove.

    Returns:
        HttpResponse: Redirect back to the cart page.
    """
    CartItem.objects.filter(id=item_id, customer=request.customer).delete()
    return redirect('portal_cart')


@customer_login_required
def update_cart_quantity(request, item_id):
    """
    AJAX endpoint: Update the quantity of a cart item.

    Expects POST data:
        quantity (int): The new quantity.

    Returns:
        JsonResponse: Updated subtotal, cart total, and optional removal flag.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})

    try:
        quantity = int(request.POST.get('quantity', 1))
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Invalid quantity.'})

    try:
        item = CartItem.objects.select_related('product').get(id=item_id, customer=request.customer)
    except CartItem.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Item not found.'})

    if quantity < 1:
        item.delete()
        return JsonResponse({
            'success': True,
            'removed': True,
            'message': 'Item removed.',
            'cart_total': str(_cart_total(_get_cart_items(request))),
        })

    # Enforce MOQ
    if quantity < item.product.moq:
        quantity = item.product.moq

    item.quantity = quantity
    item.save(update_fields=['quantity'])

    return JsonResponse({
        'success': True,
        'removed': False,
        'message': 'Quantity updated.',
        'subtotal': str(item.subtotal),
        'cart_total': str(_cart_total(_get_cart_items(request))),
    })


@customer_login_required
def checkout_view(request):
    """
    Display the checkout page.

    For ready-to-ship marketplace products (Amazon/Noon), the form collects
    shipping/carton label files and label text fields.

    Returns:
        HttpResponse: Rendered checkout.html.
    """
    customer = request.customer
    items = _get_cart_items(request)
    if not items:
        return redirect('portal_cart')

    settings = CompanySettings.get_settings()
    cart_total = _cart_total(items)
    currency_totals = _currency_totals(items, settings)
    ready_to_ship_items = [
        item for item in items
        if item.product.ready_to_ship and item.product.source in {'amazon', 'noon'}
    ]

    return render(request, 'portal/checkout.html', {
        'customer': customer,
        'items': items,
        'cart_total': cart_total,
        'currency_totals': currency_totals,
        'ready_to_ship_items': ready_to_ship_items,
        'settings': settings,
    })


@customer_login_required
def checkout_confirm(request):
    """
    Process the checkout form and create an Order from the cart.

    For ready-to-ship products, validates that shipping and carton labels/files
    are provided, stores them on the created OrderItem, and then clears the cart.

    Returns:
        JsonResponse or HttpResponse: Redirects to the order detail page on success.
    """
    if request.method != 'POST':
        return redirect('portal_checkout')

    customer = request.customer
    items = _get_cart_items(request)
    if not items:
        messages.error(request, 'Your cart is empty.')
        return redirect('portal_cart')

    settings = CompanySettings.get_settings()

    # Validate ready-to-ship label inputs.
    for item in items:
        product = item.product
        if product.ready_to_ship and product.source in {'amazon', 'noon'}:
            prefix = f'item_{item.id}'
            shipping_label = request.FILES.get(f'{prefix}_shipping_label')
            carton_label = request.FILES.get(f'{prefix}_carton_label')
            label_mark = request.POST.get(f'{prefix}_label_mark', '').strip()
            carton_mark = request.POST.get(f'{prefix}_carton_mark', '').strip()
            carton_asn = request.POST.get(f'{prefix}_carton_asn', '').strip()

            # Require at least the label files or text identifiers.
            if not shipping_label and not label_mark:
                messages.error(request, f'Please provide a shipping label or label mark for {product.name}.')
                return redirect('portal_checkout')
            if not carton_label and not carton_mark:
                messages.error(request, f'Please provide a carton label or carton mark for {product.name}.')
                return redirect('portal_checkout')

    # Collect the per-line label details this HTML form carries, then hand the
    # whole thing to the shared builder. The totals, the draft status, the frozen
    # prices and emptying the cart all live in portal/checkout.py so the API
    # creates orders exactly the same way — see the note at the top of that file.
    line_extras = {}
    for item in items:
        prefix = f'item_{item.id}'
        try:
            carton_quantity = int(request.POST.get(f'{prefix}_carton_quantity', 1) or 1)
        except (TypeError, ValueError):
            carton_quantity = 1
        line_extras[item.id] = {
            'label_mark': request.POST.get(f'{prefix}_label_mark', '').strip(),
            'carton_mark': request.POST.get(f'{prefix}_carton_mark', '').strip(),
            'carton_asn': request.POST.get(f'{prefix}_carton_asn', '').strip(),
            'carton_quantity': carton_quantity,
            'shipping_label': request.FILES.get(f'{prefix}_shipping_label'),
            'carton_label': request.FILES.get(f'{prefix}_carton_label'),
        }

    order = create_order_from_cart(customer, items, settings, line_extras)

    # Notify the customer via the order_status SMTP profile.
    try:
        from utils.email_utils import send_typed_email
        send_typed_email(
            email_type='order_status',
            subject=f'Order #{order.id} Received — {settings.company_name}',
            message=(
                f"Dear {customer.name},\n\n"
                f"We have received your order #{order.id}. Our team will review it, "
                f"calculate shipping costs, and update you shortly.\n\n"
                f"Total: {settings.currency} {order.total}\n\n"
                f"Best regards,\n{settings.company_name}"
            ),
            recipient_list=[customer.email],
            fail_silently=True,
        )
    except Exception:
        pass

    messages.success(request, f'Order #{order.id} placed successfully!')

    # Hand the order to WhatsApp.
    #
    # The customer lands on their order page, which opens the prefilled chat —
    # rather than redirecting straight to wa.me. Two reasons: a hard redirect
    # off-site loses the order confirmation entirely, and if WhatsApp is not
    # installed the customer is left staring at a broken page with no evidence
    # their order was placed. The order page carries the same link as a button,
    # so a blocked auto-open costs one tap rather than the whole handoff.
    # `placed=1` is what lets the order page fire the Purchase pixel EXACTLY
    # once. Firing it on every view of the order would re-count the same
    # revenue every time the customer opened it to check progress, which
    # inflates reported ROAS and teaches the ad platforms the wrong bid.
    if order.whatsapp_url(settings):
        return redirect(
            f"{reverse('portal_order_detail', args=[order.id])}?whatsapp=1&placed=1"
        )
    return redirect(
        f"{reverse('portal_order_detail', args=[order.id])}?placed=1"
    )


@customer_login_required
def customer_ledger(request):
    """
    Displays the customer's financial ledger with running balances per currency.
    
    Args:
        request (HttpRequest): The incoming request with request.customer set.
    
    Returns:
        HttpResponse: A rendered HTML page showing all ledger entries with a
                      running balance and a summary of current balances per currency.
    
    Business Logic:
        The ledger is the financial backbone of the customer relationship. It records
        every monetary transaction: credits (payments made by the customer) and debits
        (charges for orders, shipping, fees). Customers need transparency into their
        financial standing. This view shows each entry in chronological order with a
        running balance so the customer can trace how their balance evolved over time.
        Multi-currency support is included because international trade often involves
        multiple currencies (USD, EUR, local currency, etc.).
    """
    customer = request.customer
    from datetime import date as _date

    all_entries = LedgerEntry.objects.filter(customer=customer).order_by('date')

    # ------------------------------------------------------------------
    # Month filter. Default = the CURRENT month so the page opens on what
    # matters now; '?month=all' shows the complete history, and any past
    # month can be picked from the dropdown.
    # ------------------------------------------------------------------
    month_param = request.GET.get('month', '')
    today = _date.today()
    if not month_param:
        month_param = today.strftime('%Y-%m')

    selected_label = 'All history'
    month_start = None
    if month_param != 'all':
        try:
            y, m = int(month_param[:4]), int(month_param[5:7])
            month_start = _date(y, m, 1)
            next_start = _date(y + 1, 1, 1) if m == 12 else _date(y, m + 1, 1)
            selected_label = month_start.strftime('%B %Y')
        except (ValueError, IndexError):
            month_param = 'all'

    # Months that actually have entries, for the dropdown (newest first).
    available_months = [
        {'value': d.strftime('%Y-%m'), 'label': d.strftime('%B %Y')}
        for d in all_entries.datetimes('date', 'month', order='DESC')
    ]
    # Ensure the current month is offered even before its first entry exists.
    current_value = today.strftime('%Y-%m')
    if not any(mo['value'] == current_value for mo in available_months):
        available_months.insert(0, {'value': current_value, 'label': today.strftime('%B %Y')})

    # OVERALL balances (all time) — the headline numbers stay meaningful even
    # when a single month is displayed.
    currencies_used = all_entries.values_list('currency', flat=True).distinct()
    balances = {}
    for cur in currencies_used:
        credit = all_entries.filter(currency=cur, entry_type='credit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        debit = all_entries.filter(currency=cur, entry_type='debit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        balances[cur] = credit - debit

    # Filtered window + opening balances so the running column is correct even
    # when the view starts mid-history.
    if month_start is not None:
        entries = all_entries.filter(date__date__gte=month_start, date__date__lt=next_start)
        opening = {}
        prior = all_entries.filter(date__date__lt=month_start)
        for cur in prior.values_list('currency', flat=True).distinct():
            credit = prior.filter(currency=cur, entry_type='credit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
            debit = prior.filter(currency=cur, entry_type='debit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
            opening[cur] = credit - debit
    else:
        entries = all_entries
        opening = {}

    entries_with_running = []
    running = dict(opening)
    for entry in entries:
        cur = entry.currency
        running.setdefault(cur, Decimal('0'))
        if entry.entry_type == 'credit':
            running[cur] += entry.amount
        else:
            running[cur] -= entry.amount
        entries_with_running.append({'entry': entry, 'running': running.get(cur, Decimal('0'))})

    # ------------------------------------------------------------------
    # Excel statement export of exactly what is on screen (?export=xlsx).
    # ------------------------------------------------------------------
    if request.GET.get('export') == 'xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font
        import io as _io
        from django.http import HttpResponse as _HttpResponse

        wb = Workbook()
        ws = wb.active
        ws.title = 'Statement'
        ws.append([f'Ledger statement — {customer.name} — {selected_label}'])
        ws['A1'].font = Font(bold=True, size=13)
        ws.append([])
        ws.append(['Date', 'Type', 'Description', 'Currency', 'Amount', 'Running Balance'])
        for cell in ws[3]:
            cell.font = Font(bold=True)
        for row in entries_with_running:
            e = row['entry']
            ws.append([
                e.date.strftime('%Y-%m-%d %H:%M'),
                e.get_entry_type_display() if hasattr(e, 'get_entry_type_display') else e.entry_type,
                e.description,
                e.currency,
                float(e.amount),
                float(row['running']),
            ])
        ws.append([])
        for cur, bal in balances.items():
            ws.append(['', '', 'Overall balance', cur, '', float(bal)])
        for col, width in zip('ABCDEF', (18, 10, 50, 10, 14, 16)):
            ws.column_dimensions[col].width = width

        buf = _io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        resp = _HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        fname = f'ledger_{month_param}_{customer.id}.xlsx'
        resp['Content-Disposition'] = f'attachment; filename="{fname}"'
        return resp

    settings = CompanySettings.get_settings()

    return render(request, 'portal/ledger.html', {
        'customer': customer,
        'entries_with_running': entries_with_running,
        'balances': balances,
        'settings': settings,
        'available_months': available_months,
        'selected_month': month_param,
        'selected_label': selected_label,
        'opening_balances': opening,
    })


@customer_login_required
def customer_profile(request):
    """
    Handles viewing and updating the customer's profile information.
    
    Supports both GET (show the profile form) and POST (update via AJAX).
    
    Args:
        request (HttpRequest): The incoming request with request.customer set.
    
    Returns:
        HttpResponse (GET):  Rendered profile.html page with current customer data.
        JsonResponse (POST): JSON response confirming the update or reporting errors.
    
    Business Logic:
        Customers need to keep their contact details up to date (name, phone, address)
        so the logistics company can reach them about shipments, deliveries, and payments.
        This view also allows password changes, which is a critical security feature.
        The AJAX response means the frontend can show a success toast without reloading.
    """
    customer = request.customer
    
    if request.method == 'POST':
        # Update the customer's basic fields from the POST data.
        # The second argument to .get() is the fallback value if the field is missing.
        # This ensures that if a field is not submitted, the existing value is kept.
        customer.name = request.POST.get('name', customer.name)
        customer.phone = request.POST.get('phone', customer.phone)
        customer.address = request.POST.get('address', customer.address)
        
        # Handle password change. Only update if the new_password field is not empty.
        # An empty string means the user didn't want to change their password.
        # The current password must be provided and verified for security.
        new_password = request.POST.get('new_password', '').strip()
        current_password = request.POST.get('current_password', '').strip()
        if new_password:
            if not current_password:
                return JsonResponse({'success': False, 'message': 'Current password is required to change password.'})
            # Verify the current password against the Django User (the source of
            # truth for auth), falling back to the legacy Customer hash.
            if not request.user.check_password(current_password) and not customer.check_password(current_password):
                return JsonResponse({'success': False, 'message': 'Current password is incorrect.'})
            # Update BOTH the Django User (used for login) and the legacy Customer
            # hash (kept in sync during the transition) so the change takes effect.
            request.user.set_password(new_password)
            request.user.save(update_fields=['password'])
            customer.set_password(new_password)
            # Changing a user's password rotates the session hash; keep them logged in.
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)

        # Save all changes to the database in a single transaction.
        customer.save()
        
        # Return a JSON success response for the frontend to handle gracefully.
        return JsonResponse({'success': True, 'message': 'Profile updated successfully!'})
    
    # GET request: render the profile form with current customer data pre-filled.
    settings = CompanySettings.get_settings()
    return render(request, 'portal/profile.html', {
        'customer': customer,
        'settings': settings,
    })


# ==============================================================================
# SECTION 5: PRODUCT QUOTATION REQUESTS (Customer-Side)
# ==============================================================================
# These views allow customers to request quotes for products not yet in the
# catalog. A customer uploads product details, images, and a link; the admin
# reviews it and either converts it into a catalog product or rejects it.
# This feature bridges the gap between customer demand and catalog expansion.


@customer_login_required
def request_quote(request):
    """
    Allows a logged-in customer to submit a product quotation request with images.
    
    Supports both GET (show the form) and POST (process the submission via AJAX).
    
    Args:
        request (HttpRequest): The incoming request with request.customer set.
    
    Returns:
        HttpResponse (GET):  Rendered request_quote.html form page.
        JsonResponse (POST): JSON response confirming submission or reporting errors.
    
    Business Logic:
        In B2B logistics, customers often find products they want to source that are
        NOT yet in the company's catalog. Instead of emailing back and forth,
        the customer can use this form to submit a "Product Request" with images,
        descriptions, and a link to the source. The admin team reviews it, sources
        the product, sets pricing, and converts it into a catalog item — all tracked
        within the system. This streamlines the sourcing workflow and keeps records
        organized.
    """
    customer = request.customer
    
    if request.method == 'POST':
        # Extract form data submitted by the customer.
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        product_link = request.POST.get('product_link', '').strip()
        requested_quantity = request.POST.get('requested_quantity', '1')
        
        # Validate: product name is mandatory. The customer must at least identify
        # what product they want a quote for.
        if not name:
            return JsonResponse({'success': False, 'message': 'Product name is required.'})
        
        # Parse the requested quantity. If the user enters something invalid
        # (e.g., letters), we fall back to 1. The "or 1" handles the case where
        # int() returns 0 (which would be falsy).
        try:
            qty = int(requested_quantity) or 1
        except ValueError:
            qty = 1
        
        # Create the ProductRequest record in the database. Status is set to
        # 'pending' because the admin hasn't reviewed it yet. This record is the
        # central tracking object for this quotation workflow.
        pr = ProductRequest.objects.create(
            customer=customer,
            name=name,
            description=description,
            product_link=product_link or None,  # Store None if empty string.
            requested_quantity=qty,
            status='pending',
        )
        
        # Handle uploaded images. request.FILES.getlist('images') returns a list
        # of UploadedFile objects from the multipart form submission. The customer
        # can attach multiple images (e.g., product photos, spec sheets) to help
        # the admin identify and source the product.
        images = request.FILES.getlist('images')
        for img in images:
            # Each image is saved as a ProductRequestImage linked to the request.
            # uploaded_by='customer' tracks who uploaded it for audit purposes.
            ProductRequestImage.objects.create(
                request=pr,
                image=img,
                uploaded_by='customer',
            )
        
        # Return success JSON so the frontend can show a confirmation message
        # and optionally redirect the customer to their requests list.
        return JsonResponse({
            'success': True,
            'message': 'Request submitted successfully! Our team will review it shortly.'
        })
    
    # GET request: render the empty quotation request form.
    settings = CompanySettings.get_settings()
    return render(request, 'portal/request_quote.html', {
        'customer': customer,
        'settings': settings,
    })


@customer_login_required
def my_requests(request):
    """
    Lists all product quotation requests submitted by the logged-in customer.
    
    Args:
        request (HttpRequest): The incoming request with request.customer set.
    
    Returns:
        HttpResponse: A rendered HTML page showing the customer's request history.
    
    Business Logic:
        After submitting a quotation request, the customer wants to know the status:
        Is it still pending? Has it been quoted? Was it converted to a product?
        This view gives the customer full visibility into their request history.
        It also links to the converted product if the admin approved the request,
        so the customer can go straight to ordering.
    """
    customer = request.customer
    
    # Fetch all product requests for this customer. select_related('converted_product')
    # joins the Product table so the template can show the resulting product name
    # without an extra database query. Ordered by newest first.
    requests_list = customer.product_requests.select_related('converted_product').order_by('-created_at')
    
    settings = CompanySettings.get_settings()
    
    return render(request, 'portal/my_requests.html', {
        'customer': customer,
        'requests': requests_list,
        'settings': settings,
    })


# ==============================================================================
# SECTION 6: ADMIN CUSTOMER MANAGEMENT
# ==============================================================================
# These views are protected by Django's @login_required (staff auth).
# They allow the admin team to manage the customer database: view all customers,
# add new ones, edit existing records, and deactivate/delete accounts.
# Customer management is essential for onboarding, support, and account maintenance.


@module_required('customers')
def admin_customer_list(request):
    """
    Admin view: lists all customers in the system with statistics and search.
    
    Args:
        request (HttpRequest): The incoming request from a logged-in staff user.
    
    Returns:
        HttpResponse: A rendered HTML page with a searchable customer table and stats.
    
    Business Logic:
        The admin team needs a centralized view of all B2B customers. This page
        shows a searchable table (by name, email, or phone) and summary statistics:
        total customers, how many have portal access (email + password set), and
        how many are inactive. This helps the admin team monitor onboarding progress
        and identify customers who still need portal credentials set up.
    """
    # Get the search query from the URL's query string (e.g., ?q=John).
    # If no search term is provided, default to an empty string (show all).
    search = request.GET.get('q', '')
    
    # Start with all customers, ordered by newest first.
    customers = Customer.objects.all().order_by('-created_at')
    
    # If a search term was provided, filter the queryset by name, email, or phone.
    # The | operator chains OR conditions in Django ORM. __icontains means
    # case-insensitive partial match (e.g., "john" matches "Johnson").
    if search:
        customers = customers.filter(name__icontains=search) | customers.filter(email__icontains=search) | customers.filter(phone__icontains=search)
    
    # Calculate summary statistics for the dashboard cards at the top of the page.
    # total: all customers in the database (after search filtering).
    total = customers.count()
    
    # with_portal: customers who have both an email and a password set AND are active.
    # These are customers who can actually log in to the portal. This metric helps
    # the admin identify customers who still need portal credentials.
    with_portal = customers.filter(email__isnull=False, password__isnull=False, is_active=True).count()
    
    # inactive: customers who have been deactivated (is_active=False).
    # Admins may deactivate customers who are no longer doing business.
    inactive = customers.filter(is_active=False).count()
    
    settings = CompanySettings.get_settings()
    
    return render(request, 'portal/admin/customer_list.html', {
        'customers': customers,
        'search': search,
        'total': total,
        'with_portal': with_portal,
        'inactive': inactive,
        'settings': settings,
    })


@module_required('customers')
def admin_customer_add(request):
    """
    Admin view: creates a new customer record.
    
    Supports both GET (show the empty form) and POST (process the submission).
    
    Args:
        request (HttpRequest): The incoming request from a logged-in staff user.
    
    Returns:
        HttpResponse: A rendered form page or a redirect to the customer list.
    
    Business Logic:
        Admins can manually onboard new customers. This is useful when a customer
        calls or emails instead of self-registering. The admin can set all fields
        including an initial password. The customer can then log in immediately.
        This view also enforces validation (name, phone required) and uniqueness
        checks (email must not already exist).
    """
    if request.method == 'POST':
        # Collect form data from the admin's submission.
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip().lower()
        address = request.POST.get('address', '').strip()
        password = request.POST.get('password', '').strip()
        # Checkbox handling: HTML checkboxes send 'on' when checked, nothing when unchecked.
        is_active = request.POST.get('is_active') == 'on'
        
        # Validate required fields. Name and phone are the minimum needed to identify
        # a customer. Email is optional but recommended for portal access.
        if not name or not phone:
            messages.error(request, 'Name and phone are required.')
            return redirect('admin_customer_add')
        
        # Check for duplicate email. If the admin tries to create a customer with
        # an email already in use, we show an error and bounce back to the form.
        if email and Customer.objects.filter(email=email).exists():
            messages.error(request, 'A customer with this email already exists.')
            return redirect('admin_customer_add')
        
        # Create the customer. email is set to None if empty (for customers without email).
        customer = Customer.objects.create(
            name=name,
            phone=phone,
            email=email or None,
            address=address,
            is_active=is_active,
        )
        
        # If the admin provided a password, hash it and save.
        # If no password is set, the customer cannot log in yet (the admin can set it later).
        if password:
            customer.set_password(password)
            customer.save()

        # Create/link a Django User login so this customer can sign in through the
        # unified auth stack (only meaningful when they have an email).
        linked_user = sync_customer_user(customer, raw_password=password or None)
        # Admin-controlled 2FA policy for this customer's login.
        if linked_user is not None:
            linked_user.profile.two_factor_enabled = request.POST.get('two_factor_enabled') == 'on'
            linked_user.profile.save(update_fields=['two_factor_enabled'])

        # Show a success flash message and redirect to the customer list.
        # messages.success() stores the message in the session so it survives the redirect.
        from accounts.services import log_action
        log_action(request, 'customer.create', target=f'{name} <{email}>')
        messages.success(request, f'Customer "{name}" created successfully.')
        return redirect('admin_customer_list')
    
    # GET request: render the empty form. customer=None tells the template this is
    # an add operation (not an edit), so it won't pre-fill fields.
    settings = CompanySettings.get_settings()
    return render(request, 'portal/admin/customer_form.html', {
        'customer': None,
        'settings': settings,
    })


@module_required('customers')
def admin_customer_edit(request, customer_id):
    """
    Admin view: edits an existing customer's details.
    
    Supports both GET (show the pre-filled form) and POST (save changes).
    
    Args:
        request (HttpRequest): The incoming request from a logged-in staff user.
        customer_id (int): The primary key of the Customer to edit.
    
    Returns:
        HttpResponse: A rendered form page or a redirect to the customer list.
    
    Business Logic:
        Customer details change over time: phone numbers change, addresses move,
        passwords are forgotten. Admins need a way to update records on behalf
        of customers. This view also handles email change validation (ensuring the
        new email isn't already taken by another customer) and optional password resets.
    """
    # Fetch the customer or return a 404 if the ID doesn't exist.
    customer = get_object_or_404(Customer, id=customer_id)
    
    if request.method == 'POST':
        # Update fields from the submitted form data.
        customer.name = request.POST.get('name', '').strip()
        customer.phone = request.POST.get('phone', '').strip()
        new_email = request.POST.get('email', '').strip().lower()
        customer.address = request.POST.get('address', '').strip()
        customer.is_active = request.POST.get('is_active') == 'on'
        
        # If the email is being changed, validate uniqueness against OTHER customers.
        # We exclude the current customer from the check so saving without changing
        # the email doesn't trigger a false duplicate error.
        if new_email and new_email != customer.email:
            if Customer.objects.filter(email=new_email).exclude(id=customer.id).exists():
                messages.error(request, 'A customer with this email already exists.')
                return redirect('admin_customer_edit', customer_id=customer.id)
            customer.email = new_email or None
        
        # Handle password reset. If the admin fills in the password field, update it.
        # If left blank, the existing password is preserved.
        password = request.POST.get('password', '').strip()
        if password:
            customer.set_password(password)

        # Save all changes to the database.
        customer.save()

        # Keep the linked Django User login in sync (email, active state, and the
        # new password if one was set) so unified-auth login stays consistent.
        linked_user = sync_customer_user(customer, raw_password=password or None)
        # Admin-controlled 2FA policy for this customer's login.
        if linked_user is not None:
            linked_user.profile.two_factor_enabled = request.POST.get('two_factor_enabled') == 'on'
            linked_user.profile.save(update_fields=['two_factor_enabled'])

        from accounts.services import log_action
        log_action(request, 'customer.update', target=f'Customer #{customer.id} ({customer.name})')
        messages.success(request, f'Customer "{customer.name}" updated successfully.')
        return redirect('admin_customer_list')
    
    # GET request: render the form pre-filled with the customer's current data.
    settings = CompanySettings.get_settings()
    return render(request, 'portal/admin/customer_form.html', {
        'customer': customer,
        'settings': settings,
    })


@module_required('customers')
def admin_customer_delete(request, customer_id):
    """
    Admin view: deletes a customer from the database.
    
    Uses POST for deletion to prevent accidental deletion via GET requests
    (e.g., clicking a link or a bot crawling URLs).
    
    Args:
        request (HttpRequest): The incoming request from a logged-in staff user.
        customer_id (int): The primary key of the Customer to delete.
    
    Returns:
        HttpResponseRedirect: Redirects to the customer list after deletion.
    
    Business Logic:
        Sometimes a customer record needs to be permanently removed (e.g., a test
        account, a duplicate entry, or a customer who explicitly requested data deletion).
        Deleting a customer cascades to related records depending on the model's
        ForeignKey settings (on_delete). Admins must be careful because this operation
        is irreversible.
    """
    customer = get_object_or_404(Customer, id=customer_id)
    
    # Only perform deletion on POST. This is a security best practice:
    # GET requests should never modify data. Using POST ensures that a user
    # must intentionally submit a form (e.g., after a confirmation dialog).
    if request.method == 'POST':
        # Store the name before deletion so we can reference it in the success message.
        name = customer.name
        # Remove the linked Django User login first — deleting the Customer alone
        # would cascade away the Profile but leave an orphaned login behind.
        from accounts.services import delete_customer_user
        delete_customer_user(customer)
        customer.delete()
        from accounts.services import log_action
        log_action(request, 'customer.delete', target=name)
        messages.success(request, f'Customer "{name}" deleted successfully.')

    return redirect('admin_customer_list')


# ==============================================================================
# SECTION 7: ADMIN PRODUCT REQUEST MANAGEMENT
# ==============================================================================
# These views allow the admin team to review, manage, and act on customer
# product quotation requests. The admin can:
#   - See all pending/quoted/converted/rejected requests
#   - View request details and customer-submitted images
#   - Reject a request with notes
#   - Convert a request into a real catalog product (with specs, pricing, images)
#   - Upload additional images for record-keeping
# This is the core of the product sourcing workflow.


@module_required('customers')
def admin_request_list(request):
    """
    Admin view: lists all product quotation requests with status filtering.
    
    Args:
        request (HttpRequest): The incoming request from a logged-in staff user.
    
    Returns:
        HttpResponse: A rendered HTML page with a filterable request table and counts.
    
    Business Logic:
        The admin team needs a queue of all product requests to manage the sourcing
        workflow. This page shows requests with a status filter (pending, quoted,
        converted, rejected) and summary counts. It helps the admin prioritize
        work: pending requests need review, converted requests are already in the catalog.
    """
    # Get the status filter from the query string (e.g., ?status=pending).
    # If none provided, show all statuses.
    status_filter = request.GET.get('status', '')
    
    # Fetch all product requests with related customer and product data.
    # select_related('customer', 'converted_product') joins both tables so the
    # template can show customer name and converted product name without extra queries.
    requests_qs = ProductRequest.objects.select_related('customer', 'converted_product').order_by('-created_at')
    
    # Apply the status filter if one was provided in the URL.
    if status_filter:
        requests_qs = requests_qs.filter(status=status_filter)
    
    # Count requests by status for the filter tabs/dashboard.
    # These counts give the admin an instant overview of the pipeline.
    counts = {
        'pending': ProductRequest.objects.filter(status='pending').count(),
        'quoted': ProductRequest.objects.filter(status='quoted').count(),
        'converted': ProductRequest.objects.filter(status='converted').count(),
        'rejected': ProductRequest.objects.filter(status='rejected').count(),
    }
    
    settings = CompanySettings.get_settings()
    
    return render(request, 'portal/admin/request_list.html', {
        'requests': requests_qs,
        'status_filter': status_filter,
        'counts': counts,
        'settings': settings,
    })


@module_required('customers')
def admin_request_detail(request, request_id):
    """
    Admin view: displays a single product request and handles admin actions.
    
    Supports multiple actions via POST: reject, convert, update_notes, upload_images.
    
    Args:
        request (HttpRequest): The incoming request from a logged-in staff user.
        request_id (int): The primary key of the ProductRequest to manage.
    
    Returns:
        HttpResponse: A rendered detail page or a redirect after an action.
    
    Business Logic:
        This is the admin's workspace for reviewing a single product request.
        The admin can see customer-submitted images, descriptions, and links.
        Based on this, the admin decides:
          1. REJECT: The product cannot be sourced or is not viable.
          2. CONVERT: The product is viable. The admin creates a real Product in
             the catalog with full specs (SKU, price, weight, carton dimensions,
             MOQ, description). Images are transferred to the product. The product
             is assigned to the requesting customer so they can order it.
          3. UPDATE NOTES: Add internal notes or change status without converting.
          4. UPLOAD IMAGES: Add admin images (e.g., supplier photos, quality checks).
    """
    # Fetch the request with its related images eagerly loaded.
    # prefetch_related('images') fetches all images in one query so the template
    # can iterate over pr.images.all() efficiently.
    pr = get_object_or_404(ProductRequest.objects.prefetch_related('images'), id=request_id)
    
    if request.method == 'POST':
        # The 'action' field determines which sub-operation the admin is performing.
        action = request.POST.get('action', '')
        
        # ------------------------------------------------------------------
        # ACTION: REJECT
        # ------------------------------------------------------------------
        if action == 'reject':
            # Mark the request as rejected. The customer will see this status
            # on their "My Requests" page and know the product won't be sourced.
            pr.status = 'rejected'
            pr.admin_notes = request.POST.get('admin_notes', pr.admin_notes)
            pr.save()
            messages.success(request, 'Request rejected.')
            return redirect('admin_request_list')
        
        # ------------------------------------------------------------------
        # ACTION: CONVERT
        # ------------------------------------------------------------------
        # This is the most complex action: it creates a real Product in the catalog
        # from the customer's request. The admin enters pricing, logistics specs,
        # and then assigns the product to the customer so they can start ordering.
        elif action == 'convert':
            # Extract all product specification fields from the POST data.
            # Default values fall back to the request's original data if not provided.
            name = request.POST.get('product_name', pr.name).strip()
            sku = request.POST.get('sku', '').strip()
            price = request.POST.get('price', '0').strip()
            weight = request.POST.get('weight', '').strip()
            moq = request.POST.get('moq', '1').strip()
            carton_length = request.POST.get('carton_length', '').strip()
            carton_width = request.POST.get('carton_width', '').strip()
            carton_height = request.POST.get('carton_height', '').strip()
            carton_qty = request.POST.get('carton_qty', '').strip()
            description = request.POST.get('product_description', pr.description).strip()
            
            # Parse and validate numeric fields. We use try/except blocks because
            # Decimal() and int() will raise exceptions on invalid input.
            # Using Decimal for money and dimensions prevents floating-point errors.
            try:
                price_val = Decimal(price) if price else Decimal('0')
            except (InvalidOperation, ValueError, TypeError):
                price_val = Decimal('0')
            try:
                weight_val = Decimal(weight) if weight else None
            except (InvalidOperation, ValueError, TypeError):
                weight_val = None
            try:
                moq_val = int(moq) if moq else 1
            except (ValueError, TypeError):
                moq_val = 1
            try:
                # Carton dimensions and quantity are stored as Decimal/Int for precision.
                cl = Decimal(carton_length) if carton_length else None
                cw = Decimal(carton_width) if carton_width else None
                ch = Decimal(carton_height) if carton_height else None
                cq = int(carton_qty) if carton_qty else None
            except (InvalidOperation, ValueError, TypeError):
                cl = cw = ch = None
                cq = None
            
            # Create the new Product in the catalog. This product is now available
            # for orders and can be shown to other customers if the admin chooses.
            product = Product.objects.create(
                name=name,
                sku=sku or None,
                price=price_val,
                weight=weight_val,
                moq=moq_val,          # Minimum Order Quantity: smallest amount the customer can order.
                carton_length=cl,     # Carton dimensions in mm (for CBM and logistics planning).
                carton_width=cw,
                carton_height=ch,
                carton_qty=cq,        # Number of units per carton (for packing calculations).
                description=description,
            )
            
            # Transfer customer-submitted images to the new product. The customer
            # uploaded images to support their request; now those same images become
            # part of the product's gallery in the catalog.
            for req_img in pr.images.all():
                ProductImage.objects.create(
                    product=product,
                    image=req_img.image,
                )
            
            # Handle images uploaded by the admin during the conversion process.
            # These might be supplier photos, quality inspection photos, or better images.
            admin_images = request.FILES.getlist('admin_images')
            for img in admin_images:
                # Add to the product gallery.
                ProductImage.objects.create(product=product, image=img)
                # Also save a copy to the request record for audit/record-keeping.
                ProductRequestImage.objects.create(
                    request=pr,
                    image=img,
                    uploaded_by='admin',
                )
            
            # Assign the new product to the requesting customer via the CustomerProduct
            # junction table. This makes the product appear in the customer's
            # "My Products" page immediately so they can start placing orders.
            CustomerProduct.objects.create(
                customer=pr.customer,
                product=product,
                note=pr.admin_notes,  # Carry over admin notes as an assignment note.
            )
            
            # Update the request record to mark it as converted and link to the product.
            pr.status = 'converted'
            pr.converted_product = product  # ForeignKey to the newly created Product.
            pr.admin_notes = request.POST.get('admin_notes', pr.admin_notes)
            pr.save()
            
            messages.success(request, f'Product "{name}" created and assigned to {pr.customer.name}.')
            return redirect('admin_request_list')
        
        # ------------------------------------------------------------------
        # ACTION: UPDATE NOTES
        # ------------------------------------------------------------------
        elif action == 'update_notes':
            # Simple update: change the admin's internal notes and/or the status.
            # This is useful for intermediate steps (e.g., "quoted", "under review").
            pr.admin_notes = request.POST.get('admin_notes', '')
            pr.status = request.POST.get('status', pr.status)
            pr.save()
            messages.success(request, 'Request updated.')
            return redirect('admin_request_detail', request_id=pr.id)
        
        # ------------------------------------------------------------------
        # ACTION: UPLOAD IMAGES
        # ------------------------------------------------------------------
        elif action == 'upload_images':
            # Admin uploads additional images to the request record.
            # These are stored separately from product images and are for record-keeping.
            images = request.FILES.getlist('images')
            for img in images:
                ProductRequestImage.objects.create(
                    request=pr,
                    image=img,
                    uploaded_by='admin',
                )
            messages.success(request, f'{len(images)} image(s) uploaded.')
            return redirect('admin_request_detail', request_id=pr.id)
    
    # GET request: render the detail page with the request and its images.
    settings = CompanySettings.get_settings()
    return render(request, 'portal/admin/request_detail.html', {
        'pr': pr,
        'settings': settings,
    })


# ==============================================================================
# SECTION 8: PORTFOLIO (Public Showcase)
# ==============================================================================
# The portfolio is a public-facing gallery that showcases the company's work,
# capabilities, and success stories. It helps build trust with prospective
# customers and serves as marketing material.


def portfolio_page(request):
    """
    Renders the public portfolio page showing all active media items.
    
    Args:
        request (HttpRequest): The incoming HTTP request from any visitor.
    
    Returns:
        HttpResponse: A rendered HTML page with the portfolio gallery.
    
    Business Logic:
        The portfolio is the company's digital showcase. It displays images and
        videos of completed shipments, warehouse operations, and successful
        deliveries. Prospective customers visit this page to assess the company's
        scale and reliability before signing up. Only active items are shown
        to the public; inactive items are hidden (e.g., outdated or seasonal content).
    """
    # Fetch all active portfolio items. is_active=True ensures only approved
    # content is visible to the public. Admins control visibility via the admin panel.
    items = PortfolioItem.objects.filter(is_active=True)
    
    settings = CompanySettings.get_settings()
    
    # Try to identify the customer if they are logged in, so the navbar can show
    # their name and a logout link instead of "Login". This improves UX for
    # logged-in customers browsing the public site.
    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            pass
    
    return render(request, 'portal/portfolio.html', {
        'items': items,
        'settings': settings,
        'customer': customer,
    })


# ==============================================================================
# SECTION 9: ADMIN PORTFOLIO MANAGEMENT
# ==============================================================================
# These views allow staff to curate the public portfolio: add new items, edit
# existing ones, reorder them, and delete outdated content. Portfolio management
# is a marketing function that helps the company present a professional image.


@module_required('customers')
def admin_portfolio_list(request):
    """
    Admin view: lists all portfolio items for curation.
    
    Args:
        request (HttpRequest): The incoming request from a logged-in staff user.
    
    Returns:
        HttpResponse: A rendered HTML page with all portfolio items and counts.
    
    Business Logic:
        The admin team needs to manage the public portfolio efficiently. This page
        shows all items (active and inactive) sorted by display_order and creation date.
        It displays counts (active vs. total) so the admin knows how much content
        is currently public. From here, admins can add, edit, or delete items.
    """
    # Fetch all portfolio items, ordered by display_order ascending (for manual
    # sorting) and then by created_at descending (newest first as a tiebreaker).
    items = PortfolioItem.objects.all().order_by('display_order', '-created_at')
    
    # Count statistics for the dashboard cards.
    active_count = items.filter(is_active=True).count()
    total_count = items.count()
    
    settings = CompanySettings.get_settings()
    
    return render(request, 'portal/admin/portfolio_list.html', {
        'items': items,
        'active_count': active_count,
        'total_count': total_count,
        'settings': settings,
    })


@module_required('customers')
def admin_portfolio_add(request):
    """
    Admin view: adds a new item to the public portfolio.
    
    Supports both GET (show the form) and POST (save the new item).
    
    Args:
        request (HttpRequest): The incoming request from a logged-in staff user.
    
    Returns:
        HttpResponse: A rendered form page or a redirect to the portfolio list.
    
    Business Logic:
        The marketing team uploads new photos or videos of shipments, warehouses,
        or team events to showcase the company's operations. Each item has a title,
        description, media type (image or video), display order (for sorting), and
        an active flag. The display order controls the visual hierarchy on the public page.
    """
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        media_type = request.POST.get('media_type', 'image')
        display_order = request.POST.get('display_order', '0')
        is_active = request.POST.get('is_active') == 'on'
        # Fetch the uploaded file from the multipart form submission.
        file = request.FILES.get('file')
        
        # Validate: title is required so the item has a name in the gallery.
        if not title:
            messages.error(request, 'Title is required.')
            return redirect('admin_portfolio_add')
        
        # Validate: a file (image or video) is required for the portfolio item.
        if not file:
            messages.error(request, 'Please upload a file.')
            return redirect('admin_portfolio_add')
        
        # Parse the display order. This integer controls the sort position on the
        # public page. Lower numbers appear first. If parsing fails, default to 0.
        try:
            order = int(display_order)
        except ValueError:
            order = 0
        
        # Create the portfolio item. The file is automatically saved to the
        # configured media storage (e.g., local filesystem or S3) by Django's
        # FileField. The path is stored in the database; the file is stored on disk.
        PortfolioItem.objects.create(
            title=title,
            description=description,
            media_type=media_type,
            file=file,
            display_order=order,
            is_active=is_active,
        )
        
        messages.success(request, f'Portfolio item "{title}" added successfully.')
        return redirect('admin_portfolio_list')
    
    # GET request: render the empty form. item=None signals "add mode" to the template.
    settings = CompanySettings.get_settings()
    return render(request, 'portal/admin/portfolio_form.html', {
        'item': None,
        'settings': settings,
    })


@module_required('customers')
def admin_portfolio_edit(request, item_id):
    """
    Admin view: edits an existing portfolio item.
    
    Supports both GET (show the pre-filled form) and POST (save changes).
    
    Args:
        request (HttpRequest): The incoming request from a logged-in staff user.
        item_id (int): The primary key of the PortfolioItem to edit.
    
    Returns:
        HttpResponse: A rendered form page or a redirect to the portfolio list.
    
    Business Logic:
        Over time, portfolio items need updates: titles may be reworded, descriptions
        expanded, files replaced with better quality versions, or items deactivated
        when they become outdated. This view gives the admin full control over each
        item's metadata and visibility without deleting and re-creating it.
    """
    item = get_object_or_404(PortfolioItem, id=item_id)
    
    if request.method == 'POST':
        # Update text fields from the submitted form.
        item.title = request.POST.get('title', '').strip()
        item.description = request.POST.get('description', '').strip()
        item.media_type = request.POST.get('media_type', 'image')
        item.is_active = request.POST.get('is_active') == 'on'
        
        # Parse and update the display order. If invalid, default to 0.
        display_order = request.POST.get('display_order', '0')
        try:
            item.display_order = int(display_order)
        except ValueError:
            item.display_order = 0
        
        # Handle file replacement. If the admin uploaded a new file, replace the old one.
        # If no new file is provided, the existing file is preserved.
        new_file = request.FILES.get('file')
        if new_file:
            item.file = new_file
        
        # Save all changes to the database. Django's FileField handles the old file
        # cleanup if a new file is uploaded (depending on storage backend configuration).
        item.save()
        
        messages.success(request, f'Portfolio item "{item.title}" updated successfully.')
        return redirect('admin_portfolio_list')
    
    # GET request: render the form pre-filled with the existing item's data.
    settings = CompanySettings.get_settings()
    return render(request, 'portal/admin/portfolio_form.html', {
        'item': item,
        'settings': settings,
    })


@module_required('customers')
def admin_portfolio_delete(request, item_id):
    """
    Admin view: deletes a portfolio item.
    
    Uses POST to prevent accidental deletion via GET requests.
    
    Args:
        request (HttpRequest): The incoming request from a logged-in staff user.
        item_id (int): The primary key of the PortfolioItem to delete.
    
    Returns:
        HttpResponseRedirect: Redirects to the portfolio list after deletion.
    
    Business Logic:
        Outdated or incorrect portfolio items should be removed to keep the public
        gallery accurate and professional. Deleting the record also removes the
        associated file from storage (handled by Django's FileField on_delete
        behavior depending on the storage backend).
    """
    item = get_object_or_404(PortfolioItem, id=item_id)
    
    if request.method == 'POST':
        # Store the title before deletion for the success message.
        title = item.title
        item.delete()
        messages.success(request, f'Portfolio item "{title}" deleted successfully.')
    
    return redirect('admin_portfolio_list')


# ==============================================================================
# SECTION 10: NEW PUBLIC PAGES (About, Services, Contact)
# ==============================================================================
# These are standard corporate pages that provide information about the company.
# They are public (no login required) but still recognize logged-in customers
# so the navigation bar can be personalized.


def about_page(request):
    """
    Renders the public "About Us" page.
    
    Args:
        request (HttpRequest): The incoming HTTP request from any visitor.
    
    Returns:
        HttpResponse: A rendered HTML page with company history, mission, and team info.
    
    Business Logic:
        The About page builds trust and credibility. It tells the company's story,
        explains its logistics expertise, and reassures potential customers that they
        are dealing with an established, reliable partner. If a logged-in customer
        visits this page, they see their name in the navbar instead of a "Login" button.
    """
    settings = CompanySettings.get_settings()
    
    # Check if a customer is logged in so the navbar can be personalized.
    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            pass
    
    return render(request, 'portal/about.html', {
        'settings': settings,
        'customer': customer,
        # Only the people the owner has actually added and left active. When this
        # is empty the template omits the entire "Meet Our Team" section rather
        # than falling back to placeholder colleagues - see the note there.
        'team_members': TeamMember.objects.filter(is_active=True),
    })


def services_page(request):
    """
    Renders the public "Services" page.
    
    Args:
        request (HttpRequest): The incoming HTTP request from any visitor.
    
    Returns:
        HttpResponse: A rendered HTML page describing the company's logistics services.
    
    Business Logic:
        The Services page is a marketing tool that explains what the company offers:
        freight forwarding, warehousing, customs clearance, order management, etc.
        Prospective customers read this to understand if the company can meet their
        needs. As with other public pages, we try to recognize logged-in customers
        for a consistent navbar experience.
    """
    settings = CompanySettings.get_settings()
    
    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            pass
    
    return render(request, 'portal/services.html', {
        'settings': settings,
        'customer': customer,
    })


# ==============================================================================
# SHIPPING CALCULATOR (public)
# ==============================================================================

# How many lines one quote may contain.
#
# The form is a lead tool, not a manifest importer. A cap stops a crafted request
# from posting ten thousand lines and making the server do the work; anyone with
# a real consignment that size is a phone call, not a web form.
MAX_QUOTE_LINES = 20


def _quote_lines_from(payload):
    """
    Turn posted line data into the dicts the quoting module expects.

    Args:
        payload (dict): the decoded JSON body.

    Returns:
        tuple[list, list]: (lines, errors). Lines are only included when they
        carry enough information to price; errors are messages for the visitor.

    Validates here rather than in the quoting module so that the maths stays
    free of request handling and can be tested by passing plain numbers.
    """
    raw_lines = payload.get('lines')
    if not isinstance(raw_lines, list):
        return [], ['No product details were submitted.']

    lines, errors = [], []
    for index, raw in enumerate(raw_lines[:MAX_QUOTE_LINES], start=1):
        if not isinstance(raw, dict):
            continue

        def number(key):
            """One field as a Decimal, or None when it is absent or not a number."""
            value = raw.get(key)
            if value in (None, ''):
                return None
            try:
                parsed = Decimal(str(value).strip())
            except (InvalidOperation, ValueError, TypeError):
                return None
            # Negative dimensions are not a typo worth guessing at - a negative
            # height would silently produce a negative volume and undercharge.
            return parsed if parsed >= 0 else None

        length = number('length_cm')
        width = number('width_cm')
        height = number('height_cm')
        weight = number('weight_kg')
        quantity = number('quantity') or Decimal('1')

        # A line with nothing in it is a blank row the visitor never filled -
        # skipped silently, because complaining about empty optional rows is how
        # a form becomes annoying.
        if not any(v is not None and v > 0 for v in (length, width, height, weight)):
            continue

        if None in (length, width, height) or not all(v > 0 for v in (length, width, height)):
            errors.append(f'Item {index}: enter length, width and height in centimetres.')
            continue
        if weight is None or weight <= 0:
            errors.append(f'Item {index}: enter the weight of one carton in kilograms.')
            continue

        lines.append({
            'description': raw.get('description') or '',
            'length_cm': length,
            'width_cm': width,
            'height_cm': height,
            'weight_kg': weight,
            'quantity': max(1, int(quantity)),
        })

    if not lines and not errors:
        errors.append('Enter the dimensions and weight of at least one item.')
    return lines, errors


def shipping_calculator_page(request):
    """
    The public shipping calculator: dimensions in, a price out.

    GET renders the form. POST takes a JSON body and answers with a quote.

    Args:
        request (HttpRequest): from any visitor - no account needed.

    Returns:
        HttpResponse: the page, or a JsonResponse holding the quote.

    WHAT THE VISITOR IS TOLD, AND WHAT THEY ARE NOT

    They get one price: the cheapest of every forwarder that serves the route.
    They are NOT told which forwarder it came from, and the losing quotes are
    not returned at all - not merely hidden in the template, absent from the
    response, because anything in the JSON is public no matter what the page
    chooses to draw. Which carrier gives which rate is a negotiated supplier
    relationship, and the same reasoning keeps 1688 source links off customer
    pages.

    They are also told HOW the weight was arrived at. A customer quoted on
    volumetric weight who was only told a total assumes they have been
    overcharged; one who is shown that their carton is bulky rather than heavy
    can repack it and pay less. That is a better conversation.
    """
    settings = CompanySettings.get_settings()

    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            pass

    if request.method != 'POST':
        return render(request, 'portal/shipping_calculator.html', {
            'settings': settings,
            'customer': customer,
            'max_lines': MAX_QUOTE_LINES,
            # Both lists come from the database, so adding a country or a cargo
            # type is data entry rather than a code change.
            'destinations': ShippingDestination.objects.filter(is_active=True),
            'cargo_types': CargoType.objects.filter(
                is_active=True, customer_selectable=True),
        })

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'success': False, 'error': 'Could not read the submitted details.'}, status=400)

    method = str(payload.get('method') or 'sea').lower()
    if method not in ('air', 'sea'):
        return JsonResponse({'success': False, 'error': 'Choose air or sea freight.'}, status=400)

    destination = ShippingDestination.objects.filter(
        code=str(payload.get('destination') or '').upper(), is_active=True).first()
    if destination is None:
        return JsonResponse({'success': False, 'error': 'That destination is not served yet.'}, status=400)

    cargo_type = CargoType.objects.filter(
        slug=str(payload.get('cargo_type') or '').lower(),
        is_active=True, customer_selectable=True).first()
    if cargo_type is None:
        # Fall back to general goods rather than refusing: an unknown cargo type
        # is a stale bookmark or a retired category, not a reason to withhold a
        # price for the commonest case.
        cargo_type = CargoType.objects.filter(
            slug='general', is_active=True).first()
        if cargo_type is None:
            return JsonResponse({'success': False, 'error': 'No cargo types are configured.'}, status=400)

    lines, errors = _quote_lines_from(payload)
    if errors:
        return JsonResponse({'success': False, 'error': ' '.join(errors)}, status=400)

    rates = list(quoting.lane_rates(destination.code, cargo_type.slug, method))
    if not rates:
        # Nobody has a rate on file for this lane. Fall back to the global house
        # rate, which is what the site quoted before per-company rates existed.
        house = quoting.house_rate_row(settings, destination.code, cargo_type.slug, method)
        if house is not None:
            rates = [house]

    quotes = quoting.best_quote(rates, lines, settings)
    if not quotes:
        # No rate configured for this combination. Said plainly, with a route to
        # a human, rather than showing a confident 0.00.
        return JsonResponse({
            'success': False,
            'error': 'We do not have a published rate for that route yet. '
                     'Send us the details and we will quote it directly.',
            'needs_manual_quote': True,
        }, status=200)

    best = quotes[0]

    def money(value):
        """Decimals as strings - see the note on JSON number handling below."""
        return f'{value:.2f}'

    return JsonResponse({
        'success': True,
        # Every number is a STRING. JSON numbers are IEEE-754 doubles in every
        # browser, so a price sent as a number is re-parsed as binary floating
        # point and can render as 1234.5600000000001. Strings arrive as typed.
        'currency': settings.currency,
        'currency_symbol': settings.currency_symbol,
        'method': method,
        'destination': destination.code,
        'destination_label': destination.name,
        'cargo_type': cargo_type.slug,
        'cargo_type_label': cargo_type.name,
        'transit_days': best['transit_days'],
        'cartons': best['totals']['cartons'],
        'actual_kg': f"{best['actual_kg']:.3f}",
        'volumetric_kg': f"{best['volumetric_kg']:.3f}",
        'cbm': f"{best['cbm']:.3f}",
        'divisor': f"{best['divisor']:.0f}",
        'billed': f"{best['billed']:.3f}",
        'unit': best['unit'],
        'minimum_applied': best['minimum_applied'],
        'minimum': f"{best['minimum']:.3f}",
        'volumetric_applied': best['volumetric_applied'],
        'rate': money(best['rate']),
        'total': money(best['cost']),
        'quote_validity_days': settings.quote_validity_days,
    })


def _notify_admin_of_lead(lead):
    """
    Email the business as soon as a website enquiry arrives.

    Args:
        lead (ContactMessage): The submission that was just saved.

    Returns:
        int: Number of emails sent. 0 if no recipient is configured or SMTP fails.

    Business Logic:
        A lead is perishable. Someone comparing three sourcing agents will go with
        whoever answers first, so the gap between "enquiry submitted" and "someone
        knows about it" is the part of the funnel most worth shortening.

        The whole message is included in the body rather than a "you have a new
        enquiry, log in to read it" notice: the recipient is usually on a phone,
        and being able to read the requirement and reply from the mail client
        removes a step from the fastest possible response.

        Failures are swallowed. A misconfigured SMTP server must never turn into a
        500 on the public contact form — the enquiry is already safely saved, and
        it is visible in the back-office regardless of whether this email lands.
    """
    settings = CompanySettings.get_settings()

    # Prefer the dedicated security/ops mailbox, fall back to the order-status
    # sender. Both are configured under Settings → Email.
    # Configured recipients, falling back to the security/order-status sender when
    # "Send New Enquiry Alerts To" has not been filled in.
    recipients = settings.lead_notification_recipients
    if not recipients:
        return 0

    body = (
        f"New enquiry from the website\n"
        f"{'-' * 40}\n\n"
        f"Name:    {lead.name}\n"
        f"Email:   {lead.email}\n"
        f"Phone:   {lead.phone or '(not given)'}\n"
        f"Subject: {lead.subject or '(none)'}\n"
        f"Received: {lead.created_at.strftime('%d %b %Y, %H:%M')}\n\n"
        f"Message:\n{lead.message}\n\n"
        f"{'-' * 40}\n"
        f"Reply directly to this email to answer {lead.name}.\n"
        f"All enquiries: {settings.base_url}/portal/admin/leads/\n"
    )

    try:
        return send_typed_email(
            email_type='security',
            subject=f'New enquiry: {lead.name}' + (f' — {lead.subject}' if lead.subject else ''),
            message=body,
            recipient_list=recipients,
            # reply_to means hitting Reply in the mail client answers the customer
            # rather than the company's own address.
            reply_to=[lead.email] if lead.email else None,
            fail_silently=True,
        )
    except Exception:
        return 0


# =============================================================================
# ENQUIRY FORM SPAM DEFENCES
# =============================================================================

def antispam_field_name():
    """
    The honeypot's field name.

    Deliberately plausible: a bot that fills every input it finds will fill
    this one, while a real browser never shows it. Named for something an
    autofiller would recognise rather than something obviously a trap.
    """
    return 'company_website'


def _form_timestamp_value(request):
    """
    A signed timestamp to put in the form.

    Signed rather than a plain number so the value cannot simply be rewritten
    to claim the form was opened an hour ago. Carries no personal data - it is
    a clock reading and nothing else.
    """
    from django.core import signing

    return signing.dumps({'t': timezone.now().timestamp()}, salt='enquiry-form')


def _form_elapsed_seconds(request):
    """
    How long the form was open, in seconds.

    Returns:
        float | None: the elapsed time, or None when the field is missing or
        unreadable - in which case the timing signal is simply not used rather
        than being treated as suspicious. An older cached page, or a visitor
        with a browser extension that strips hidden inputs, must not be
        mistaken for a bot.
    """
    from django.core import signing

    raw = request.POST.get('form_started_at', '')
    if not raw:
        return None
    try:
        data = signing.loads(raw, salt='enquiry-form', max_age=60 * 60 * 12)
    except Exception:                                            # noqa: BLE001
        return None
    try:
        return max(0.0, timezone.now().timestamp() - float(data.get('t', 0)))
    except (TypeError, ValueError):
        return None


def contact_page(request):
    """
    Renders the public "Contact Us" page and handles contact form submissions.
    
    Supports both GET (show the form) and POST (process the submission).
    
    Args:
        request (HttpRequest): The incoming HTTP request from any visitor.
    
    Returns:
        HttpResponse: A rendered HTML page with the contact form, or a redirect
                      after successful submission.
    
    Business Logic:
        The contact page is the primary channel for prospective customers to reach
        the company. It collects name, email, phone, subject, and message, stores
        the submission as a ContactMessage for the admin to follow up, and sends
        the visitor to a dedicated thank-you page.

        Two behaviours here exist specifically to stop losing enquiries:

        1. On a validation failure the submitted values are handed back to the
           template so the form re-renders FILLED IN. The previous version
           re-rendered an empty form, so anyone who wrote a detailed product
           specification and forgot one field lost everything they had typed.
           That is the single most expensive kind of form bug: the visitor was
           motivated enough to write to you, and the site threw it away.

        2. A successful submission redirects to `contact_thank_you`, not back to
           this page. Redirect-after-POST prevents a browser refresh from
           re-submitting the enquiry, and a distinct URL gives the analytics
           tools a clean conversion event to count.
    """
    settings = CompanySettings.get_settings()

    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            pass

    # Values echoed back into the form. On GET these prefill from the logged-in
    # customer's own record where we have it — a returning customer should never
    # have to retype their own name and email.
    form_data = {
        # Customer.email is nullable, so coerce None to '' — a literal "None"
        # rendered into a value attribute is worse than an empty field.
        'name': customer.name if customer else '',
        'email': (customer.email or '') if customer else '',
        'phone': (customer.phone or '') if customer else '',
        'subject': '',
        'message': '',
    }
    field_errors = {}

    if request.method == 'POST':
        # Extract contact form fields from the POST data.
        form_data = {
            'name': request.POST.get('name', '').strip(),
            'email': request.POST.get('email', '').strip(),
            'phone': request.POST.get('phone', '').strip(),
            'subject': request.POST.get('subject', '').strip(),
            'message': request.POST.get('message', '').strip(),
        }

        # Validate required fields. Name, email, and message are mandatory;
        # phone and subject are optional. Errors are collected per-field rather
        # than as one banner so the template can mark the specific input that
        # needs attention instead of making the visitor hunt for it.
        if not form_data['name']:
            field_errors['name'] = 'Please tell us your name.'
        if not form_data['email']:
            field_errors['email'] = 'We need an email address to reply to you.'
        elif '@' not in form_data['email'] or '.' not in form_data['email'].split('@')[-1]:
            field_errors['email'] = 'That email address does not look right.'
        if not form_data['message']:
            field_errors['message'] = 'Tell us what you are looking to source.'

        # CAPTCHA. A wrong or missing answer is the one check here that blocks
        # the submission outright, because it is the one a person can simply
        # fix - unlike the spam score below, which only files the message away.
        # See portal/captcha.py for why this is self-hosted.
        if not captcha.verify(request.POST.get(captcha.TOKEN_FIELD),
                              request.POST.get(captcha.ANSWER_FIELD)):
            field_errors['captcha'] = ('That answer was not right, or the question expired. '
                                       'Please answer the new question below.')

        # The homepage sourcing form sends three extra fields. They are
        # appended to the message rather than dropped: ContactMessage has no
        # columns for them, and an enquiry that says only "I need chargers"
        # costs a round trip to ask what quantity and which country.
        #
        # Absent on the plain /contact/ form, where they simply stay empty.
        sourcing_detail = [
            (label, request.POST.get(field, '').strip())
            for field, label in (
                ('product_link', 'Product link'),
                ('quantity', 'Quantity needed'),
                ('destination', 'Ship to'),
            )
        ]
        extra = '\n'.join(f'{label}: {value}' for label, value in sourcing_detail if value)
        body = f"{form_data['message']}\n\n{extra}".strip() if extra else form_data['message']

        if field_errors:
            # A homepage submission that fails comes back on THIS page, which
            # has no link/quantity/destination inputs. Folding them into the
            # message keeps what the visitor typed instead of silently losing it.
            form_data['message'] = body

        if not field_errors:

            # --------------------------------------------------------------
            # SPAM SCORING
            # --------------------------------------------------------------
            # The form had no protection at all and was running at 84% spam —
            # 31 of 37 enquiries — each one also firing a notification email,
            # so the inbox meant to catch customers was mostly catching bots.
            #
            # Three inputs the visitor never sees: a honeypot field, how long
            # the form was open, and whether this exact text has arrived
            # before. See portal/antispam.py for why this is scored on the
            # server rather than behind a CAPTCHA.
            # --------------------------------------------------------------
            elapsed = _form_elapsed_seconds(request)
            score, reasons = antispam.score_submission(
                name=form_data['name'],
                email=form_data['email'],
                subject=form_data['subject'],
                message=body,
                elapsed_seconds=elapsed,
                honeypot=request.POST.get(antispam_field_name(), ''),
                recent_duplicate=antispam.is_duplicate(body),
            )
            flagged = score >= antispam.SPAM_THRESHOLD

            # Save the submission so it appears in the back-office lead list.
            lead = ContactMessage.objects.create(
                name=form_data['name'],
                email=form_data['email'],
                phone=form_data['phone'],
                subject=form_data['subject'],
                message=body,
                is_spam=flagged,
                spam_score=min(score, 255),
                spam_reason='; '.join(reasons)[:255],
            )

            # Tell someone. Until now a lead was saved silently and was only
            # visible in Django's stock /admin/ — a URL nobody has reason to open.
            # Enquiries could sit unread for days while the sender assumed they
            # had been ignored.
            #
            # Flagged messages skip this: the notification exists so a real
            # customer gets a fast reply, and an alert that fires for bots
            # trains people to ignore the alert.
            if not flagged:
                _notify_admin_of_lead(lead)

            # A flagged sender still sees the ordinary thank-you page. Telling a
            # bot it was caught just invites the operator to tune around the
            # filter, and a human wrongly flagged is not left staring at an
            # error for something they did nothing wrong.
            return redirect('contact_thank_you')

        messages.error(request, 'Almost there — please check the highlighted fields below.')

    return render(request, 'portal/contact.html', {
        'settings': settings,
        'customer': customer,
        'form_data': form_data,
        'field_errors': field_errors,
        # Spam defences. Rendered into the form; checked on submit.
        'antispam_field': antispam_field_name(),
        'form_started_at': _form_timestamp_value(request),
        # Always a NEW question, including after a failed attempt: each token
        # is single-use, so re-showing the old one could never be answered.
        'captcha': captcha.new_challenge(),
    })


def contact_thank_you(request):
    """
    Confirmation page shown after a successful enquiry.

    Args:
        request (HttpRequest): The incoming request.

    Returns:
        HttpResponse: The rendered thank-you page.

    Business Logic:
        Previously both public forms redirected back to the page they came from
        and showed a green banner. That cost three things at once:

          * No expectation was set. "We reply within 24 hours" is reassurance the
            visitor needs at exactly this moment.
          * The visitor had nowhere to go next, so a motivated lead hit a dead end.
          * There was no distinct URL, so neither GA4 nor Meta had a clean page to
            count as a conversion — you could see form submissions only as events,
            never as a destination.

        This page fixes all three. It is deliberately `noindex` (see the template):
        it holds no content anyone would search for, and a thank-you page showing
        up in search results means people land on it without having converted,
        which corrupts the very metric it exists to provide.
    """
    return render(request, 'portal/thank_you.html', {
        'settings': CompanySettings.get_settings(),
    })


def testimonials_page(request):
    """
    Renders the public "Testimonials" page with customer reviews and case studies.

    Args:
        request (HttpRequest): The incoming HTTP request from any visitor.

    Returns:
        HttpResponse: A rendered HTML page with testimonials and case studies.

    Business Logic:
        The Testimonials page showcases feedback from satisfied customers. It builds
        trust with prospective clients by showing real-world results and positive
        experiences. As with other public pages, we try to recognize logged-in customers
        for a consistent navbar experience.
    """
    settings = CompanySettings.get_settings()

    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            pass

    return render(request, 'portal/testimonials.html', {
        'settings': settings,
        'customer': customer,
    })


def faq_page(request):
    """
    Renders the public "FAQ" page with an accordion of common questions.

    Args:
        request (HttpRequest): The incoming HTTP request from any visitor.

    Returns:
        HttpResponse: A rendered HTML page with a Bootstrap accordion FAQ.

    Business Logic:
        An FAQ page reduces the sales team's workload by answering common questions
        upfront (pricing, shipping times, customs, etc.). It also improves SEO by
        targeting long-tail keywords that potential customers search for. As with
        other public pages, we try to recognize logged-in customers for a
        consistent navbar experience.
    """
    settings = CompanySettings.get_settings()

    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            pass

    return render(request, 'portal/faq.html', {
        'settings': settings,
        'customer': customer,
    })


# =============================================================================
# PUBLIC BLOG
# =============================================================================
# Two views: a paginated index (optionally filtered by category) and an article
# detail page. Both are open to anyone — the whole point is to be found in search
# by people who are not customers yet.
# =============================================================================


def blog_index(request):
    """
    Renders the blog index: a paginated list of published articles.

    Args:
        request (HttpRequest): The incoming request. Supports two query params —
                               `category` (a BlogCategory slug) and `page`.

    Returns:
        HttpResponse: The rendered blog listing.

    Business Logic:
        This is the hub page of the content cluster. It links out to every article
        and is itself the page most likely to rank for broad terms like "China
        sourcing blog". Drafts (is_published=False) are excluded so an unfinished
        article is never exposed by guessing the URL.
    """
    from .models import BlogPost, BlogCategory

    settings = CompanySettings.get_settings()

    posts = (
        BlogPost.objects
        .filter(is_published=True)
        .select_related('category')       # avoids one extra query per row for category.name
        .order_by('-published_at')
    )

    categories = BlogCategory.objects.all()

    # Optional category filter. An unknown slug yields an empty list rather than a
    # 404: the page still renders with its navigation, which is friendlier than an
    # error if a category is ever renamed or removed.
    active_category = None
    category_slug = request.GET.get('category', '').strip()
    if category_slug:
        active_category = categories.filter(slug=category_slug).first()
        posts = posts.filter(category__slug=category_slug)

    # Featured articles get a highlighted row at the top, but only on the
    # unfiltered first page — otherwise they would appear twice on the same screen.
    featured = []
    if not category_slug:
        featured = list(posts.filter(is_featured=True)[:3])

    paginator = Paginator(posts, 9)
    page_obj = paginator.get_page(request.GET.get('page'))

    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            pass

    return render(request, 'portal/blog_list.html', {
        'settings': settings,
        'customer': customer,
        'page_obj': page_obj,
        'posts': page_obj.object_list,
        'categories': categories,
        'active_category': active_category,
        'featured_posts': featured,
        'total_posts': paginator.count,
    })


def blog_detail(request, slug):
    """
    Renders a single blog article.

    Args:
        request (HttpRequest): The incoming request.
        slug (str): The article's URL slug, captured from the URL.

    Returns:
        HttpResponse: The rendered article page.

    Raises:
        Http404: If no published article has this slug.

    Business Logic:
        Unpublished drafts 404 rather than render, so a draft cannot leak by URL
        guessing or by being shared before it is ready.

        The page also surfaces up to three related articles — same category first,
        falling back to the most recent posts. Related links keep a reader on the
        site after they finish, which is both a ranking signal and the mechanism
        that moves someone from "researching" to "enquiring".
    """
    from .models import BlogPost

    settings = CompanySettings.get_settings()

    post = get_object_or_404(
        BlogPost.objects.select_related('category'),
        slug=slug,
        is_published=True,
    )

    related = list(
        BlogPost.objects
        .filter(is_published=True, category=post.category)
        .exclude(pk=post.pk)
        .order_by('-published_at')[:3]
    ) if post.category else []

    if len(related) < 3:
        # Top up with recent posts so the "keep reading" row is never half empty.
        exclude_ids = [post.pk] + [p.pk for p in related]
        related += list(
            BlogPost.objects
            .filter(is_published=True)
            .exclude(pk__in=exclude_ids)
            .order_by('-published_at')[:3 - len(related)]
        )

    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            pass

    return render(request, 'portal/blog_detail.html', {
        'settings': settings,
        'customer': customer,
        'post': post,
        'related_posts': related,
    })


# =============================================================================
# ARABIC LANDING PAGES
# =============================================================================
# The business sells to the UAE and the wider Middle East, and the site was
# English-only — no lang="ar", no dir="rtl", no hreflang anywhere. That closes off
# a segment of the market entirely, and it is a differentiator against every other
# China sourcing agent chasing the same buyers with an English-only site.
#
# These are hand-written translated pages rather than Django's i18n framework. The
# reason is deployment: gettext-based i18n needs `compilemessages`, which needs the
# GNU gettext binaries present on the server. On shared cPanel hosting those are
# frequently missing, and a missing binary at deploy time would mean broken pages.
# Two standalone templates carry no such dependency.
#
# If the Arabic side grows past a handful of pages, revisit this and move to
# proper i18n with .po files — at that point the duplication becomes the bigger
# cost.
# =============================================================================


def ar_home(request):
    """
    Arabic homepage at /ar/.

    Args:
        request (HttpRequest): The incoming request.

    Returns:
        HttpResponse: The rendered right-to-left Arabic homepage.
    """
    return render(request, 'portal/ar/home.html', {
        'settings': CompanySettings.get_settings(),
        # The Arabic hero form posts to contact_page like the English one, so it
        # carries the same defences.
        'antispam_field': antispam_field_name(),
        'form_started_at': _form_timestamp_value(request),
        'captcha': captcha.new_challenge(),
    })


def ar_services_page(request):
    """
    Arabic services page at /ar/services/.

    Args:
        request (HttpRequest): The incoming request.

    Returns:
        HttpResponse: The rendered right-to-left Arabic services page.
    """
    return render(request, 'portal/ar/services.html', {
        'settings': CompanySettings.get_settings(),
    })


def favicon_ico(request):
    """
    Redirects the root /favicon.ico request to the real icon in static files.

    Args:
        request (HttpRequest): The incoming request (unused).

    Returns:
        HttpResponsePermanentRedirect: 301 to the hashed static URL of the icon.

    Business Logic:
        Browsers, crawlers and link-preview bots request /favicon.ico from the
        site root whatever the page markup says. Without this route each of those
        requests rendered a full 404 page.

        The URL is resolved at request time rather than at import time on purpose:
        production uses WhiteNoise's ManifestStaticFilesStorage, whose url() reads
        the staticfiles manifest. Resolving it while the URLConf is being imported
        would blow up on any environment where collectstatic has not run yet.
    """
    from django.contrib.staticfiles.storage import staticfiles_storage
    from django.shortcuts import redirect
    return redirect(staticfiles_storage.url('images/favicon.ico'), permanent=True)


def robots_txt(request):
    """
    Renders a robots.txt file for search engine crawlers.

    Args:
        request (HttpRequest): The incoming HTTP request from any visitor.

    Returns:
        HttpResponse: A text/plain response containing robots.txt directives.

    Business Logic:
        robots.txt tells search engines which pages they can and cannot crawl.
        Everything behind a login is disallowed: those URLs return a redirect to
        the login page for a crawler, so letting Google spend its crawl budget on
        them buys nothing and can surface login screens in search results.

        Two things worth understanding about this file:

        1. robots.txt controls CRAWLING, not INDEXING. A disallowed URL that is
           linked from elsewhere can still appear in results as a bare URL with no
           description. Anything that must never be indexed needs the
           `<meta name="robots" content="noindex">` tag on the page itself — which
           is why the auth templates carry one.

        2. The /media/ and /static/ directories must stay crawlable. Google renders
           pages before ranking them; blocking CSS, JS and images makes the site
           look broken to the renderer and costs mobile-usability signals. The
           earlier version of this file blocked /media/, hiding every product and
           portfolio image from Google Images.
    """
    from django.http import HttpResponse
    lines = [
        'User-agent: *',
        '',
        '# Back-office and authenticated areas — nothing here is useful to a crawler.',
        'Disallow: /admin/',
        'Disallow: /dashboard/',
        'Disallow: /accounts/',
        'Disallow: /support/',
        'Disallow: /products/',
        'Disallow: /customers/',
        'Disallow: /orders/',
        'Disallow: /khata/',
        'Disallow: /noon-labels/',
        'Disallow: /settings/',
        '',
        '# Customer portal. The public marketing pages are also mounted at the root',
        '# (/about/, /services/, ...) and those root URLs are the canonical ones, so',
        '# blocking /portal/ removes the duplicate copies from the index.',
        'Disallow: /portal/',
        '',
        '# Session-specific pages: no shared content, and crawling them just burns',
        '# crawl budget on redirects.',
        'Disallow: /*?next=',
        '',
        '# Images and assets MUST stay crawlable so Google can render pages properly',
        '# and index product/portfolio photos in Google Images.',
        'Allow: /media/',
        'Allow: /static/',
        '',
        '# Public marketing pages, the blog, and the product catalogue.',
        'Allow: /',
        'Allow: /blog/',
        'Allow: /shop/',
        '',
        '# Filtered and sorted catalogue views are the same products in a',
        '# different order. Letting a crawler walk every combination burns the',
        '# crawl budget on near-duplicates; the canonical tag on each page points',
        '# back at the unfiltered listing, and these rules save the round trip.',
        'Disallow: /shop/?*sort=',
        'Disallow: /shop/?*min_price=',
        'Disallow: /shop/?*max_price=',
        'Disallow: /shop/?*page=',
        '',
        # Built from the configured site address rather than a hardcoded domain,
        # so a domain change does not leave robots.txt pointing crawlers at a
        # sitemap that no longer exists.
        f'Sitemap: {CompanySettings.get_settings().base_url}/sitemap.xml',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')


@module_required('customers')
def admin_lead_list(request):
    """
    Back-office list of website enquiries (ContactMessage rows).

    Args:
        request (HttpRequest): Supports `status` ('new'/'all') and `page`.

    Returns:
        HttpResponse: The rendered lead inbox.

    Business Logic:
        These are the enquiries the public contact form and the homepage hero form
        produce — the top of the sales funnel. Until now they were reachable only
        through Django's stock /admin/, which meant in practice they were not
        reached at all.

        Unread leads are shown first and by default, because the only question that
        matters on this screen is "what have I not answered yet".
    """
    settings = CompanySettings.get_settings()

    leads = ContactMessage.objects.all()
    status = request.GET.get('status', 'new')

    # Spam is excluded from every view except its own tab. It is never deleted
    # here - a filter that silently destroys a misjudged enquiry is worse than
    # the spam it removes - but it does not belong in a list whose job is
    # showing the owner who is waiting for a reply.
    if status == 'spam':
        leads = leads.filter(is_spam=True)
    elif status == 'new':
        leads = leads.filter(is_spam=False, is_read=False)
    else:
        leads = leads.filter(is_spam=False)

    paginator = Paginator(leads, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'portal/admin/lead_list.html', {
        'settings': settings,
        'page_obj': page_obj,
        'leads': page_obj.object_list,
        'status': status,
        # The counts behind the tabs. `new_count` drives the sidebar badge, so
        # it excludes spam too - a badge showing 31 when 31 are bots is how the
        # badge stops meaning anything.
        'new_count': ContactMessage.objects.filter(is_spam=False, is_read=False).count(),
        'total_count': ContactMessage.objects.filter(is_spam=False).count(),
        'spam_count': ContactMessage.objects.filter(is_spam=True).count(),
    })


@module_required('customers')
def admin_lead_spam_action(request):
    """
    Bulk actions on flagged enquiries: delete them, or release one back.

    Args:
        request (HttpRequest): POST with `action` of 'delete_all' or 'not_spam',
            and `lead_id` for the latter.

    Returns:
        HttpResponseRedirect: back to the spam tab.

    Clearing spam one row at a time is why it accumulates - 31 messages is 31
    confirmations. Releasing is per-message on purpose: that is the action with
    consequences, and it should be deliberate.
    """
    if request.method != 'POST':
        return redirect('/portal/admin/leads/?status=spam')

    action = request.POST.get('action', '')

    if action == 'delete_all':
        deleted, _ = ContactMessage.objects.filter(is_spam=True).delete()
        messages.success(request, f'Deleted {deleted} spam message{"" if deleted == 1 else "s"}.')

    elif action == 'not_spam':
        lead = ContactMessage.objects.filter(id=request.POST.get('lead_id')).first()
        if lead is not None:
            lead.is_spam = False
            lead.spam_reason = ''
            lead.save(update_fields=['is_spam', 'spam_reason'])
            messages.success(request, f'Moved {lead.name} back to the inbox.')
            # The notification never fired for a flagged message, so send it
            # now - otherwise releasing a wrongly-flagged enquiry puts it in a
            # list nobody is watching.
            _notify_admin_of_lead(lead)
    else:
        messages.error(request, 'Unknown action.')

    return redirect('/portal/admin/leads/?status=spam')


@module_required('customers')
def admin_lead_delete(request):
    """
    Permanently delete one or more enquiries.

    Args:
        request (HttpRequest): POST with one or more `lead_ids`, plus the
            `status` and `page` of the list to return to.

    Returns:
        HttpResponseRedirect: back to the same tab and page of the lead list.

    Covers both the Delete button on a single card and "Delete selected". The
    templates ask for confirmation first; this view only acts on POST, so a
    link, a prefetch or a crawler can never delete anything.
    """
    status = request.POST.get('status') or request.GET.get('status') or 'new'
    if status not in ('new', 'all', 'spam'):
        status = 'new'
    target = f"{reverse('admin_lead_list')}?status={status}"
    page = (request.POST.get('page') or '').strip()
    if page.isdigit():
        target += f'&page={page}'

    if request.method != 'POST':
        return redirect(target)

    ids = [i for i in request.POST.getlist('lead_ids') if str(i).isdigit()]
    if not ids:
        messages.error(request, 'Select at least one enquiry to delete.')
        return redirect(target)

    deleted, _ = ContactMessage.objects.filter(id__in=ids).delete()
    messages.success(request, f'Deleted {deleted} enquir{"y" if deleted == 1 else "ies"}.')
    return redirect(target)


@module_required('customers')
def admin_lead_toggle_read(request, lead_id):
    """
    Flip a lead between read and unread, then return to the list.

    Args:
        request (HttpRequest): Expected to be a POST.
        lead_id (int): Primary key of the ContactMessage.

    Returns:
        HttpResponseRedirect: Back to the lead list, preserving the current filter.

    Business Logic:
        "Read" here means "dealt with" — it is what removes a lead from the default
        view and from the notification badge. Being able to mark it back to unread
        matters just as much: opening something you cannot action right now should
        not make it disappear.
    """
    lead = get_object_or_404(ContactMessage, id=lead_id)
    if request.method == 'POST':
        lead.is_read = not lead.is_read
        lead.save(update_fields=['is_read'])
        messages.success(
            request,
            f'Marked as {"handled" if lead.is_read else "unread"}: {lead.name}'
        )
    status = request.GET.get('status', 'new')
    return redirect(f"{reverse('admin_lead_list')}?status={status}")


@module_required('orders')
def notification_counts(request):
    """
    AJAX endpoint: Returns notification counts for the admin bell icon.

    Args:
        request (HttpRequest): The incoming AJAX GET request.

    Returns:
        JsonResponse: {'pending_requests': int, 'pending_orders': int}

    Business Logic:
        The notification bell in the admin topbar needs to show unread product
        requests and pending orders. This endpoint provides those counts so the
        frontend can update the badge in real-time without reloading the page.
    """
    pending_requests = ProductRequest.objects.filter(status='pending').count()
    pending_orders = Order.objects.filter(is_placed=False).count()
    # Unanswered website enquiries. Added because leads were the one inbound queue
    # with no indicator anywhere in the back-office — they could sit for days while
    # the sender assumed they had been ignored.
    new_leads = ContactMessage.objects.filter(is_read=False).count()
    return JsonResponse({
        'new_leads': new_leads,
        'pending_requests': pending_requests,
        'pending_orders': pending_orders,
    })


@module_required('customers')
def admin_portfolio_reorder(request):
    """
    AJAX endpoint: Reorders portfolio items based on a new ID sequence.

    Args:
        request (HttpRequest): The incoming AJAX POST request with 'ids' JSON array.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        When the admin drags and drops portfolio items to reorder them, the
        frontend sends the new order as a JSON array of IDs. This endpoint
        updates each item's display_order to match the new sequence.

    Django Concepts:
        - json.loads(): Parses the JSON string from the POST data into a Python list.
        - enumerate(ids, start=1): Generates 1-based indices for display_order.
        - PortfolioItem.objects.filter(id__in=ids): Fetches only the items being reordered.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})
    import json
    ids_raw = request.POST.get('ids', '[]')
    try:
        ids = json.loads(ids_raw)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid IDs'})
    if not isinstance(ids, list) or not ids:
        return JsonResponse({'success': False, 'message': 'No IDs provided'})

    items = {item.id: item for item in PortfolioItem.objects.filter(id__in=ids)}
    for index, item_id in enumerate(ids, start=1):
        item = items.get(item_id)
        if item:
            item.display_order = index
            item.save(update_fields=['display_order'])

    return JsonResponse({'success': True, 'message': 'Order updated'})



# ==============================================================================
# SECTION 9: CUSTOMER SUPPORT TICKETS
# ==============================================================================
# The customer-facing side of the support system. Customers open tickets, view
# their own thread, and reply. Internal notes (is_internal) are never shown here.
# The support-desk side (queue, assignment, status) lives in the support app.


@customer_login_required
def customer_support_list(request):
    """List the logged-in customer's support tickets."""
    tickets = Ticket.objects.filter(customer=request.customer).order_by('-updated_at')
    settings = CompanySettings.get_settings()
    return render(request, 'portal/support_list.html', {
        'customer': request.customer,
        'tickets': tickets,
        'settings': settings,
    })


@customer_login_required
def customer_support_create(request):
    """Open a new support ticket with an initial message."""
    settings = CompanySettings.get_settings()

    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        category = request.POST.get('category', 'general')
        priority = request.POST.get('priority', Ticket.PRIORITY_NORMAL)
        body = request.POST.get('body', '').strip()

        if not subject or not body:
            messages.error(request, 'Please provide a subject and a message.')
            return render(request, 'portal/support_create.html', {
                'customer': request.customer, 'settings': settings,
                'categories': Ticket.CATEGORY_CHOICES, 'priorities': Ticket.PRIORITY_CHOICES,
                'form_data': {'subject': subject, 'category': category, 'priority': priority, 'body': body},
            })

        if category not in dict(Ticket.CATEGORY_CHOICES):
            category = 'general'
        if priority not in dict(Ticket.PRIORITY_CHOICES):
            priority = Ticket.PRIORITY_NORMAL

        ticket = Ticket.objects.create(
            created_by=request.user,
            customer=request.customer,
            subject=subject,
            category=category,
            priority=priority,
            status=Ticket.STATUS_OPEN,
        )
        msg = TicketMessage.objects.create(ticket=ticket, author=request.user, body=body)
        for f in request.FILES.getlist('attachments'):
            TicketAttachment.objects.create(message=msg, file=f)

        # Notify the support desk that a new ticket has arrived.
        send_typed_email(
            email_type='security',
            subject=f'New support ticket #{ticket.id} — {settings.company_name}',
            message=(
                f"A new support ticket has been opened by {request.customer.name}.\n\n"
                f"Subject: {subject}\nPriority: {ticket.get_priority_display()}\n\n{body}"
            ),
            recipient_list=[settings.get_smtp_profile('security').get('from_address')
                            or settings.email_from_address
                            or 'support@localhost'],
            fail_silently=True,
        )

        messages.success(request, f'Support ticket #{ticket.id} created.')
        return redirect('portal_support_detail', ticket_id=ticket.id)

    return render(request, 'portal/support_create.html', {
        'customer': request.customer, 'settings': settings,
        'categories': Ticket.CATEGORY_CHOICES, 'priorities': Ticket.PRIORITY_CHOICES,
        'form_data': {},
    })


@customer_login_required
def customer_support_detail(request, ticket_id):
    """View one of the customer's tickets and post a reply."""
    ticket = get_object_or_404(Ticket, id=ticket_id, customer=request.customer)
    settings = CompanySettings.get_settings()

    if request.method == 'POST':
        body = request.POST.get('body', '').strip()
        if body:
            msg = TicketMessage.objects.create(ticket=ticket, author=request.user, body=body)
            for f in request.FILES.getlist('attachments'):
                TicketAttachment.objects.create(message=msg, file=f)
            # A customer reply re-opens the conversation for the support desk.
            if ticket.status in (Ticket.STATUS_PENDING, Ticket.STATUS_RESOLVED):
                ticket.status = Ticket.STATUS_OPEN
            ticket.save()
            messages.success(request, 'Reply sent.')
        return redirect('portal_support_detail', ticket_id=ticket.id)

    # Customers never see internal notes.
    thread = ticket.messages.filter(is_internal=False).select_related('author').prefetch_related('attachments')
    return render(request, 'portal/support_detail.html', {
        'customer': request.customer,
        'ticket': ticket,
        'thread': thread,
        'settings': settings,
    })


# ==============================================================================
# SECTION 10: CUSTOMER NOTIFICATIONS
# ==============================================================================
# In-portal notifications (order status, shipment updates, payments, support
# replies). Reuses orders.Notification, which already supports a customer FK.


@customer_login_required
def customer_notifications(request):
    """List the customer's notifications; viewing the page marks them read."""
    from orders.models import Notification
    settings = CompanySettings.get_settings()
    notifications = Notification.objects.filter(customer=request.customer)[:100]
    # Mark everything as read once the customer has seen the list.
    Notification.objects.filter(customer=request.customer, is_read=False).update(is_read=True)
    return render(request, 'portal/notifications.html', {
        'customer': request.customer,
        'notifications': notifications,
        'settings': settings,
    })


# =============================================================================
# COUNTRY LANDING PAGES
# =============================================================================
# One crawlable page per market, tied together with reciprocal hreflang.
#
# WHY NOT DETECT THE COUNTRY AND SWAP THE HOMEPAGE
#
# Because the crawler would never see the swap. Googlebot fetches almost
# exclusively from US addresses, so an IP-driven homepage would be indexed as
# the US version and the Pakistan, UAE and UK variants would never enter the
# index at all - the exact opposite of the goal. Distinct URLs are what can be
# crawled, linked to, and ranked separately.
#
# Geolocation still has a place, but only to OFFER the local page (see the
# suggestion banner in base.html), never to force it.
# =============================================================================

def market_page(request, slug):
    """
    A country landing page: what we source, how it ships to that market, and
    the freight position for that lane.

    Freight is read from ShippingDestination rather than written into the
    template. Only the lanes operations has actually priced show a rate; the
    rest say the shipment is quoted individually, which is true and keeps a
    number nobody agreed to off a public page.
    """
    from portal.markets import MARKETS, get_market

    market = get_market(slug)
    if market is None:
        raise Http404('No such market.')

    settings_obj = CompanySettings.get_settings()

    # Does operations actually run this lane?
    from settings_manager.models import ShippingDestination
    destination = ShippingDestination.objects.filter(
        code=market['code'], is_active=True
    ).first()

    # Real categories, so each page carries substantive content and links into
    # the catalogue rather than being a page of adjectives.
    categories = (
        Category.objects.filter(is_active=True)
        .annotate(n=Count('products', filter=Q(products__is_draft=False,
                                               products__is_private=False)))
        .filter(n__gt=0)
        .order_by('-n')[:9]
    )

    featured = list(
        _public_products().filter(images__image__gt='').distinct().order_by('-id')[:4]
    )
    featured_products = [
        {'product': p, 'first_image': p.primary_image, 'cbm': None, 'in_cart': False}
        for p in featured
    ]

    return render(request, 'portal/market.html', {
        'settings': settings_obj,
        'market': market,
        'markets': MARKETS,
        'lane_is_priced': destination is not None,
        'categories': categories,
        'featured_products': featured_products,
        'is_customer': bool(
            request.user.is_authenticated
            and getattr(getattr(request.user, 'profile', None), 'customer', None)
        ),
        'canonical_path': request.path,
    })
