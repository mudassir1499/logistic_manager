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

# timezone.now() returns an aware datetime matching USE_TZ, which is what the
# overdue-invoice comparison needs (Order.date is a DateTimeField).
from django.utils import timezone

# Django ORM aggregation functions for dashboard statistics
# Sum   - Adds up numeric fields (e.g., total revenue, total CBM)
# Count - Counts the number of matching database rows
from django.db.models import Sum, Count

# TruncMonth buckets a datetime to the first of its month, which lets the six-month
# charts be built with two grouped queries instead of one query per month.
from django.db.models.functions import TruncMonth

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
from portal.sitemaps import (StaticViewSitemap, BlogSitemap, ProductSitemap,
                             ShopIndexSitemap, MarketSitemap)

# Import portal views so they can be referenced in URL patterns at root level
from portal import views as portal_views
from orders import views as order_views

# ---------------------------------------------------------------------------
# SITEMAPS DICTIONARY
# ---------------------------------------------------------------------------
# This dictionary is passed to the sitemap view. Each key is a section name
# (for organizing the sitemap), and each value is a Sitemap class instance.
# ---------------------------------------------------------------------------
sitemaps = {
    'static': StaticViewSitemap,  # All public marketing pages (homepage, about, etc.)
    'blog': BlogSitemap,          # Every published blog article, with real lastmod dates
    'shop': ShopIndexSitemap,     # Catalogue landing page + one URL per category
    'markets': MarketSitemap,     # One country landing page per market served
    'products': ProductSitemap,   # Every publicly visible product
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

def _stale_days():
    """The configured no-movement threshold in days (0 = warning disabled)."""
    from orders.views import _stale_shipment_days

    return _stale_shipment_days()


def _stale_shipment_count():
    """
    How many orders hold a shipment that has stopped moving.

    Deliberately calls the same helper the order list filters with, so the
    number on the dashboard and the rows behind ``?stale=1`` can never disagree.
    A count that does not match the list it links to is worse than no count.
    """
    from orders.views import _stale_shipment_order_ids

    days = _stale_days()
    if not days:
        return 0
    return _stale_shipment_order_ids(days).distinct().count()


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

    # -------------------------------------------------------------------------
    # PERFORMANCE NOTE
    # -------------------------------------------------------------------------
    # This used to run one query per metric per month inside the loop below —
    # count, CBM sum and shipment count, six times over, plus a second identical
    # loop further down for revenue. That was ~24 database round trips to draw
    # two charts, and it is most of why this page issued 46 queries.
    #
    # Instead we now group by month in the database: one query returns every
    # month's order count, CBM and revenue together, and a second returns the
    # shipment-block counts. The loop then just reads from those dictionaries, so
    # the query cost is fixed at two regardless of how many months are charted.
    # -------------------------------------------------------------------------
    six_months_ago = date(today.year, today.month, 1) - timedelta(days=1)
    six_months_ago = date(six_months_ago.year, six_months_ago.month, 1)
    for _ in range(4):
        prev_last_day = six_months_ago - timedelta(days=1)
        six_months_ago = date(prev_last_day.year, prev_last_day.month, 1)

    monthly_rows = (
        Order.objects
        .filter(date__date__gte=six_months_ago)
        .annotate(bucket=TruncMonth('date'))
        .values('bucket')
        .annotate(orders=Count('id'), cbm=Sum('total_cbm'), revenue=Sum('total'))
    )
    by_month = {
        (r['bucket'].year, r['bucket'].month): r
        for r in monthly_rows if r['bucket']
    }

    # Shipment blocks are distinct (order, shipment_no) pairs, which cannot be
    # produced by the same aggregate — they need their own grouped query.
    shipment_rows = (
        OrderItem.objects
        .filter(order__date__date__gte=six_months_ago)
        .annotate(bucket=TruncMonth('order__date'))
        .values('bucket', 'order_id', 'shipment_no')
        .distinct()
    )
    shipments_by_month = {}
    for row in shipment_rows:
        if row['bucket']:
            key = (row['bucket'].year, row['bucket'].month)
            shipments_by_month[key] = shipments_by_month.get(key, 0) + 1

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

        ms = date(y, m, 1)

        # Read from the pre-grouped results rather than querying per month.
        row = by_month.get((y, m)) or {}
        o_count = row.get('orders') or 0
        cbm_val = float(row.get('cbm') or 0)
        ship_count = shipments_by_month.get((y, m), 0)

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
    # Reads from the same `by_month` grouping built for the order/CBM chart above.
    # This block used to repeat the whole six-month loop with its own aggregate
    # query per month — six extra round trips to draw a line the other loop had
    # already walked the same months for.
    # -------------------------------------------------------------------------
    chart_revenue = []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        row = by_month.get((y, m)) or {}
        chart_revenue.append(round(float(row.get('revenue') or 0), 2))

    # -------------------------------------------------------------------------
    # BUILD THE CONTEXT DICTIONARY
    # -------------------------------------------------------------------------
    # The context is a Python dictionary that maps variable names to data.
    # The template engine (Jinja2-like syntax in Django templates) uses these
    # keys to insert dynamic values into the HTML. For example:
    # {{ product_count }} in the template will display the number of products.
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # NEEDS ATTENTION — the work queue
    # -------------------------------------------------------------------------
    # Everything above this point describes what HAS happened. None of it tells
    # the owner what to DO, so the dashboard was a report you read and then left
    # to go hunting through five separate pages for outstanding work.
    #
    # This block assembles the actual queue. Each entry is a count plus a link
    # straight to the filtered list that resolves it, and entries with nothing
    # outstanding are dropped rather than shown as a zero — a row of zeros is
    # noise that trains you to ignore the panel.
    # -------------------------------------------------------------------------
    from portal.models import ContactMessage, ProductRequest
    from support.models import Ticket

    # Unpaid orders older than 30 days. `date` is a DateTimeField, so this
    # compares against a timestamp rather than a date.
    overdue_cutoff = timezone.now() - timedelta(days=30)

    attention_items = [
        {
            'key': 'leads',
            'count': ContactMessage.objects.filter(is_read=False).count(),
            'label': 'website enquiries awaiting a reply',
            'url': '/portal/admin/leads/',
            'icon': 'bi-inbox',
            'tone': 'amber',
        },
        {
            'key': 'requests',
            'count': ProductRequest.objects.filter(status='pending').count(),
            'label': 'product requests to review',
            'url': '/portal/admin/requests/',
            'icon': 'bi-clipboard-check',
            'tone': 'violet',
        },
        {
            'key': 'tickets',
            'count': Ticket.objects.filter(status=Ticket.STATUS_OPEN).count(),
            'label': 'support tickets open',
            'url': '/support/',
            'icon': 'bi-life-preserver',
            'tone': 'info',
        },
        {
            'key': 'unplaced',
            'count': not_placed_count,
            'label': 'orders not yet placed with a supplier',
            'url': '/orders/?placed=no',
            'icon': 'bi-cart-dash',
            'tone': 'info',
        },
        {
            'key': 'overdue',
            'count': Order.objects.filter(
                payment_status__in=['unpaid', 'partial'], date__lt=overdue_cutoff
            ).count(),
            'label': 'invoices unpaid for over 30 days',
            'url': '/orders/?payment=unpaid',
            'icon': 'bi-cash-stack',
            'tone': 'red',
        },
        {
            # Shipments that have stopped moving. Every other item here is
            # something that arrived and is waiting to be dealt with; this one is
            # the opposite — nothing arrived, which is exactly why it goes
            # unnoticed until the customer asks where their goods are.
            'key': 'stale_shipments',
            'count': _stale_shipment_count(),
            'label': f'shipments with no movement in {_stale_days()} days',
            'url': '/orders/?stale=1',
            'icon': 'bi-hourglass-split',
            'tone': 'amber',
        },
    ]
    # Only surface what actually needs doing.
    attention_items = [i for i in attention_items if i['count']]

    context = {
        # The work queue, and a flag so the template can show a single
        # "nothing outstanding" state instead of an empty panel.
        'attention_items': attention_items,
        'attention_total': sum(i['count'] for i in attention_items),

        # Total counts for the KPI cards at the top of the dashboard
        'product_count': Product.objects.count(),     # How many products in catalog
        'customer_count': Customer.objects.count(),   # How many registered customers
        'order_count': Order.objects.count(),         # Total orders of all time
        'ledger_count': LedgerEntry.objects.count(),  # Total accounting entries

        # Recent orders for the "Latest Orders" table on the dashboard
        # [:5] slices the queryset to only the first 5 results (Python slicing)
        'recent_orders': Order.objects.select_related('customer').order_by('-date')[:5],

        # The "All Orders" table on this page sits inside a fixed-height scroll
        # box, which makes it LOOK bounded — but it was rendering every order in
        # the database into the HTML, of which about eight are visible at a time.
        # Measured at 1.1 MB of markup for 800 orders, on the page most likely to
        # be opened from a phone.
        #
        # Capped at the 50 most recent, with a link through to the full, paginated
        # and searchable order list for anything older. `recent_order_total` lets
        # the template say honestly that it is showing a subset.
        'all_orders': all_orders[:50],
        'recent_order_total': all_orders.count(),

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
def service_worker(request):
    """
    Serve the back-office service worker from the site root.

    Args:
        request (HttpRequest): unused.

    Returns:
        HttpResponse: the worker as JavaScript.

    Read from disk rather than redirected to /static/: a redirect changes the
    URL the browser registers, which puts the scope back under /static/ and
    defeats the point of the route.
    """
    from django.conf import settings as dj_settings
    from django.http import HttpResponse, Http404
    import os as _os

    for root in list(dj_settings.STATICFILES_DIRS) + [dj_settings.STATIC_ROOT or '']:
        candidate = _os.path.join(str(root), 'sw.js')
        if _os.path.exists(candidate):
            with open(candidate, 'r', encoding='utf-8') as handle:
                body = handle.read()
            response = HttpResponse(body, content_type='application/javascript')
            # The worker is the one file that must never be served stale: a
            # cached copy keeps an old cache version alive on every device.
            response['Cache-Control'] = 'no-cache'
            return response
    raise Http404('sw.js not found')


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
    # Public shipment tracking. No login: the tracking number IS the credential,
    # and the page deliberately carries no customer details, prices or totals.
    # See orders/views.py::track_shipment for the full whitelist.
    path('track/', order_views.track_shipment, name='track_shipment'),

    # Public shipping calculator. A root URL rather than one under /portal/
    # because it needs no account: "how much to ship this to Dubai" is the
    # question a prospective customer asks BEFORE registering, and putting it
    # behind a login answers it only for people who already stayed.
    # Serves the page on GET and answers the quote on POST.
    path('shipping-calculator/', portal_views.shipping_calculator_page,
         name='shipping_calculator_page'),

    # Post-enquiry confirmation. A distinct URL (not a banner on the contact page)
    # so GA4/Meta have a clean conversion destination to count. Deliberately kept
    # out of sitemap.xml and marked noindex in its template.
    path('thank-you/', portal_views.contact_thank_you, name='contact_thank_you'),
    path('testimonials/', portal_views.testimonials_page, name='testimonials_page'),  # Customer reviews
    path('faq/', portal_views.faq_page, name='faq_page'),                    # FAQ accordion

    # -------------------------------------------------------------------------
    # BLOG (public, no login required)
    # -------------------------------------------------------------------------
    # The blog lives at the root, not under /portal/, for two reasons: /portal/ is
    # disallowed in robots.txt, and a short top-level path (/blog/guide-slug/) is
    # easier to share and reads better in a search result than a nested one.
    #
    # Order matters. The index pattern is listed first and the detail pattern uses
    # <slug:slug>, which cannot match an empty string, so /blog/ can never be
    # swallowed by the detail route.
    # -------------------------------------------------------------------------
    path('blog/', portal_views.blog_index, name='blog_index'),
    path('blog/<slug:slug>/', portal_views.blog_detail, name='blog_detail'),

    # -------------------------------------------------------------------------
    # PUBLIC CATALOGUE
    # -------------------------------------------------------------------------
    # Mounted at the root, NOT under /portal/, because robots.txt disallows
    # /portal/ wholesale — a catalogue there could never be indexed however good
    # its markup was. These pages are readable by anyone, including crawlers;
    # ordering still requires a customer login.
    #
    # /shop/ rather than /products/ because /products/ is the staff back-office
    # and is itself disallowed to crawlers.
    #
    # Index first, then the slug route, so /shop/ can never be swallowed by
    # <slug:slug> (which cannot match an empty string anyway).
    # -------------------------------------------------------------------------
    path('shop/', portal_views.shop_index, name='shop_index'),

    # Country landing pages. The URL is the search phrase - somebody looking for
    # this types "china to pakistan", not "markets/pakistan" - and each one is a
    # separate crawlable page rather than an IP-driven variant of the homepage,
    # which the crawler would never see. See portal/markets.py.
    path('china-to-<slug:slug>/', portal_views.market_page, name='market_page'),
    path('shop/<slug:slug>/', portal_views.shop_product_detail, name='shop_product_detail'),

    # -------------------------------------------------------------------------
    # ARABIC PAGES
    # -------------------------------------------------------------------------
    # A language prefix (/ar/) rather than a subdomain or a query parameter: it is
    # the arrangement Google handles most reliably, it keeps all authority on one
    # domain, and it is unambiguous to a human reading the URL.
    #
    # These pair with the English originals through the hreflang tags in each
    # template — /ar/ with /, and /ar/services/ with /services/.
    # -------------------------------------------------------------------------
    path('ar/', portal_views.ar_home, name='ar_home'),
    path('ar/services/', portal_views.ar_services_page, name='ar_services_page'),

    # -------------------------------------------------------------------------
    # SEO ENDPOINTS (Sitemap & Robots.txt)
    # -------------------------------------------------------------------------
    # sitemap.xml helps search engines discover all public pages.
    # robots.txt guides crawlers on which pages to index or avoid.
    # -------------------------------------------------------------------------
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', portal_views.robots_txt, name='robots_txt'),

    # -------------------------------------------------------------------------
    # /favicon.ico
    # -------------------------------------------------------------------------
    # Browsers request /favicon.ico from the site root regardless of the <link
    # rel="icon"> tags in the page, and so do some crawlers and link-preview bots.
    # Without this route every one of those requests hit the Django 404 handler.
    # A permanent redirect to the real static file gets it cached by the browser
    # once and never asked for again.
    # -------------------------------------------------------------------------
    path('favicon.ico', portal_views.favicon_ico, name='favicon'),

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
    # -------------------------------------------------------------------------
    # JSON API
    # -------------------------------------------------------------------------
    # Mounted ABOVE the app routes so /api/v1/... can never be shadowed by a
    # page route added later. Browsable docs live at /api/v1/docs/ and the
    # machine-readable schema at /api/v1/schema/.
    # -------------------------------------------------------------------------
    # URL: /sw.js
    #
    # Served from the ROOT, not from /static/, and that is not a cosmetic
    # choice. A service worker may only control URLs at or below the path it is
    # served from, so /static/sw.js could only ever control /static/ - it would
    # register successfully and then do nothing at all for any real page. The
    # file itself lives in static/ with the rest of the front-end; this route
    # just serves it from a path whose scope covers the whole site.
    path('sw.js', service_worker, name='service_worker'),

    path('api/v1/', include('api.urls')),

    path('products/', include('products.urls')),

    # CUSTOMERS: Customer directory, CRUD operations, product assignments, quotations
    path('customers/', include('customers.urls')),

    # ORDERS: Order creation, editing, invoices, packing lists, payment tracking
    path('orders/', include('orders.urls')),

    # QUOTES: Quotations to customers, convertible into orders.
    path('quotes/', include('quotes.urls')),

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
