"""
URL configuration for the portal app.

The portal app serves two audiences:
  1. PUBLIC VISITORS: Anyone on the internet can view the marketing pages
     (homepage, portfolio, about, services, contact). These are the company's
     public-facing website pages.
  2. REGISTERED CUSTOMERS: Logged-in customers can access their personal
     dashboard, view their orders, browse products, check their ledger balance,
     update their profile, and request quotes.
  3. ADMIN USERS: Staff can manage customer accounts, handle product requests,
     and manage portfolio content from within the portal.

This module defines URL routes for all three areas, organized by section.

Django URL Routing Concepts Used:
  path()       - Modern URL pattern matcher. Uses simple string patterns and
                 angle-bracket converters like <int:order_id>.
  <int:...>    - URL converter that captures an integer and passes it to the
                 view as a keyword argument. Returns 404 for non-integers.
  name=        - Unique route name for use in templates, redirects, and the
                 {% url %} template tag. Never hardcode URLs in templates.
"""

# Import path() from django.urls. path() is the modern, recommended way to define
# URL routes in Django. It replaced the older url() function and is cleaner
# for most common routing needs.
from django.urls import path

# RedirectView is a built-in class-based view that issues an HTTP redirect.
# `pattern_name=` makes it redirect to whatever a named URL currently resolves
# to, so the target is never hardcoded.
from django.views.generic.base import RedirectView

# Import all view functions from this app's views.py module.
# The dot (.) means "from the current package" (the portal app directory).
# Each function handles a specific page or action within the portal.
from . import views

# =============================================================================
# URL PATTERNS FOR THE PORTAL APP
# =============================================================================
# urlpatterns is a Python list that Django scans from top to bottom.
# When a request arrives for a URL starting with /portal/ (as defined in the
# project's urls.py via include('portal.urls')), Django looks for a match here.
# Note: Some of these routes are ALSO duplicated at the ROOT level in the
# project's urls.py (front_page, portfolio_page, etc.) for cleaner public URLs.
# =============================================================================
urlpatterns = [
    # =========================================================================
    # LEGACY PUBLIC-PAGE REDIRECTS  (SEO — do not turn these back into views)
    # =========================================================================
    # The public marketing pages used to be served from BOTH /portal/<page>/ and
    # the root /<page>/. That was actively harmful:
    #
    #   1. Duplicate content. Both URLs returned HTTP 200 with the same HTML and
    #      each declared itself canonical, so Google saw two competing copies of
    #      every page and had to guess which to rank.
    #
    #   2. Every internal link pointed at the WRONG one. Django's reverse() takes
    #      the LAST pattern registered under a name, and portal.urls is included
    #      after the root routes — so `{% url 'faq_page' %}` in the navbar and
    #      footer resolved to /portal/faq/, not /faq/. sitemap.xml, built from the
    #      same reverse() call, submitted the /portal/ URLs too.
    #
    #   3. robots.txt disallows /portal/ (it is the logged-in customer area). So
    #      the site was submitting a sitemap of URLs it simultaneously forbade
    #      crawling, and giving the canonical root URLs zero internal links. Those
    #      pages could not rank.
    #
    # Serving a 301 here fixes all three at once: the root URL becomes the single
    # canonical address, reverse() now returns it (these redirect routes are
    # deliberately left unnamed), and any old inbound link or bookmark still lands
    # on the right page while passing its link equity to the canonical URL.
    # =========================================================================
    path('', RedirectView.as_view(pattern_name='front_page', permanent=True)),
    path('portfolio/', RedirectView.as_view(pattern_name='portfolio_page', permanent=True)),

    # -------------------------------------------------------------------------
    # CUSTOMER LOGIN: Portal Authentication
    # -------------------------------------------------------------------------
    # URL: /portal/login/
    # Shows the customer login form. Unlike /admin/login/ (for staff), this
    # login is for registered customers who want to access their personal
    # dashboard and order history. Uses a different template and redirect flow.
    # -------------------------------------------------------------------------
    path('login/', views.customer_login, name='portal_login'),

    # -------------------------------------------------------------------------
    # CUSTOMER LOGOUT: End Customer Session
    # -------------------------------------------------------------------------
    # URL: /portal/logout/
    # Logs the customer out of their portal session and redirects them to
    # the homepage. This clears the session cookie and requires re-login
    # to access protected pages again.
    # -------------------------------------------------------------------------
    path('logout/', views.customer_logout, name='portal_logout'),

    # -------------------------------------------------------------------------
    # CUSTOMER REGISTER: Create a New Customer Account
    # -------------------------------------------------------------------------
    # URL: /portal/register/
    # Shows a registration form for new customers to create an account.
    # After registration, the customer can log in and access the full portal.
    # This may require admin approval in some business flows.
    # -------------------------------------------------------------------------
    path('register/', views.customer_register, name='portal_register'),

    # -------------------------------------------------------------------------
    # CUSTOMER FORGOT PASSWORD: Request a Password Reset
    # -------------------------------------------------------------------------
    # URL: /portal/forgot-password/
    # Shows a form where the customer can enter their email to request a
    # password reset. A secure token is generated and (in production) emailed.
    # -------------------------------------------------------------------------
    path('forgot-password/', views.forgot_password, name='forgot_password'),

    # -------------------------------------------------------------------------
    # CUSTOMER FORGOT PASSWORD DONE: Confirmation Page
    # -------------------------------------------------------------------------
    # URL: /portal/forgot-password/done/
    # Displays a confirmation message after a password reset request.
    # In this teaching project, it also shows the token for easy testing.
    # -------------------------------------------------------------------------
    path('forgot-password/done/', views.forgot_password_done, name='forgot_password_done'),

    # -------------------------------------------------------------------------
    # CUSTOMER RESET PASSWORD: Set a New Password
    # -------------------------------------------------------------------------
    # URL: /portal/reset-password/?token=...
    # Validates the reset token and allows the customer to enter a new password.
    # The token must be valid, unused, and not expired (24-hour window).
    # -------------------------------------------------------------------------
    path('reset-password/', views.reset_password, name='reset_password'),

    # =========================================================================
    # CUSTOMER PORTAL (Login Required)
    # =========================================================================
    # These pages are only accessible to authenticated customers. They provide
    # self-service access to order tracking, product browsing, financial records,
    # and profile management. This reduces admin workload by letting customers
    # help themselves.

    # -------------------------------------------------------------------------
    # CUSTOMER DASHBOARD: Personal Home Page
    # -------------------------------------------------------------------------
    # URL: /portal/dashboard/
    # The customer's personal landing page after login. Shows a summary of
    # their account: recent orders, pending payments, total spent, order status
    # breakdown, and quick links to common actions.
    # -------------------------------------------------------------------------
    path('dashboard/', views.customer_dashboard, name='portal_dashboard'),

    # -------------------------------------------------------------------------
    # CUSTOMER ORDERS: View All Orders
    # -------------------------------------------------------------------------
    # URL: /portal/orders/
    # Lists all orders placed by the logged-in customer with status, date,
    # total amount, and tracking information. Customers can search and filter
    # their order history.
    # -------------------------------------------------------------------------
    path('orders/', views.customer_orders, name='portal_orders'),

    # -------------------------------------------------------------------------
    # CUSTOMER ORDER DETAIL: View a Specific Order
    # -------------------------------------------------------------------------
    # URL: /portal/orders/5/
    # Shows detailed information for a single order: line items, shipment
    # blocks, invoice, payment status, and tracking updates. The customer can
    # download the invoice and packing list from this page.
    # -------------------------------------------------------------------------
    path('orders/<int:order_id>/', views.customer_order_detail, name='portal_order_detail'),

    # -------------------------------------------------------------------------
    # CUSTOMER PRODUCTS: Browse Product Catalog
    # -------------------------------------------------------------------------
    # URL: /portal/products/
    # Displays the products available to this customer (their assigned catalog).
    # Customers can view product details, images, dimensions, and pricing.
    # They may also request quotes from this page.
    # -------------------------------------------------------------------------
    path('products/', views.customer_products, name='portal_products'),

    # AMAZON PRODUCTS: Browse Amazon-sourced products
    path('products/amazon/', views.customer_amazon_products, name='portal_amazon_products'),

    # PRODUCT DETAIL: One product in full — gallery, specs, and the free-form
    # attribute list staff maintain on it.
    #
    # Listed AFTER the two literal 'products/<word>/' routes above so 'amazon' and
    # 'noon' can never be swallowed by <int:product_id>. They could not be anyway
    # (the converter only matches digits), but keeping literal paths above dynamic
    # ones is the habit that stops the next addition from breaking them.
    path('products/<int:product_id>/', views.customer_product_detail,
         name='portal_product_detail'),

    # NOON PRODUCTS: Browse Noon-sourced products
    path('products/noon/', views.customer_noon_products, name='portal_noon_products'),

    # MARKETPLACE: Browse Amazon + Noon products together
    path('marketplace/', views.customer_marketplace, name='portal_marketplace'),

    # -------------------------------------------------------------------------
    # CUSTOMER LEDGER: View Financial History
    # -------------------------------------------------------------------------
    # URL: /portal/ledger/
    # Shows the customer's financial transaction history: all orders, payments
    # made, credits received, and the current running balance. This gives
    # customers transparency into their account status.
    # -------------------------------------------------------------------------
    path('ledger/', views.customer_ledger, name='portal_ledger'),

    # -------------------------------------------------------------------------
    # CUSTOMER PROFILE: Manage Account Details
    # -------------------------------------------------------------------------
    # URL: /portal/profile/
    # Allows the customer to update their personal information: name, phone,
    # email, password, shipping address, and company details. Some fields may
    # be read-only if managed by the admin.
    # -------------------------------------------------------------------------
    path('profile/', views.customer_profile, name='portal_profile'),

    # -------------------------------------------------------------------------
    # REQUEST QUOTE: Ask for a Price Quote
    # -------------------------------------------------------------------------
    # URL: /portal/request-quote/
    # Shows a form where the customer can request a quotation for products
    # they want to purchase. They select products, specify quantities, and
    # submit the request. The admin reviews the request and sends back a quote.
    # -------------------------------------------------------------------------
    path('request-quote/', views.request_quote, name='request_quote'),

    # -------------------------------------------------------------------------
    # MY REQUESTS: View Quote Request History
    # -------------------------------------------------------------------------
    # URL: /portal/my-requests/
    # Lists all quote requests the customer has submitted with their status:
    # pending (waiting for admin review), quoted (admin sent a price), or
    # rejected. The customer can view the details of each request.
    # -------------------------------------------------------------------------
    path('my-requests/', views.my_requests, name='my_requests'),

    # =========================================================================
    # SHOPPING CART & CHECKOUT (Login Required)
    # =========================================================================
    path('cart/', views.cart_view, name='portal_cart'),
    path('cart/add/', views.add_to_cart, name='portal_add_to_cart'),
    path('cart/remove/<int:item_id>/', views.remove_from_cart, name='portal_remove_from_cart'),
    path('cart/update/<int:item_id>/', views.update_cart_quantity, name='portal_update_cart_quantity'),
    path('checkout/', views.checkout_view, name='portal_checkout'),
    path('checkout/confirm/', views.checkout_confirm, name='portal_checkout_confirm'),

    # =========================================================================
    # CUSTOMER SUPPORT TICKETS (Login Required)
    # =========================================================================
    path('notifications/', views.customer_notifications, name='portal_notifications'),
    path('support/', views.customer_support_list, name='portal_support_list'),
    path('support/new/', views.customer_support_create, name='portal_support_create'),
    path('support/<int:ticket_id>/', views.customer_support_detail, name='portal_support_detail'),

    # =========================================================================
    # ADMIN CUSTOMER MANAGEMENT (Staff/Admin Only)
    # =========================================================================
    # These pages are for admin users to manage the customer base. They
    # complement the main admin panel by providing customer-specific tools
    # within the portal interface.

    # -------------------------------------------------------------------------
    # ADMIN CUSTOMER LIST: View All Registered Customers
    # -------------------------------------------------------------------------
    # URL: /portal/admin/customers/
    # Shows a table of all customers registered in the portal with their
    # account status, contact info, total orders, and balance. Admins can
    # search, filter, and perform actions on multiple customers.
    # -------------------------------------------------------------------------
    path('admin/customers/', views.admin_customer_list, name='admin_customer_list'),

    # -------------------------------------------------------------------------
    # ADMIN ADD CUSTOMER: Create a New Customer Account
    # -------------------------------------------------------------------------
    # URL: /portal/admin/customers/add/
    # Shows a form to create a new customer account manually. The admin enters
    # the customer's details and can set an initial password. This is used when
    # a customer calls to register instead of using the public registration page.
    # -------------------------------------------------------------------------
    path('admin/customers/add/', views.admin_customer_add, name='admin_customer_add'),

    # -------------------------------------------------------------------------
    # ADMIN EDIT CUSTOMER: Modify Customer Details
    # -------------------------------------------------------------------------
    # URL: /portal/admin/customers/5/edit/
    # Opens a pre-filled form to edit a customer's profile. The admin can
    # update contact info, change the password, activate/deactivate the account,
    # and modify any business-relevant customer data.
    # -------------------------------------------------------------------------
    path('admin/customers/<int:customer_id>/edit/', views.admin_customer_edit, name='admin_customer_edit'),

    # -------------------------------------------------------------------------
    # ADMIN DELETE CUSTOMER: Remove a Customer Account
    # -------------------------------------------------------------------------
    # URL: /portal/admin/customers/5/delete/
    # Handles the deletion of a customer account. This usually requires
    # confirmation and may archive the customer's data rather than permanently
    # deleting it for compliance and record-keeping purposes.
    # -------------------------------------------------------------------------
    path('admin/customers/<int:customer_id>/delete/', views.admin_customer_delete, name='admin_customer_delete'),

    # =========================================================================
    # ADMIN PRODUCT REQUESTS MANAGEMENT
    # =========================================================================
    # These pages handle quote requests submitted by customers through the
    # "Request Quote" feature. The admin reviews, processes, and responds to them.

    # -------------------------------------------------------------------------
    # ADMIN REQUEST LIST: View All Quote Requests
    # -------------------------------------------------------------------------
    # URL: /portal/admin/requests/
    # Shows a list of all customer quote requests with their status, customer
    # name, date submitted, and requested products. Admins can filter by status
    # (pending, quoted, rejected) to prioritize their work.
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # WEBSITE LEADS (contact-form enquiries)
    # -------------------------------------------------------------------------
    # URL: /portal/admin/leads/
    # Enquiries submitted through the public contact form and the homepage hero
    # form. These previously existed only in Django's stock /admin/, which meant
    # nobody saw them — this is the top of the sales funnel, so it belongs in the
    # back-office next to everything else the team works from.
    # -------------------------------------------------------------------------
    path('admin/leads/', views.admin_lead_list, name='admin_lead_list'),
    path('admin/leads/<int:lead_id>/toggle-read/', views.admin_lead_toggle_read, name='admin_lead_toggle_read'),

    # Bulk clear the spam tab, or release one message back to the inbox.
    # Clearing one row at a time is why spam accumulates.
    path('admin/leads/spam-action/', views.admin_lead_spam_action, name='admin_lead_spam_action'),

    # Permanently delete one enquiry or a selection of them (POST only).
    path('admin/leads/delete/', views.admin_lead_delete, name='admin_lead_delete'),

    path('admin/requests/', views.admin_request_list, name='admin_request_list'),

    # -------------------------------------------------------------------------
    # ADMIN REQUEST DETAIL: Review a Specific Quote Request
    # -------------------------------------------------------------------------
    # URL: /portal/admin/requests/12/
    # Shows the full details of a quote request: customer information,
    # requested products with quantities, special instructions, and any attached
    # files. The admin can generate a quote from this page or reject the request.
    # -------------------------------------------------------------------------
    path('admin/requests/<int:request_id>/', views.admin_request_detail, name='admin_request_detail'),

    # =========================================================================
    # ADMIN PORTFOLIO MANAGEMENT
    # =========================================================================
    # These pages allow the admin to manage the content displayed on the
    # public portfolio page. They can add new projects, update descriptions,
    # upload images, and remove outdated entries.

    # -------------------------------------------------------------------------
    # ADMIN PORTFOLIO LIST: View All Portfolio Items
    # -------------------------------------------------------------------------
    # URL: /portal/admin/portfolio/
    # Shows a table of all portfolio items (projects, case studies) with
    # their title, thumbnail, status (active/inactive), and order. Admins can
    # reorder, edit, or delete items from this page.
    # -------------------------------------------------------------------------
    path('admin/portfolio/', views.admin_portfolio_list, name='admin_portfolio_list'),

    # -------------------------------------------------------------------------
    # ADMIN PORTFOLIO ADD: Create a New Portfolio Item
    # -------------------------------------------------------------------------
    # URL: /portal/admin/portfolio/add/
    # Shows a form to add a new project to the portfolio. The admin enters
    # the project title, description, client name, completion date, and uploads
    # images to showcase the work.
    # -------------------------------------------------------------------------
    path('admin/portfolio/add/', views.admin_portfolio_add, name='admin_portfolio_add'),

    # -------------------------------------------------------------------------
    # ADMIN PORTFOLIO EDIT: Update an Existing Item
    # -------------------------------------------------------------------------
    # URL: /portal/admin/portfolio/3/edit/
    # Opens a pre-filled form to edit a portfolio item. The admin can update
    # any field, replace images, or change the item's display order.
    # -------------------------------------------------------------------------
    path('admin/portfolio/<int:item_id>/edit/', views.admin_portfolio_edit, name='admin_portfolio_edit'),

    # -------------------------------------------------------------------------
    # ADMIN PORTFOLIO DELETE: Remove a Portfolio Item
    # -------------------------------------------------------------------------
    # URL: /portal/admin/portfolio/3/delete/
    # Handles the deletion of a portfolio item. This removes the item from
    # the public portfolio page. Usually requires confirmation.
    # -------------------------------------------------------------------------
    path('admin/portfolio/<int:item_id>/delete/', views.admin_portfolio_delete, name='admin_portfolio_delete'),

    # -------------------------------------------------------------------------
    # ADMIN PORTFOLIO REORDER: Drag-and-drop reorder
    # -------------------------------------------------------------------------
    # URL: /portal/admin/portfolio/reorder/
    # AJAX endpoint that updates display_order for all portfolio items based on
    # a new sequence sent by the frontend drag-and-drop handler.
    # -------------------------------------------------------------------------
    path('admin/portfolio/reorder/', views.admin_portfolio_reorder, name='admin_portfolio_reorder'),

    # -------------------------------------------------------------------------
    # NOTIFICATION COUNTS: Unread requests and pending orders
    # -------------------------------------------------------------------------
    # URL: /portal/notification-counts/
    # AJAX endpoint that returns the count of pending product requests and
    # unplaced orders for the admin notification bell badge.
    #
    # NOTE: this MUST NOT reuse '/portal/notifications/' — that path is already
    # claimed above by the customer-facing `portal_notifications` page, which is
    # @customer_required. Sharing the path made this admin endpoint unreachable
    # and made the admin bell poll hit the customer page, raising PermissionDenied
    # (403) for every staff/admin user on a 60s loop. Keep the paths distinct.
    # -------------------------------------------------------------------------
    path('notification-counts/', views.notification_counts, name='notification_counts'),

    # =========================================================================
    # SEO / MARKETING PAGES (No login required)
    # =========================================================================
    # These pages improve the site's visibility and credibility for search
    # engines and prospective customers.

    # -------------------------------------------------------------------------
    # Legacy redirects to the canonical root URLs (/testimonials/, /faq/).
    # See the long note at the top of this file for why these are 301s and not
    # views. The canonical routes live in logistic_manager/urls.py.
    # -------------------------------------------------------------------------
    path('testimonials/', RedirectView.as_view(pattern_name='testimonials_page', permanent=True)),
    path('faq/', RedirectView.as_view(pattern_name='faq_page', permanent=True)),
]
