"""
URL configuration for the customers app.

This module defines all URL routes related to customer management:
listing customers, adding new customers, editing existing ones, deleting,
viewing a customer's products, generating quotations, and assigning/removing
products from a customer's catalog.

Django URL Routing Concepts Used:
  path()      - Modern URL pattern matcher. Uses simple string patterns and
                angle-bracket converters like <int:customer_id>.
  include()   - Not used here (this is an app-level urls.py), but the parent
                project urls.py includes this module with path('customers/', include(...)).
  name=       - Gives each route a unique name. Templates and views reference
                URLs by name (e.g., {% url 'add_customer' %}) instead of
                hardcoding the path. This makes URLs easy to change later.
  <int:...>   - A URL converter that captures an integer from the URL and passes
                it as a keyword argument to the view function.
"""

# Import the path() function from django.urls. path() is the modern,
# recommended way to define URL routes in Django (replaces the older url() function).
from django.urls import path

# Import all view functions from this app's views.py module.
# The dot (.) means "from the current package/directory".
# Each function in views.py handles one type of HTTP request for this app.
from . import views

# =============================================================================
# URL PATTERNS FOR CUSTOMER MANAGEMENT
# =============================================================================
# urlpatterns is a list that Django scans from top to bottom. When a request
# arrives for a URL starting with /customers/ (as defined in the project's
# urls.py include()), Django looks for a match in this list.
#
# URL pattern:  path('add/', views.add_customer, name='add_customer')
#   - 'add/'   : The relative URL path (after the /customers/ prefix).
#   - views.add_customer: The Python function that handles the request.
#   - name='...': A unique identifier used in templates and redirects.
#
# URL converters: <int:customer_id>
#   - int:      Ensures the captured value is an integer. Django returns 404
#               if the URL contains non-numeric characters here.
#   - customer_id: The variable name passed to the view function as a keyword
#                  argument. So views.delete_customer(request, customer_id=5).
# =============================================================================
urlpatterns = [
    # -------------------------------------------------------------------------
    # ROOT: Customer List Page
    # -------------------------------------------------------------------------
    # URL: /customers/
    # Displays a table of all customers with search, filter, and pagination.
    # This is the default landing page when someone visits the Customers section.
    # -------------------------------------------------------------------------
    path('', views.customer_list, name='customer_list'),

    # -------------------------------------------------------------------------
    # ADD: Create a New Customer
    # -------------------------------------------------------------------------
    # URL: /customers/add/
    # Shows a form to enter customer details (name, phone, email, address, etc.)
    # and saves the new Customer record to the database.
    # -------------------------------------------------------------------------
    path('add/', views.add_customer, name='add_customer'),

    # -------------------------------------------------------------------------
    # EDIT: Update an Existing Customer
    # -------------------------------------------------------------------------
    # URL: /customers/edit/
    # Note: This route does NOT include a customer_id parameter.
    # It likely uses a POST parameter or session to identify which customer
    # to edit, or it might be a general edit form that handles the selection
    # internally. Some implementations use POST data to determine the customer.
    # -------------------------------------------------------------------------
    path('edit/', views.edit_customer, name='edit_customer'),

    # -------------------------------------------------------------------------
    # DELETE: Remove a Customer
    # -------------------------------------------------------------------------
    # URL: /customers/delete/5/
    # The <int:customer_id> converter captures the customer's primary key from
    # the URL and passes it to the view. The view looks up the customer,
    # confirms deletion (or handles it via POST), and removes the record.
    # -------------------------------------------------------------------------
    path('delete/<int:customer_id>/', views.delete_customer, name='delete_customer'),

    # -------------------------------------------------------------------------
    # CUSTOMER PRODUCTS: View Products Assigned to a Customer
    # -------------------------------------------------------------------------
    # URL: /customers/5/products/
    # Shows which products from the catalog have been assigned to this specific
    # customer. This is useful for per-customer pricing and catalog management.
    # -------------------------------------------------------------------------
    path('<int:customer_id>/products/', views.customer_products, name='customer_products'),

    # -------------------------------------------------------------------------
    # CUSTOMER QUOTATION: Generate a Price Quote for a Customer
    # -------------------------------------------------------------------------
    # URL: /customers/5/quotation/
    # Generates a quotation document (likely a PDF or Excel export) listing
    # products and prices tailored for this customer. This is a key sales tool
    # in the logistics business.
    # -------------------------------------------------------------------------
    path('<int:customer_id>/quotation/', views.customer_quotation, name='customer_quotation'),

    # -------------------------------------------------------------------------
    # ASSIGN PRODUCT: Link a Product to a Customer
    # -------------------------------------------------------------------------
    # URL: /customers/5/assign-product/
    # Associates a product from the main catalog with this customer's
    # personal catalog. This allows per-customer pricing and custom product lists.
    # -------------------------------------------------------------------------
    path('<int:customer_id>/assign-product/', views.assign_product, name='assign_product'),

    # -------------------------------------------------------------------------
    # REMOVE PRODUCT: Unlink a Product from a Customer
    # -------------------------------------------------------------------------
    # URL: /customers/5/remove-product/12/
    # Removes the association between a specific customer and a specific product.
    # Two URL parameters: customer_id (who) and product_id (which product).
    # -------------------------------------------------------------------------
    path('<int:customer_id>/remove-product/<int:product_id>/', views.remove_product, name='remove_product'),
]
