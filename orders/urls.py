"""
URL configuration for the orders app.

This module defines all URL routes related to order management:
listing orders, creating new orders, editing existing orders, confirming orders,
viewing order details, deleting orders, generating invoices, duplicating orders,
toggling payment status, marking orders as placed, generating quotations in Excel,
importing quotations, and managing packing lists.

Django URL Routing Concepts Used:
  path()          - Modern URL pattern matcher. Uses simple string patterns and
                    angle-bracket converters like <int:order_id>.
  <int:...>       - URL converter that captures an integer and passes it to
                    the view as a keyword argument. Automatically returns 404
                    if the URL segment is not a valid integer.
  name=           - Assigns a unique name to each route. Templates and views
                    reference URLs by name (e.g., {% url 'order_detail' 5 %})
                    instead of hardcoding the path. This makes the code resilient
                    to URL changes.
"""

# Import path() from django.urls. path() is the modern, recommended way to define
# URL routes in Django. It replaced the older url() function (now called re_path)
# and is cleaner for most common routing needs.
from django.urls import path

# Import all view functions from this app's views.py module.
# The dot (.) means "from the current package" (the orders app directory).
# Each function handles a specific type of request for order management.
from . import views

# =============================================================================
# URL PATTERNS FOR ORDER MANAGEMENT
# =============================================================================
# urlpatterns is a Python list that Django scans from top to bottom.
# When a request arrives for a URL starting with /orders/ (as defined in the
# project's urls.py via include('orders.urls')), Django looks for a match here.
#
# IMPORTANT: Order matters. Django returns the FIRST matching route. More
# specific routes should be placed before generic ones. For example, 'add/'
# must come before '' because '' matches everything.
# =============================================================================
urlpatterns = [
    # -------------------------------------------------------------------------
    # ROOT: Order List Page
    # -------------------------------------------------------------------------
    # URL: /orders/
    # The default page for the Orders section. Displays a table of all orders
    # with search, filter, sort, pagination, and status indicators. This is the
    # central hub for the logistics business to track all customer shipments.
    # -------------------------------------------------------------------------
    path('', views.order_list, name='order_list'),

    # -------------------------------------------------------------------------
    # ADD: Create a New Order
    # -------------------------------------------------------------------------
    # URL: /orders/add/
    # Shows a multi-step form to create a new order: select customer, add
    # products, set quantities, calculate totals (CBM, weight, cost). This is
    # the core transaction flow of the logistics business.
    # -------------------------------------------------------------------------
    path('add/', views.add_order, name='add_order'),

    # -------------------------------------------------------------------------
    # EDIT: Modify an Existing Order
    # -------------------------------------------------------------------------
    # URL: /orders/edit/5/
    # Opens an existing order in edit mode. The admin can change the customer,
    # add/remove products, update quantities, and recalculate totals.
    # The <int:order_id> parameter identifies which order to edit.
    # -------------------------------------------------------------------------
    path('edit/<int:order_id>/', views.edit_order, name='edit_order'),

    # -------------------------------------------------------------------------
    # CONFIRM: Finalize an Order
    # -------------------------------------------------------------------------
    # URL: /orders/confirm/5/
    # Marks an order as confirmed and locks it from further editing. This is
    # a critical business step: once confirmed, the order is sent to the
    # warehouse/supplier for processing and shipment preparation.
    # -------------------------------------------------------------------------
    path('confirm/<int:order_id>/', views.confirm_order, name='confirm_order'),

    # -------------------------------------------------------------------------
    # DETAIL: View Order Details
    # -------------------------------------------------------------------------
    # URL: /orders/detail/5/
    # Shows a read-only, detailed view of an order: customer info, product
    # line items, shipment blocks, pricing breakdown, status, and history.
    # This is the page customers see and what admins print/share.
    # -------------------------------------------------------------------------
    path('detail/<int:order_id>/', views.order_detail, name='order_detail'),

    # -------------------------------------------------------------------------
    # DELETE: Remove an Order
    # -------------------------------------------------------------------------
    # URL: /orders/delete/5/
    # Handles deletion of an order. Usually requires a confirmation dialog
    # to prevent accidental deletion of important business records.
    # -------------------------------------------------------------------------
    path('delete/<int:order_id>/', views.delete_order, name='delete_order'),

    # -------------------------------------------------------------------------
    # INVOICE: Generate Order Invoice
    # -------------------------------------------------------------------------
    # URL: /orders/invoice/5/
    # Generates a professional invoice document (PDF or HTML) for the order.
    # The invoice includes company details, customer info, line items,
    # totals, payment terms, and branding. This is sent to the customer
    # for payment processing.
    # -------------------------------------------------------------------------
    path('invoice/<int:order_id>/', views.order_invoice, name='order_invoice'),

    # -------------------------------------------------------------------------
    # DUPLICATE: Copy an Existing Order
    # -------------------------------------------------------------------------
    # URL: /orders/duplicate/5/
    # Creates a new order by copying all details from an existing order.
    # This is useful for repeat customers who place the same or similar orders
    # regularly, saving time on data entry.
    # -------------------------------------------------------------------------
    path('duplicate/<int:order_id>/', views.duplicate_order, name='duplicate_order'),

    # -------------------------------------------------------------------------
    # PAYMENT STATUS: Toggle Payment State
    # -------------------------------------------------------------------------
    # URL: /orders/payment-status/5/
    # Toggles whether the order is marked as paid or unpaid. This is typically
    # an AJAX endpoint that updates the database and returns a JSON response
    # without reloading the page.
    # -------------------------------------------------------------------------
    path('payment-status/<int:order_id>/', views.toggle_payment_status, name='toggle_payment_status'),

    # -------------------------------------------------------------------------
    # TOGGLE PLACED: Mark Order as Placed with Supplier
    # -------------------------------------------------------------------------
    # URL: /orders/toggle-placed/5/
    # Toggles the is_placed flag on the order. "Placed" means the order has
    # been officially submitted to the supplier/warehouse for fulfillment.
    # This is a key workflow status in the logistics pipeline.
    # -------------------------------------------------------------------------
    path('toggle-placed/<int:order_id>/', views.toggle_placed, name='toggle_placed'),

    # -------------------------------------------------------------------------
    # QUOTATION EXCEL: Export Quotation Spreadsheet
    # -------------------------------------------------------------------------
    # URL: /orders/quotation-excel/
    # Generates an Excel file containing the order details formatted as a
    # quotation. This is sent to customers for approval before the order
    # is confirmed and placed.
    # -------------------------------------------------------------------------
    path('quotation-excel/', views.generate_quotation_excel, name='generate_quotation_excel'),

    # -------------------------------------------------------------------------
    # IMPORT QUOTATION: Import Order from Excel
    # -------------------------------------------------------------------------
    # URL: /orders/import-quotation/
    # Accepts an Excel quotation file and creates a new Order from it.
    # This is useful when customers send quotations back with modifications
    # and the admin needs to import them into the system.
    # -------------------------------------------------------------------------
    path('import-quotation/', views.import_quotation_excel, name='import_quotation_excel'),

    # -------------------------------------------------------------------------
    # PACKING LIST: View All Packing Lists
    # -------------------------------------------------------------------------
    # URL: /orders/packing-list/
    # Displays a list of all packing lists (shipment summaries) across orders.
    # A packing list is a document that lists the contents of each shipment
    # block for customs and freight forwarding.
    # -------------------------------------------------------------------------
    path('packing-list/', views.packing_list_view, name='packing_list'),

    # -------------------------------------------------------------------------
    # PACKING LIST PRINT: Print Packing List for a Specific Order
    # -------------------------------------------------------------------------
    # URL: /orders/packing-list/5/
    # Generates a printable packing list for a specific order. This document
    # is used by shipping companies, customs, and warehouse staff to verify
    # the contents of a shipment. Includes product names, quantities, weights,
    # dimensions, and carton details.
    # -------------------------------------------------------------------------
    path('packing-list/<int:order_id>/', views.packing_list_print, name='packing_list_print'),

    # -------------------------------------------------------------------------
    # EXPORT: Export Order to Excel
    # -------------------------------------------------------------------------
    # URL: /orders/export/5/
    # Generates an Excel file containing the full details of a specific order.
    # This is useful for record keeping, sending to accountants, or importing
    # into other business systems.
    # -------------------------------------------------------------------------
    path('export/<int:order_id>/', views.order_excel_export, name='order_excel_export'),

    # -------------------------------------------------------------------------
    # REPORTS: Business Analytics Reports with Charts
    # -------------------------------------------------------------------------
    # URL: /orders/reports/
    # Displays comprehensive business reports with interactive charts:
    # revenue over time, top products, top customers, shipping method distribution.
    # Supports date range filtering.
    # -------------------------------------------------------------------------
    path('reports/', views.reports, name='reports'),

    # -------------------------------------------------------------------------
    # REPORTS EXPORT EXCEL: Download report as Excel
    # -------------------------------------------------------------------------
    # URL: /orders/reports/export-excel/?start_date=...&end_date=...
    # -------------------------------------------------------------------------
    path('reports/export-excel/', views.reports_export_excel, name='reports_export_excel'),

    # -------------------------------------------------------------------------
    # REPORTS EXPORT PDF: Download report as PDF
    # -------------------------------------------------------------------------
    # URL: /orders/reports/export-pdf/?start_date=...&end_date=...
    # -------------------------------------------------------------------------
    path('reports/export-pdf/', views.reports_export_pdf, name='reports_export_pdf'),

    # -------------------------------------------------------------------------
    # ADMIN STATS: Real-time KPI counts for the admin stats bar
    # -------------------------------------------------------------------------
    # URL: /orders/admin-stats/
    # AJAX endpoint that returns product, customer, order, ledger counts and
    # pending requests/orders for the mini stat widgets shown on every admin page.
    # -------------------------------------------------------------------------
    path('admin-stats/', views.admin_stats, name='admin_stats'),

    # -------------------------------------------------------------------------
    # AMAZON ORDERS: Orders containing Amazon-sourced products
    # -------------------------------------------------------------------------
    # URL: /orders/amazon/
    # -------------------------------------------------------------------------
    path('amazon/', views.amazon_order_list, name='amazon_order_list'),

    # -------------------------------------------------------------------------
    # DOWNLOAD LABELS ZIP: Download all ready-to-ship labels for an order
    # -------------------------------------------------------------------------
    # URL: /orders/labels-zip/5/
    # -------------------------------------------------------------------------
    path('labels-zip/<int:order_id>/', views.download_order_labels_zip, name='download_order_labels_zip'),
]
