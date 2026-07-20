"""
URL configuration for the khata app.

"Khata" (خاتہ) is an Urdu/Hindi word meaning "account book" or "ledger."
In the context of this logistics business, the khata app manages the financial
ledger — tracking money owed by customers, payments received, and running balances.

This module defines URL routes for:
  - The ledger home page (summary of all customer accounts)
  - Individual customer ledger pages (detailed transaction history)
  - Printable ledger views (for sharing or physical records)
  - Adding new ledger entries (payments, debits, credits)
  - Deleting ledger entries (for corrections)

Django URL Routing Concepts Used:
  path()       - Modern URL pattern matcher. Replaces regex-based routing.
  <int:...>    - URL converter that captures an integer and passes it as a
                 keyword argument to the view. Returns 404 for non-integers.
  name=        - Unique route name for use in templates and redirects.
"""

# Import path() from django.urls. path() is the modern, clean way to define
# URL routes in Django. It uses simple string patterns and angle-bracket
# converters instead of regular expressions.
from django.urls import path

# Import all view functions from this app's views.py module.
# The dot (.) means "from the current package" (the khata app directory).
# Each function handles a specific financial/accounting operation.
from . import views

# =============================================================================
# URL PATTERNS FOR LEDGER / ACCOUNTING MANAGEMENT
# =============================================================================
# urlpatterns is a Python list that Django scans from top to bottom.
# When a request arrives for a URL starting with /khata/ (as defined in the
# project's urls.py via include('khata.urls')), Django looks for a match here.
#
# Order matters: Django returns the FIRST matching route. More specific routes
# should be placed before generic ones to prevent unintended matches.
# =============================================================================
urlpatterns = [
    # -------------------------------------------------------------------------
    # ROOT: Ledger Home Page
    # -------------------------------------------------------------------------
    # URL: /khata/
    # The main landing page for the accounting/ledger section. Displays a
    # summary of all customers with their current balances, recent transactions,
    # and links to individual customer ledgers. This gives the business owner
    # a quick overview of who owes money and how much.
    # -------------------------------------------------------------------------
    path('', views.ledger_home, name='ledger_home'),

    # -------------------------------------------------------------------------
    # CUSTOMER LEDGER: View Transactions for a Specific Customer
    # -------------------------------------------------------------------------
    # URL: /khata/customer/5/
    # Shows a detailed chronological list of all financial transactions for a
    # specific customer: orders placed, payments received, credits given,
    # and the running balance. This is the core accounting view for each client.
    # The <int:customer_id> parameter identifies which customer's ledger to show.
    # -------------------------------------------------------------------------
    path('customer/<int:customer_id>/', views.customer_ledger, name='customer_ledger'),

    # -------------------------------------------------------------------------
    # PRINT LEDGER: Printable Version of Customer Ledger
    # -------------------------------------------------------------------------
    # URL: /khata/customer/5/print/
    # Generates a printer-friendly version of the customer's ledger, usually
    # in a clean HTML layout or PDF format. This is used for sharing with
    # customers, accountants, or for physical record keeping. The layout is
    # optimized for printing (no navigation, minimal styling, page breaks).
    # -------------------------------------------------------------------------
    path('customer/<int:customer_id>/print/', views.print_ledger, name='print_ledger'),

    # -------------------------------------------------------------------------
    # EXPORT PDF: Date-Range Account Statement
    # -------------------------------------------------------------------------
    # URL: /khata/customer/5/export-pdf/?from=2026-01-01&to=2026-06-30
    # Downloads the customer's ledger as a PDF statement. Both query parameters
    # are optional — omitting them exports the complete ledger. When a start date
    # is supplied the PDF includes an opening-balance row so the statement still
    # reconciles against the customer's true position.
    # -------------------------------------------------------------------------
    path('customer/<int:customer_id>/export-pdf/', views.export_ledger_pdf, name='export_ledger_pdf'),

    # -------------------------------------------------------------------------
    # ADD ENTRY: Create a New Ledger Transaction
    # -------------------------------------------------------------------------
    # URL: /khata/add/
    # Shows a form to add a new financial entry to a customer's ledger.
    # Entries can be of various types: payment received, debit (charge),
    # credit (refund), or adjustment. Each entry affects the customer's
    # running balance. This is how the business records all money movements.
    # -------------------------------------------------------------------------
    path('add/', views.add_entry, name='add_entry'),

    # -------------------------------------------------------------------------
    # DELETE ENTRY: Remove a Ledger Transaction
    # -------------------------------------------------------------------------
    # URL: /khata/delete/12/
    # Removes a specific ledger entry from the database. This is typically
    # used for correcting mistakes (e.g., a duplicate entry or wrong amount).
    # The <int:entry_id> parameter identifies the LedgerEntry record to delete.
    # Usually requires confirmation to prevent accidental data loss.
    # -------------------------------------------------------------------------
    path('delete/<int:entry_id>/', views.delete_entry, name='delete_entry'),
]
