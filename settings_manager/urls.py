"""
URL configuration for the settings_manager app.

This module handles application-wide configuration settings that affect how
the logistics business operates. Unlike Django's settings.py (which controls
the framework), settings_manager stores business-specific settings in the
database so admins can change them without redeploying code.

This module defines URL routes for:
  - General company settings (name, phone, address, currency, logo, etc.)
  - Shipping calculator configuration (rates, formulas, zones)
  - Shipping company management (CRUD for freight forwarders, couriers)
  - Shipping rate sheets (download/upload rate spreadsheets)

Django URL Routing Concepts Used:
  path()         - Modern URL pattern matcher. Uses simple string patterns and
                   angle-bracket converters.
  <int:...>      - URL converter that captures an integer and passes it to the
                   view as a keyword argument. Returns 404 for non-integer values.
  name=          - Unique route name for use in templates and redirects.
"""

# Import path() from django.urls. path() is the modern, recommended way to define
# URL routes in Django. It is cleaner than the older regex-based url() function.
from django.urls import path

# Import all view functions from this app's views.py module.
# The dot (.) means "from the current package" (the settings_manager app directory).
# Each function handles a specific configuration management task.
from . import views

# =============================================================================
# URL PATTERNS FOR SETTINGS MANAGEMENT
# =============================================================================
# urlpatterns is a Python list that Django scans from top to bottom.
# When a request arrives for a URL starting with /settings/ (as defined in
# the project's urls.py via include('settings_manager.urls')), Django looks
# for a match here.
# =============================================================================
urlpatterns = [
    # -------------------------------------------------------------------------
    # ROOT: General Company Settings Page
    # -------------------------------------------------------------------------
    # URL: /settings/
    # The main settings page where the admin can configure company-wide
    # information: company name, logo, phone number, email, address, currency,
    # default tax rates, invoice numbering, and other business parameters.
    # These settings are stored in the database and used throughout the app
    # (in invoices, quotations, emails, and the public website).
    # -------------------------------------------------------------------------
    path('', views.settings_view, name='settings'),

    # -------------------------------------------------------------------------
    # SHIPPING CALCULATOR: Configure Shipping Cost Calculator
    # -------------------------------------------------------------------------
    # URL: /settings/shipping-calculator/
    # Manages the shipping cost estimation tool. The admin can configure
    # rate formulas, weight tiers, CBM tiers, zone pricing, and shipping
    # methods. This calculator is used when creating orders to give customers
    # accurate shipping cost estimates before they confirm the order.
    # -------------------------------------------------------------------------
    path('shipping-calculator/', views.shipping_calculator_view, name='shipping_calculator'),

    # -------------------------------------------------------------------------
    # SHIPPING COMPANIES: List All Freight Forwarders / Couriers
    # -------------------------------------------------------------------------
    # URL: /settings/shipping-companies/
    # Displays a list of all shipping companies the logistics business works with:
    # DHL, FedEx, Aramex, local freight forwarders, etc. For each company,
    # the admin can view contact info, rates, and active status.
    # -------------------------------------------------------------------------
    path('shipping-companies/', views.shipping_company_list, name='shipping_company_list'),

    # -------------------------------------------------------------------------
    # ADD SHIPPING COMPANY: Create a New Shipping Company Record
    # -------------------------------------------------------------------------
    # URL: /settings/shipping-companies/add/
    # Shows a form to add a new shipping company to the system. The admin
    # enters the company name, contact details, API credentials (if applicable),
    # and initial rate information.
    # -------------------------------------------------------------------------
    path('shipping-companies/add/', views.shipping_company_add, name='shipping_company_add'),

    # -------------------------------------------------------------------------
    # EDIT SHIPPING COMPANY: Modify an Existing Company
    # -------------------------------------------------------------------------
    # URL: /settings/shipping-companies/5/edit/
    # Opens a pre-filled form to edit a shipping company's details. The
    # <int:company_id> parameter identifies which shipping company to modify.
    # -------------------------------------------------------------------------
    path('shipping-companies/<int:company_id>/edit/', views.shipping_company_edit, name='shipping_company_edit'),

    # -------------------------------------------------------------------------
    # SAVE RATES: Update Shipping Rates for a Company
    # -------------------------------------------------------------------------
    # URL: /settings/shipping-companies/5/save-rates/
    # A dedicated endpoint for updating the rate structure of a shipping company.
    # This might be called via AJAX from a rate table editor. The rates could
    # include per-kg costs, per-CBM costs, zone-based pricing, and surcharges.
    # -------------------------------------------------------------------------
    path('shipping-companies/<int:company_id>/save-rates/', views.shipping_company_save_rates, name='shipping_company_save_rates'),

    # -------------------------------------------------------------------------
    # DOWNLOAD RATE SHEET: Export Company Rates to Excel
    # -------------------------------------------------------------------------
    # URL: /settings/shipping-companies/5/sheet/download/
    # Generates and downloads an Excel file containing the current rate structure
    # for a shipping company. This can be shared with the company for verification
    # or used as a backup before making rate changes.
    # -------------------------------------------------------------------------
    path('shipping-companies/<int:company_id>/sheet/download/', views.shipping_company_sheet_download, name='shipping_company_sheet_download'),

    # -------------------------------------------------------------------------
    # UPLOAD RATE SHEET: Import Company Rates from Excel
    # -------------------------------------------------------------------------
    # URL: /settings/shipping-companies/5/sheet/upload/
    # Accepts an Excel file containing rate data and imports it into the system.
    # This is useful when shipping companies send updated rate sheets, allowing
    # quick bulk updates instead of manual entry.
    # -------------------------------------------------------------------------
    path('shipping-companies/<int:company_id>/sheet/upload/', views.shipping_company_sheet_upload, name='shipping_company_sheet_upload'),

    # -------------------------------------------------------------------------
    # DELETE SHIPPING COMPANY: Remove a Company Record
    # -------------------------------------------------------------------------
    # URL: /settings/shipping-companies/5/delete/
    # Removes a shipping company from the system. This is typically used when
    # the business stops working with a particular freight forwarder or courier.
    # Usually requires confirmation to prevent accidental deletion.
    # -------------------------------------------------------------------------
    path('shipping-companies/<int:company_id>/delete/', views.shipping_company_delete, name='shipping_company_delete'),
]
