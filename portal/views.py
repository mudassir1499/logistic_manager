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

# JsonResponse is a Django HttpResponse subclass that serializes data to JSON.
# Used for AJAX endpoints (login, register, profile update) so the frontend
# can receive structured data without a full page reload.
from django.http import JsonResponse

# Sum is a Django ORM aggregation function that adds up values across a queryset.
# Used in the ledger to calculate total credit and debit amounts per currency.
from django.db.models import Sum

# Django's messages framework provides a one-time notification system
# that persists across redirects. Used by admin views to show success/error
# flash messages (e.g., "Customer created successfully").
from django.contrib import messages

# Decimal is Python's fixed-point arithmetic type. Critical for financial
# calculations (ledger balances, order totals) to avoid floating-point
# rounding errors that would cause discrepancies in money calculations.
from decimal import Decimal, InvalidOperation

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
from products.models import Product, ProductImage

# orders: Purchase orders, line items, shipment tracking
from orders.models import Order, OrderItem

# khata: Ledger / financial entries (credit/debit transactions per customer)
from khata.models import LedgerEntry

# settings_manager: Company-wide settings (name, logo, phone, currency, etc.)
from settings_manager.models import CompanySettings

# portal models: Product quotation requests, portfolio items, password reset requests,
# cart items, and contact form submissions.
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
    
    # Render the front_page.html template, passing context variables that the
    # template can use: settings (company info), customer (if logged in),
    # and portfolio_items (featured gallery).
    return render(request, 'portal/front_page.html', {
        'settings': settings,
        'customer': customer,
        'portfolio_items': portfolio_items,
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
    recent_orders = orders[:5]
    
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
        Customers need to see their complete order history in one place. This view
        fetches every order belonging to the customer, along with related data
        (order items and products) so the template can show each order's line items
        without making additional database queries. This is called "eager loading"
        and prevents the N+1 query problem.
    """
    customer = request.customer
    
    # Fetch all orders for this customer with eager loading of related data:
    #   select_related('customer'):  Joins the Customer table so the template can
    #                               access customer.name without a separate query.
    #   prefetch_related('items__product'): Fetches all OrderItems and their
    #                               related Products in a single query, so
    #                               iterating over order.items.all() in the
    #                               template doesn't hit the database repeatedly.
    orders = Order.objects.filter(customer=customer).select_related('customer').prefetch_related('items__product').order_by('-date')
    
    settings = CompanySettings.get_settings()
    
    return render(request, 'portal/orders.html', {
        'customer': customer,
        'orders': orders,
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
    for item in order.items.all():
        # If shipment_no is None, default to 1 (treat as a single shipment).
        sno = item.shipment_no or 1
        if sno not in shipments_dict:
            shipments_dict[sno] = []
        shipments_dict[sno].append(item)
    
    # Build a structured list of shipment groups for the template.
    # For each shipment, we calculate the total quantity and subtotal of items.
    invoice_shipments = []
    for sno in sorted(shipments_dict.keys()):
        items = shipments_dict[sno]
        # Sum the quantity of all items in this shipment.
        total_qty = sum(item.quantity for item in items)
        # Calculate the subtotal: price * quantity for each item, summed.
        subtotal = sum(item.price * item.quantity for item in items)
        invoice_shipments.append({
            'shipment_no': sno,
            'shipment_name': items[0].shipment_name if items else '',
            'items': items,
            'total_qty': total_qty,
            'subtotal': subtotal,
            'method': items[0].shipment_method if items else 'manual',
        })
    
    # Calculate the invoice totals. Order.total is the sum of all line items.
    # Additional costs are added on top: shipping, other fees, and commission.
    total = order.total
    shipping = order.shipping_cost
    other = order.other_cost
    commission = order.commission_amount
    grand_total = total + shipping + other + commission
    
    return render(request, 'portal/order_detail.html', {
        'customer': customer,
        'order': order,
        'shipments': invoice_shipments,
        'total': total,
        'shipping': shipping,
        'other': other,
        'commission': commission,
        'grand_total': grand_total,
        'settings': settings,
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
    assigned = customer.assigned_products.select_related('product').prefetch_related('product__images').order_by('-assigned_at')
    
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
            'first_image': p.images.first(),  # First image for the thumbnail
            'in_cart': p.id in cart_product_ids,
        })
    
    return render(request, 'portal/products.html', {
        'customer': customer,
        'products_data': products_data,
        'settings': settings,
    })


@customer_login_required
def customer_amazon_products(request):
    """
    Displays published Amazon-sourced products available to the logged-in customer.
    """
    customer = request.customer
    settings = CompanySettings.get_settings()
    products = Product.objects.prefetch_related('images').filter(
        is_draft=False, is_private=False, source='amazon'
    ).order_by('name')
    cart_product_ids = set(
        CartItem.objects.filter(customer=customer).values_list('product_id', flat=True)
    )
    products_data = []
    for p in products:
        cbm = None
        if p.carton_length and p.carton_width and p.carton_height:
            cbm = round(float(p.carton_length) * float(p.carton_width) * float(p.carton_height) / 1_000_000, 4)
        products_data.append({
            'product': p,
            'cbm': cbm,
            'first_image': p.images.first(),
            'in_cart': p.id in cart_product_ids,
        })
    return render(request, 'portal/amazon_products.html', {
        'customer': customer,
        'products_data': products_data,
        'settings': settings,
    })


@customer_login_required
def customer_noon_products(request):
    """
    Displays published Noon-sourced products available to the logged-in customer.
    """
    customer = request.customer
    settings = CompanySettings.get_settings()
    products = Product.objects.prefetch_related('images').filter(
        is_draft=False, is_private=False, source='noon'
    ).order_by('name')
    cart_product_ids = set(
        CartItem.objects.filter(customer=customer).values_list('product_id', flat=True)
    )
    products_data = []
    for p in products:
        cbm = None
        if p.carton_length and p.carton_width and p.carton_height:
            cbm = round(float(p.carton_length) * float(p.carton_width) * float(p.carton_height) / 1_000_000, 4)
        products_data.append({
            'product': p,
            'cbm': cbm,
            'first_image': p.images.first(),
            'in_cart': p.id in cart_product_ids,
        })
    return render(request, 'portal/noon_products.html', {
        'customer': customer,
        'products_data': products_data,
        'settings': settings,
    })


@customer_login_required
def customer_marketplace(request):
    """
    Displays a unified marketplace of Amazon and Noon products for logged-in customers.
    """
    customer = request.customer
    settings = CompanySettings.get_settings()
    source_filter = request.GET.get('source', 'all')

    products_qs = Product.objects.prefetch_related('images').filter(
        is_draft=False, is_private=False, source__in=['amazon', 'noon']
    )
    if source_filter in ('amazon', 'noon'):
        products_qs = products_qs.filter(source=source_filter)
    products_qs = products_qs.order_by('source', 'name')

    cart_product_ids = set(
        CartItem.objects.filter(customer=customer).values_list('product_id', flat=True)
    )
    products_data = []
    for p in products_qs:
        cbm = None
        if p.carton_length and p.carton_width and p.carton_height:
            cbm = round(float(p.carton_length) * float(p.carton_width) * float(p.carton_height) / 1_000_000, 4)
        products_data.append({
            'product': p,
            'cbm': cbm,
            'first_image': p.images.first(),
            'in_cart': p.id in cart_product_ids,
        })
    return render(request, 'portal/marketplace.html', {
        'customer': customer,
        'products_data': products_data,
        'settings': settings,
        'source_filter': source_filter,
    })


def _get_cart_items(request):
    """
    Return the cart items for the current logged-in customer.

    Args:
        request (HttpRequest): The incoming request with request.customer set.

    Returns:
        QuerySet: CartItem queryset for the customer, prefetched with product and images.
    """
    return CartItem.objects.filter(customer=request.customer).select_related('product').prefetch_related('product__images')


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

    try:
        product = Product.objects.get(id=product_id, is_draft=False)
    except (Product.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Product not found.'})

    try:
        quantity = int(quantity)
    except (ValueError, TypeError):
        quantity = 1

    if quantity < product.moq:
        quantity = product.moq

    # Check if this product is already in the cart; if so, increment quantity.
    cart_item, created = CartItem.objects.get_or_create(
        customer=request.customer,
        product=product,
        defaults={'quantity': quantity},
    )
    if not created:
        cart_item.quantity += quantity
        cart_item.save(update_fields=['quantity'])

    cart_count = CartItem.objects.filter(customer=request.customer).count()
    return JsonResponse({
        'success': True,
        'message': f'Added {product.name} to cart.',
        'cart_count': cart_count,
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

    # Calculate totals
    subtotal = _cart_total(items)
    commission_pct = settings.commission_percentage or Decimal('0')
    commission_amount = (subtotal * commission_pct / Decimal('100')).quantize(Decimal('0.01'))
    total = subtotal + commission_amount

    # Create the order as a draft so the admin can review shipping costs.
    order = Order.objects.create(
        customer=customer,
        total=total,
        commission_amount=commission_amount,
        commission_percentage=commission_pct,
        status=Order.STATUS_DRAFT,
        payment_status='unpaid',
    )

    for item in items:
        product = item.product
        prefix = f'item_{item.id}'
        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=item.quantity,
            price=product.price,
            shipment_no=1,
            shipment_method='manual',
            cargo_type='standard',
            label_mark=request.POST.get(f'{prefix}_label_mark', '').strip(),
            carton_mark=request.POST.get(f'{prefix}_carton_mark', '').strip(),
            carton_asn=request.POST.get(f'{prefix}_carton_asn', '').strip(),
            carton_quantity=int(request.POST.get(f'{prefix}_carton_quantity', 1) or 1),
            shipping_label=request.FILES.get(f'{prefix}_shipping_label'),
            carton_label=request.FILES.get(f'{prefix}_carton_label'),
        )

    # Clear the cart after successful order creation.
    items.delete()

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
    return redirect('portal_order_detail', order_id=order.id)


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
    
    # Fetch all ledger entries for this customer, ordered by date (oldest first).
    # Chronological order is essential for calculating a correct running balance.
    entries = LedgerEntry.objects.filter(customer=customer).order_by('date')
    
    # Determine which currencies are used in this customer's ledger. A customer might
    # deal in multiple currencies (e.g., USD for orders and local currency for fees).
    # We need to track balances separately per currency.
    currencies_used = entries.values_list('currency', flat=True).distinct()
    
    # Calculate the final balance for each currency. This is the summary shown
    # at the top of the ledger page. Positive = customer has credit (overpaid);
    # Negative = customer owes money.
    balances = {}
    for cur in currencies_used:
        credit = entries.filter(currency=cur, entry_type='credit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        debit = entries.filter(currency=cur, entry_type='debit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        balances[cur] = credit - debit
    
    # Build a list of entries with running balances. The running balance is the
    # cumulative sum of all entries up to that point, per currency.
    # We track each currency independently because credits/debits in one currency
    # do not affect another.
    entries_with_running = []
    running = {}  # Dictionary to hold running totals per currency.
    for entry in entries:
        cur = entry.currency
        # setdefault initializes the running balance to 0 if this currency hasn't
        # been seen yet in the iteration.
        running.setdefault(cur, Decimal('0'))
        
        # Update the running balance: add for credits, subtract for debits.
        if entry.entry_type == 'credit':
            running[cur] += entry.amount
        else:
            running[cur] -= entry.amount
        
        # Append the entry and its current running balance to the list.
        # The template uses this to display each row with the running total.
        entries_with_running.append({
            'entry': entry,
            'running': running.get(cur, Decimal('0')),
        })
    
    settings = CompanySettings.get_settings()
    
    return render(request, 'portal/ledger.html', {
        'customer': customer,
        'entries_with_running': entries_with_running,
        'balances': balances,
        'settings': settings,
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
        sync_customer_user(customer, raw_password=password or None)

        # Show a success flash message and redirect to the customer list.
        # messages.success() stores the message in the session so it survives the redirect.
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
        sync_customer_user(customer, raw_password=password or None)

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
        customer.delete()
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
        the company. It collects name, email, phone, subject, and message. While
        this implementation currently shows a success message without actually sending
        an email (a common placeholder), the form data is validated and the user
        receives immediate feedback. In production, this would typically integrate
        with an email backend or CRM system.
    """
    settings = CompanySettings.get_settings()
    
    customer = None
    if request.session.get('customer_id'):
        try:
            customer = Customer.objects.get(id=request.session['customer_id'], is_active=True)
        except Customer.DoesNotExist:
            pass
    
    if request.method == 'POST':
        # Extract contact form fields from the POST data.
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()
        
        # Validate required fields. Name, email, and message are mandatory.
        # Phone and subject are optional but collected for completeness.
        if name and email and message:
            # Save the submission to the ContactMessage model so admins can
            # review and follow up from the Django admin backend.
            ContactMessage.objects.create(
                name=name,
                email=email,
                phone=phone,
                subject=subject,
                message=message,
            )
            messages.success(request, 'Thank you for reaching out! We will get back to you within 24 hours.')
            return redirect('contact_page')
        else:
            # If required fields are missing, show an error and re-render the form.
            messages.error(request, 'Please fill in all required fields.')
    
    return render(request, 'portal/contact.html', {
        'settings': settings,
        'customer': customer,
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


def robots_txt(request):
    """
    Renders a robots.txt file for search engine crawlers.

    Args:
        request (HttpRequest): The incoming HTTP request from any visitor.

    Returns:
        HttpResponse: A text/plain response containing robots.txt directives.

    Business Logic:
        robots.txt tells search engines which pages they can and cannot crawl.
        This implementation allows all crawlers to access all public pages while
        disallowing private admin and customer portal URLs. It also points crawlers
        to the sitemap.xml for efficient discovery of all indexable pages.
    """
    from django.http import HttpResponse
    lines = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /dashboard/',
        'Disallow: /portal/',
        'Disallow: /products/',
        'Disallow: /customers/',
        'Disallow: /orders/',
        'Disallow: /khata/',
        'Disallow: /noon-labels/',
        'Disallow: /settings/',
        'Disallow: /media/',
        'Allow: /',
        'Allow: /about/',
        'Allow: /services/',
        'Allow: /contact/',
        'Allow: /portfolio/',
        'Allow: /testimonials/',
        'Allow: /faq/',
        '',
        'Sitemap: https://mudassirllc.com/sitemap.xml',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')


@module_required('customers')
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
    return JsonResponse({
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
