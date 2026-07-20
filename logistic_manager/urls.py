"""
URL configuration for the logistic_manager project.

The `urlpatterns` list routes incoming HTTP URLs to the correct Python view functions.
For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/

Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf (sub-routing)
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

# ---------------------------------------------------------------------------
# Django URL Imports
# ---------------------------------------------------------------------------
# path()       - The modern way to define a URL route. Uses simple strings
#                and angle-bracket converters like <int:customer_id>.
#                Replaces the older regex-based re_path() for most cases.
# include()    - Lets you "mount" another app's urls.py under a prefix.
#                For example: path('customers/', include('customers.urls'))
#                means any URL starting with /customers/ is handled by
#                customers/urls.py. This keeps each app's routes organized.
# re_path()    - (not used here) Uses regular expressions for complex URL
#                matching patterns. path() is preferred for readability.
# ---------------------------------------------------------------------------
from django.urls import path, include

# ---------------------------------------------------------------------------
# Django Settings & Static File Imports
# ---------------------------------------------------------------------------
# settings     - The global settings object. We use it here to check DEBUG mode
#                so we only serve uploaded media files during development.
# static()     - A helper that creates URL patterns for serving user-uploaded
#                files (images, PDFs, etc.) from the filesystem during local
#                development. In production, the web server (Nginx/Apache)
#                handles this directly for performance and security.
# ---------------------------------------------------------------------------
from django.conf import settings
from django.conf.urls.static import static

# ---------------------------------------------------------------------------
# Django Template & Utility Imports
# ---------------------------------------------------------------------------
# render()     - Django's shortcut for rendering a template with a context
#                dictionary and returning an HttpResponse. It looks up the
#                template, merges the data, and sends HTML back to the browser.
# ---------------------------------------------------------------------------
from django.shortcuts import render

# Python standard library imports for the dashboard view
import calendar          # Provides month_name, monthrange() for date calculations
import json              # Serializes Python lists/dicts into JSON strings for JS charts
from datetime import date, timedelta  # For today's date and building date ranges

# Django ORM aggregation functions for dashboard statistics
# Sum   - Adds up numeric fields (e.g., total revenue, total CBM)
# Count - Counts the number of matching database rows
from django.db.models import Sum, Count

# Django's built-in authentication views (login, logout, password change, etc.)
# These are pre-built, battle-tested views that handle form rendering,
# validation, and session management for you.
from django.contrib.auth import views as auth_views

# Django admin site object. We mount its URLs under /admin/.
from django.contrib import admin

# A decorator that redirects unauthenticated users to the login page.
# Placing @login_required above a view function is the standard Django way
# to protect private pages. If a user is not logged in, they are redirected
# to the URL defined in settings.LOGIN_URL.
from django.contrib.auth.decorators import login_required

# Unified role-based guards. The dashboard aggregates data from every module, so
# it is open to any internal back-office user (admin / staff / support) but not
# to customers or the public.
from accounts.decorators import staff_required
from accounts import views as account_views

# ---------------------------------------------------------------------------
# Django Sitemap Framework Imports
# ---------------------------------------------------------------------------
# sitemap()    - A pre-built view that renders a sitemap.xml from Sitemap classes.
#                It takes a {'sitemaps': {...}} dictionary and automatically
#                generates the XML output that search engines like Google read.
# ---------------------------------------------------------------------------
from django.contrib.sitemaps.views import sitemap

# ---------------------------------------------------------------------------
# Portal Sitemap Classes
# ---------------------------------------------------------------------------
# StaticViewSitemap defines which public pages should be included in sitemap.xml.
# ---------------------------------------------------------------------------
from portal.sitemaps import StaticViewSitemap

# Import portal views so they can be referenced in URL patterns at root level
from portal import views as portal_views

# ---------------------------------------------------------------------------
# SITEMAPS DICTIONARY
# ---------------------------------------------------------------------------
# This dictionary is passed to the sitemap view. Each key is a section name
# (for organizing the sitemap), and each value is a Sitemap class instance.
# ---------------------------------------------------------------------------
sitemaps = {
    'static': StaticViewSitemap,  # All public marketing pages (homepage, about, etc.)
}
from products.models import Product               # Product catalog for counting items
from customers.models import Customer             # Customer directory for counting clients
from orders.models import Order, OrderItem          # Order records for revenue, shipment, CBM stats
from khata.models import LedgerEntry                # Ledger (accounting) entries for financial tracking
from settings_manager.models import CompanySettings  # Company currency/branding for display


# =============================================================================
# DASHBOARD VIEW
# =============================================================================
# This is a custom view function (not inside any app) that serves as the
# admin home page. It aggregates data from ALL apps to give the business owner
# a real-time overview of the logistics operation.
# =============================================================================

@staff_required
def dashboard(request):
    """
    Renders the admin dashboard with real-time business analytics.

    Args:
        request (HttpRequest): The incoming HTTP request from the browser.
                               Contains user session, GET/POST data, headers, etc.

    Returns:
        HttpResponse: A rendered HTML page ('dashboard.html') containing
                      KPI cards, charts, recent orders, and monthly statistics.

    Business Logic:
        The logistics business owner needs to see the big picture every day:
        - How many orders were placed this month?
        - What is the total volume (CBM) and weight shipped?
        - How much revenue was generated?
        - How many shipments were processed?
        - What is the trend over the last 6 months?

        This view pulls data from the Order, OrderItem, Product, Customer,
        and LedgerEntry models and packages it into a single context dictionary
        that the template uses to render charts, tables, and summary cards.
    """
    # Get today's date. We use date.today() (not datetime.now()) because
    # we only care about the calendar day, not the exact hour/minute.
    today = date.today()

    # -------------------------------------------------------------------------
    # CURRENT MONTH STATISTICS
    # -------------------------------------------------------------------------
    # The business owner wants to know how the current month is performing.
    # We calculate the first day of the month, then filter all orders created
    # on or after that date.
    # -------------------------------------------------------------------------

    # Replace the day component with 1 to get the first day of this month.
    # Example: if today is 2024-07-15, month_start becomes 2024-07-01.
    month_start = today.replace(day=1)

    # Filter orders created from the start of the month until now.
    # The `date__date` syntax means: look at the DATE part of the DateTimeField
    # (strip the time component). This is useful when the 'date' field stores
    # both date and time but we only care about the calendar day.
    monthly_qs = Order.objects.filter(date__date__gte=month_start)

    # Count how many orders were placed this month.
    monthly_orders = monthly_qs.count()

    # -------------------------------------------------------------------------
    # Aggregation: total_cbm, total_weight, total (revenue)
    # -------------------------------------------------------------------------
    # aggregate() is a Django ORM method that performs SQL-level calculations.
    # It returns a dictionary with keys like 't' (the alias we give).
    # The pattern `aggregate(t=Sum('total_cbm'))` runs SQL: SELECT SUM(total_cbm) FROM orders
    # The `['t'] or 0` ensures we get 0 instead of None if there are no orders.
    # float() converts the Decimal to a Python float for JSON serialization later.
    # -------------------------------------------------------------------------
    monthly_cbm = float(monthly_qs.aggregate(t=Sum('total_cbm'))['t'] or 0)
    monthly_weight = float(monthly_qs.aggregate(t=Sum('total_weight'))['t'] or 0)
    monthly_revenue = float(monthly_qs.aggregate(t=Sum('total'))['t'] or 0)

    # -------------------------------------------------------------------------
    # DISTINCT SHIPMENT BLOCKS (this month)
    # -------------------------------------------------------------------------
    # In logistics, a single order can contain multiple items shipped in
    # different "shipment blocks" (identified by shipment_no). The business
    # wants to know how many unique shipment blocks were processed, not
    # just how many orders exist.
    # -------------------------------------------------------------------------
    # values('order', 'shipment_no').distinct() tells Django to generate SQL:
    # SELECT DISTINCT order_id, shipment_no FROM order_items WHERE ...
    # .count() then gives the number of unique (order, shipment_no) pairs.
    # -------------------------------------------------------------------------
    monthly_shipments = int(
        OrderItem.objects.filter(order__date__date__gte=month_start)
        .values('order', 'shipment_no').distinct().count()
    )

    # -------------------------------------------------------------------------
    # LAST 6 MONTHS TREND DATA (for the line chart)
    # -------------------------------------------------------------------------
    # We build lists of labels and numeric values for a JavaScript chart library.
    # The chart shows the business owner if orders are growing or declining.
    # -------------------------------------------------------------------------
    chart_labels = []     # Human-readable month names like "Jul 2024"
    chart_orders = []     # Number of orders per month
    chart_cbm = []        # Total cubic meters per month
    chart_shipments = []  # Total shipment blocks per month

    # Loop from 5 months ago to now (inclusive). Example: if today is July,
    # this iterates: February, March, April, May, June, July.
    for i in range(5, -1, -1):
        # Calculate the month number by subtracting 'i' from current month.
        # This can go negative (e.g., July=7, i=5 -> 2, i=6 -> 1, i=7 -> 0).
        m = today.month - i
        y = today.year

        # Handle year rollover. If month is 0 or negative, add 12 and
        # subtract 1 from the year. Example: m=0 -> December of previous year.
        while m <= 0:
            m += 12
            y -= 1

        # ms = month start (first day of that month)
        # me = month end (last day of that month, using calendar.monthrange)
        # calendar.monthrange(year, month) returns (weekday_of_1st, days_in_month)
        ms = date(y, m, 1)
        me = date(y, m, calendar.monthrange(y, m)[1])

        # Filter orders that fall within this month's date range (inclusive).
        qs = Order.objects.filter(date__date__gte=ms, date__date__lte=me)

        # Count orders in this month
        o_count = qs.count()

        # Aggregate CBM for this month
        cbm_val = float(qs.aggregate(t=Sum('total_cbm'))['t'] or 0)

        # Count distinct shipment blocks for this month
        ship_count = int(
            OrderItem.objects.filter(order__date__date__gte=ms, order__date__date__lte=me)
            .values('order', 'shipment_no').distinct().count()
        )

        # Append data to the chart lists
        # strftime('%b %Y') formats as "Jul 2024" (short month name + full year)
        chart_labels.append(ms.strftime('%b %Y'))
        chart_orders.append(o_count)
        # round to 3 decimal places for clean display in the chart
        chart_cbm.append(round(cbm_val, 3))
        chart_shipments.append(ship_count)

    # -------------------------------------------------------------------------
    # ORDER STATUS BREAKDOWN (placed vs not placed)
    # -------------------------------------------------------------------------
    # The business tracks whether an order has been "placed" with suppliers.
    # is_placed=True means the order is confirmed and sent to the warehouse.
    # is_placed=False means it is still a draft or pending.
    # -------------------------------------------------------------------------
    # select_related('customer') is a performance optimization. It performs a
    # SQL JOIN so that when we access order.customer.name, Django doesn't need
    # to run a separate database query. This is crucial for list views.
    # order_by('-date') sorts newest first (the minus sign means descending).
    # -------------------------------------------------------------------------
    all_orders = Order.objects.select_related('customer').order_by('-date')
    placed_count = all_orders.filter(is_placed=True).count()
    not_placed_count = all_orders.filter(is_placed=False).count()

    # -------------------------------------------------------------------------
    # PREVIOUS MONTH COMPARISON
    # -------------------------------------------------------------------------
    # A tile that just reads "0" tells the owner nothing. Comparing the current
    # month against the previous one turns each tile into something actionable
    # ("3 orders, down from 8 last month"). We compute the previous calendar
    # month's window and the same four metrics over it.
    # -------------------------------------------------------------------------
    prev_month_end = month_start - timedelta(days=1)          # last day of previous month
    prev_month_start = prev_month_end.replace(day=1)          # first day of previous month
    prev_qs = Order.objects.filter(date__date__gte=prev_month_start, date__date__lte=prev_month_end)
    prev_orders = prev_qs.count()
    prev_revenue = float(prev_qs.aggregate(t=Sum('total'))['t'] or 0)

    # True when the current month has any activity at all. The template uses this
    # to show a single "no activity yet" note instead of a row of zeros.
    has_monthly_activity = bool(monthly_orders or monthly_revenue or monthly_cbm or monthly_weight)

    # -------------------------------------------------------------------------
    # PAYMENT STATUS DISTRIBUTION (for dashboard doughnut chart)
    # -------------------------------------------------------------------------
    # Counts how many orders fall into each payment category.
    # This helps the admin quickly see cash flow health.
    # -------------------------------------------------------------------------
    payment_status_qs = Order.objects.values('payment_status').annotate(count=Count('id')).order_by('payment_status')
    payment_status_labels = []
    payment_status_counts = []
    payment_label_map = {'unpaid': 'Unpaid', 'partial': 'Partial', 'paid': 'Paid'}
    counts_by_status = {ps['payment_status']: ps['count'] for ps in payment_status_qs}
    for ps in payment_status_qs:
        payment_status_labels.append(payment_label_map.get(ps['payment_status'], ps['payment_status']))
        payment_status_counts.append(ps['count'])

    # Payment status as a proportional bar instead of a doughnut. A doughnut with a
    # single category renders as one solid ring that conveys nothing; a stacked bar
    # reads correctly at every data shape and takes a third of the vertical space.
    payment_total = sum(counts_by_status.values())
    payment_breakdown = []
    for key, label, css in (('paid', 'Paid', 'paid'), ('partial', 'Partial', 'partial'), ('unpaid', 'Unpaid', 'unpaid')):
        count = counts_by_status.get(key, 0)
        if not count:
            continue
        payment_breakdown.append({
            'label': label,
            'css': css,
            'count': count,
            'pct': round(count * 100.0 / payment_total, 1) if payment_total else 0,
        })

    # -------------------------------------------------------------------------
    # SHIPPING METHOD DISTRIBUTION (for dashboard doughnut chart)
    # -------------------------------------------------------------------------
    # Counts how many orders use each shipping method.
    # Helps the admin understand which freight modes are most popular.
    # -------------------------------------------------------------------------
    shipping_method_qs = Order.objects.values('shipping_method').annotate(count=Count('id')).order_by('-count')
    method_labels_map = {'manual': 'Manual', 'air': 'Air', 'sea': 'Sea', 'ksa_air': 'KSA Air', 'ksa_sea': 'KSA Sea', 'ksa': 'KSA'}
    shipping_method_labels = []
    shipping_method_counts = []
    for sm in shipping_method_qs:
        shipping_method_labels.append(method_labels_map.get(sm['shipping_method'], sm['shipping_method']))
        shipping_method_counts.append(sm['count'])

    # -------------------------------------------------------------------------
    # 6-MONTH REVENUE TREND (for dashboard line chart)
    # -------------------------------------------------------------------------
    # Parallel to the existing order/CBM/shipment charts, we also compute
    # monthly revenue for the last 6 months so the dashboard can show a
    # revenue trend line alongside the other metrics.
    # -------------------------------------------------------------------------
    chart_revenue = []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        ms = date(y, m, 1)
        me = date(y, m, calendar.monthrange(y, m)[1])
        qs = Order.objects.filter(date__date__gte=ms, date__date__lte=me)
        rev_val = float(qs.aggregate(t=Sum('total'))['t'] or 0)
        chart_revenue.append(round(rev_val, 2))

    # -------------------------------------------------------------------------
    # BUILD THE CONTEXT DICTIONARY
    # -------------------------------------------------------------------------
    # The context is a Python dictionary that maps variable names to data.
    # The template engine (Jinja2-like syntax in Django templates) uses these
    # keys to insert dynamic values into the HTML. For example:
    # {{ product_count }} in the template will display the number of products.
    # -------------------------------------------------------------------------
    context = {
        # Total counts for the KPI cards at the top of the dashboard
        'product_count': Product.objects.count(),     # How many products in catalog
        'customer_count': Customer.objects.count(),   # How many registered customers
        'order_count': Order.objects.count(),         # Total orders of all time
        'ledger_count': LedgerEntry.objects.count(),  # Total accounting entries

        # Recent orders for the "Latest Orders" table on the dashboard
        # [:5] slices the queryset to only the first 5 results (Python slicing)
        'recent_orders': Order.objects.select_related('customer').order_by('-date')[:5],

        # All orders (for the full orders table or data export)
        'all_orders': all_orders,

        # Placed vs not placed counts for status breakdown cards
        'placed_count': placed_count,
        'not_placed_count': not_placed_count,

        # Monthly KPIs (current month only)
        'monthly_orders': monthly_orders,
        'monthly_shipments': monthly_shipments,
        'monthly_cbm': round(monthly_cbm, 3),         # rounded for clean display
        'monthly_weight': round(monthly_weight, 3),
        'monthly_revenue': round(monthly_revenue, 2),   # 2 decimals for currency

        # Human-readable current month label, e.g., "July 2024"
        'current_month': today.strftime('%B %Y'),

        # Previous-month comparison + empty-state flag for the monthly tiles
        'prev_month_label': prev_month_start.strftime('%B'),
        'prev_orders': prev_orders,
        'prev_revenue': round(prev_revenue, 2),
        'has_monthly_activity': has_monthly_activity,

        # Payment mix rendered as a proportional bar (replaces the doughnut)
        'payment_breakdown': payment_breakdown,
        'payment_total': payment_total,

        # Currency code so money on the dashboard is always labelled
        'currency': CompanySettings.get_settings().currency,

        # Chart data serialized to JSON strings so JavaScript can parse them.
        # json.dumps() converts a Python list like ['Jul 2024', 'Aug 2024']
        # into a JavaScript-compatible string: '["Jul 2024","Aug 2024"]'
        'chart_labels': json.dumps(chart_labels),
        'chart_orders': json.dumps(chart_orders),
        'chart_cbm': json.dumps(chart_cbm),
        'chart_shipments': json.dumps(chart_shipments),

        # Additional dashboard chart data (new)
        'chart_payment_labels': json.dumps(payment_status_labels),
        'chart_payment_counts': json.dumps(payment_status_counts),
        'chart_shipping_labels': json.dumps(shipping_method_labels),
        'chart_shipping_counts': json.dumps(shipping_method_counts),
        'chart_revenue': json.dumps(chart_revenue),
    }

    # render() looks up the template 'dashboard.html' in the template directories
    # (as defined in settings.TEMPLATES), passes the context dictionary, and
    # returns an HttpResponse with the final HTML string.
    return render(request, 'dashboard.html', context)


# =============================================================================
# URL PATTERNS (The URL Routing Table)
# =============================================================================
# urlpatterns is a Python list that Django scans from top to bottom.
# When a browser requests a URL, Django walks this list and calls the FIRST
# matching view function. Order matters! More specific routes should come
# before more generic ones.
#
# path(route, view, kwargs=None, name=None)
#   route  - The URL pattern string. Can use converters like <int:id>.
#   view   - The Python function or class that handles the request.
#   name   - A unique string name used in templates and redirects. This is
#            the preferred way to reference URLs (not hardcoding paths).
#
# include(prefix, namespace=None)
#   - Delegates URL matching to another app's urls.py.
#   - Example: path('customers/', include('customers.urls')) means
#     /customers/          -> customers.urls   (root of that app)
#     /customers/add/      -> customers.urls   (the add/ path inside that app)
#   - This modular approach keeps each app's routing self-contained.
# =============================================================================
urlpatterns = [
    # -------------------------------------------------------------------------
    # PUBLIC MARKETING PAGES (from the portal app, but mounted at root level)
    # -------------------------------------------------------------------------
    # These pages are visible to anyone on the internet. They serve as the
    # company's public-facing website: homepage, portfolio, about us, services,
    # and contact form. Mounting them at the root ('') makes the homepage
    # accessible at mudassirllc.com/ instead of mudassirllc.com/portal/.
    # -------------------------------------------------------------------------
    path('', portal_views.front_page, name='front_page'),          # Homepage
    path('portfolio/', portal_views.portfolio_page, name='portfolio_page'),  # Work showcase
    path('about/', portal_views.about_page, name='about_page'),              # Company info
    path('services/', portal_views.services_page, name='services_page'),     # Services offered
    path('contact/', portal_views.contact_page, name='contact_page'),        # Contact form
    path('testimonials/', portal_views.testimonials_page, name='testimonials_page'),  # Customer reviews
    path('faq/', portal_views.faq_page, name='faq_page'),                    # FAQ accordion

    # -------------------------------------------------------------------------
    # SEO ENDPOINTS (Sitemap & Robots.txt)
    # -------------------------------------------------------------------------
    # sitemap.xml helps search engines discover all public pages.
    # robots.txt guides crawlers on which pages to index or avoid.
    # -------------------------------------------------------------------------
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', portal_views.robots_txt, name='robots_txt'),

    # -------------------------------------------------------------------------
    # ADMIN DASHBOARD (protected by @login_required)
    # -------------------------------------------------------------------------
    # The dashboard view defined above in this file. Only logged-in users
    # can access it because of the @login_required decorator.
    # -------------------------------------------------------------------------
    path('dashboard/', dashboard, name='dashboard'),

    # -------------------------------------------------------------------------
    # APP-SPECIFIC URL ROUTES (delegated via include())
    # -------------------------------------------------------------------------
    # Each Django app has its own urls.py. Using include() keeps the main
    # urls.py clean and lets each app manage its own routes independently.
    # This is a core Django best practice: "apps are self-contained and reusable."
    # -------------------------------------------------------------------------
    # PRODUCTS: Product catalog, supplier quotes, bulk uploads, pricing
    path('products/', include('products.urls')),

    # CUSTOMERS: Customer directory, CRUD operations, product assignments, quotations
    path('customers/', include('customers.urls')),

    # ORDERS: Order creation, editing, invoices, packing lists, payment tracking
    path('orders/', include('orders.urls')),

    # KHATA: Ledger (accounting) system for customer financial records
    path('khata/', include('khata.urls')),

    # NOON LABELS: Generates shipping labels and carton labels for the Noon marketplace
    path('noon-labels/', include('noon_labels.urls')),

    # SETTINGS: Company configuration, shipping calculators, shipping company management
    path('settings/', include('settings_manager.urls')),

    # PORTAL: Customer login portal, quote requests, customer dashboard, admin pages
    # Note: The public portal pages are duplicated above at root level for SEO/friendliness.
    path('portal/', include('portal.urls')),

    # SUPPORT: Support-ticket queue for the internal Support role.
    path('support/', include('support.urls')),

    # ACCOUNTS: Unified authentication (login/logout/register/password reset) and
    # internal user & role management. This is the single auth surface for every
    # role — admin, staff, support, and customer.
    path('accounts/', include('accounts.urls')),

    # -------------------------------------------------------------------------
    # LEGACY AUTH URL ALIASES
    # -------------------------------------------------------------------------
    # The whole app now authenticates through the unified accounts views. These
    # aliases keep the historical URL names (`admin_login`, `admin_logout`) and
    # paths working so existing templates and bookmarks don't break — they simply
    # point at the new role-aware login/logout views. They MUST come before the
    # `admin/` include below, otherwise Django admin's own login would shadow them.
    # -------------------------------------------------------------------------
    path('admin/login/', account_views.login_view, name='admin_login'),
    path('admin/logout/', account_views.logout_view, name='admin_logout'),

    # DJANGO ADMIN: Default admin interface for staff to manage database records.
    path('admin/', admin.site.urls),
]

# -------------------------------------------------------------------------
# MEDIA FILES SERVING (Development Only)
# -------------------------------------------------------------------------
# User-uploaded files (product images, PDFs, etc.) are stored in MEDIA_ROOT.
# During local development (DEBUG=True), Django can serve these files directly
# using the static() helper. This adds URL patterns to urlpatterns that map
# MEDIA_URL to the filesystem path MEDIA_ROOT.
#
# IMPORTANT: In production, NEVER let Django serve media files. Configure
# your web server (Apache/Nginx) to serve them directly. Django is not
# optimized for static file serving and it can expose security risks.
# -------------------------------------------------------------------------
if settings.DEBUG:
    # static() returns a list of URL patterns; += appends them to urlpatterns
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
