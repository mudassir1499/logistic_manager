"""
URL configuration for the products app.

This module defines all URL routes related to product management:
listing products, adding/editing/deleting products, saving prices, viewing the
public product catalogue, toggling privacy settings, bulk operations (uploads,
actions, templates), and generating supplier quote templates.

Django URL Routing Concepts Used:
  path()        - The modern URL pattern matcher. Replaces the older url() function.
                  Uses simple string patterns and angle-bracket converters.
  <int:...>     - URL converter that captures an integer parameter and passes it
                  to the view as a keyword argument. Returns 404 for non-integers.
  name=         - A unique string name for each route. Used in templates and
                  redirects so URLs can be referenced by name, not by hardcoded path.
"""

# Import path() from django.urls. path() is the standard, modern way to define
# URL routes in Django. It is cleaner and more readable than the older regex-based
# url() or re_path() for most common use cases.
from django.urls import path

# Import all view functions from this app's views.py.
# The dot (.) means "from the current package" (the products app directory).
# Each function handles a specific HTTP request for the product management system.
from . import api, feeds, views

# =============================================================================
# URL PATTERNS FOR PRODUCT MANAGEMENT
# =============================================================================
# urlpatterns is a Python list that Django scans from top to bottom.
# When a request arrives for a URL starting with /products/ (as set up in
# the project's urls.py via include()), Django looks for a match here.
#
# Order matters: Django returns the FIRST matching route. Put more specific
# routes before generic ones. For example, 'add/' must come before '' because
# 'add/' is more specific and '' matches everything.
# =============================================================================
urlpatterns = [
    # -------------------------------------------------------------------------
    # ROOT: Product List Page
    # -------------------------------------------------------------------------
    # URL: /products/
    # The default page for the Products section. Displays a searchable,
    # filterable list of all products in the catalog. Usually includes images,
    # pricing, stock status, and action buttons (edit, delete, view).
    # -------------------------------------------------------------------------
    path('', views.product_list, name='product_list'),

    # -------------------------------------------------------------------------
    # ADD: Create a New Product
    # -------------------------------------------------------------------------
    # URL: /products/add/
    # Shows a form to create a new product (name, image, dimensions, weight,
    # CBM, prices, supplier info). On submission, saves the Product record.
    # -------------------------------------------------------------------------
    path('add/', views.add_product, name='add_product'),

    # -------------------------------------------------------------------------
    # EDIT: Update an Existing Product
    # -------------------------------------------------------------------------
    # URL: /products/edit/5/
    # Displays a pre-filled form with the product's current data. The admin
    # can modify any field and save changes. The <int:product_id> parameter
    # identifies which product to edit.
    # -------------------------------------------------------------------------
    path('edit/<int:product_id>/', views.edit_product, name='edit_product'),

    # -------------------------------------------------------------------------
    # DELETE: Remove a Product
    # -------------------------------------------------------------------------
    # URL: /products/delete/5/
    # Handles the deletion of a product from the catalog. Usually requires
    # a confirmation step to prevent accidental data loss.
    # -------------------------------------------------------------------------
    path('delete/<int:product_id>/', views.delete_product, name='delete_product'),

    # -------------------------------------------------------------------------
    # SAVE PRICES: Update Pricing for a Product
    # -------------------------------------------------------------------------
    # URL: /products/save-prices/5/
    # A dedicated endpoint for updating product pricing (FOB, retail, wholesale,
    # etc.). This may be called via AJAX from a pricing table or form.
    # -------------------------------------------------------------------------
    path('save-prices/<int:product_id>/', views.save_product_prices, name='save_product_prices'),

    # -------------------------------------------------------------------------
    # CATALOGUE: Public Product Catalogue
    # -------------------------------------------------------------------------
    # URL: /products/catalogue/
    # A customer-facing or public page showing all products in a clean,
    # browseable format. This is the "storefront" view of the product catalog.
    # -------------------------------------------------------------------------
    path('catalogue/', views.product_catalogue, name='product_catalogue'),

    # -------------------------------------------------------------------------
    # TOGGLE PRIVATE: Change Product Visibility
    # -------------------------------------------------------------------------
    # URL: /products/toggle-private/5/
    # Switches a product between public (visible in catalogue) and private
    # (hidden from public view, only for admin/internal use). This is useful
    # for managing which products are offered to customers.
    # -------------------------------------------------------------------------
    path('toggle-private/<int:product_id>/', views.toggle_private, name='toggle_private'),

    # -------------------------------------------------------------------------
    # BULK ACTION: Perform Mass Operations on Products
    # -------------------------------------------------------------------------
    # URL: /products/bulk-action/
    # Handles bulk operations like "delete selected", "change category",
    # "mark as private", etc. Receives a list of product IDs via POST data
    # and applies the chosen action to all of them at once.
    # -------------------------------------------------------------------------
    path('bulk-action/', views.bulk_action, name='bulk_action'),

    # URL: /products/tags/save/  and  /products/tags/delete/
    # Rename, recolour or delete one tag, from the tag manager on the product
    # list. Both are POST-only and return JSON — the dialog updates in place
    # rather than reloading a list somebody is midway through working through.
    # URL: /products/feed.csv  and  /products/feed.xml
    #
    # The advertising catalogue. Meta (Facebook/Instagram) and TikTok fetch these
    # on their own schedule to build the product catalogue that dynamic and
    # retargeting ads are served from.
    #
    # DELIBERATELY UNAUTHENTICATED. The crawlers arrive with no session and no
    # token, so a login wall here means an empty catalogue and no ads at all.
    # Everything served is already public on the storefront - private products,
    # drafts and supplier links are filtered out in products/feeds.py, which is
    # where the reasoning and the tests live.
    path('feed.csv', feeds.product_feed_csv, name='product_feed_csv'),
    path('feed.xml', feeds.product_feed_xml, name='product_feed_xml'),

    # Staff-only: what the feeds contain, and what they are silently dropping.
    path('feed-health/', views.feed_health, name='feed_health'),

    path('tags/save/', views.tag_save, name='tag_save'),
    path('tags/delete/', views.tag_delete, name='tag_delete'),

    # CATEGORY MANAGEMENT: create/rename/hide/delete categories and their
    # subcategories without going through Django's own /admin/.
    path('categories/', views.category_manage, name='category_manage'),

    # PRICE HISTORY: every bulk adjustment, with its money impact.
    path('price-history/', views.price_history, name='price_history'),

    # -------------------------------------------------------------------------
    # BULK UPLOAD: Import Products from a Spreadsheet
    # -------------------------------------------------------------------------
    # URL: /products/bulk-upload/
    # Accepts an Excel/CSV file and creates multiple Product records at once.
    # This is essential for logistics businesses that receive large product
    # lists from suppliers and need to import them quickly.
    # -------------------------------------------------------------------------
    path('bulk-upload/', views.bulk_upload, name='bulk_upload'),

    # -------------------------------------------------------------------------
    # BULK UPLOAD PHOTOS: Import Products from Image Files
    # -------------------------------------------------------------------------
    # URL: /products/bulk-upload-photos/
    # Allows uploading multiple product images at once, possibly with automatic
    # product creation based on image filenames or embedded metadata.
    # -------------------------------------------------------------------------
    path('bulk-upload-photos/', views.bulk_upload_from_images, name='bulk_upload_from_images'),

    # -------------------------------------------------------------------------
    # BULK UPLOAD 1688: Import from 1688.com (Chinese B2B Platform)
    # -------------------------------------------------------------------------
    # URL: /products/bulk-upload-1688/
    # Specialized import for products sourced from 1688.com, a major Chinese
    # wholesale platform. This likely parses 1688 data formats or API responses.
    # -------------------------------------------------------------------------
    path('bulk-upload-1688/', views.bulk_upload_1688, name='bulk_upload_1688'),

    # -------------------------------------------------------------------------
    # BULK UPLOAD TEMPLATE: Download Import Template
    # -------------------------------------------------------------------------
    # URL: /products/bulk-upload-template/
    # Returns an Excel/CSV template file with the correct column headers so
    # admins can fill in product data and then use the bulk-upload feature.
    # -------------------------------------------------------------------------
    path('bulk-upload-template/', views.bulk_upload_template, name='bulk_upload_template'),

    # -------------------------------------------------------------------------
    # CATALOGUE EXPORT: Export Products to Excel
    # -------------------------------------------------------------------------
    # URL: /products/catalogue-export/
    # Generates and downloads an Excel file containing all products in the
    # catalog. Useful for sharing with customers, suppliers, or for backup.
    # -------------------------------------------------------------------------
    path('catalogue-export/', views.catalogue_excel_export, name='catalogue_excel_export'),

    # -------------------------------------------------------------------------
    # CATALOGUE IMPORT: the export, filled in and sent back
    # -------------------------------------------------------------------------
    # URL: /products/catalogue-import/
    # Takes the .xlsx produced by catalogue-export and applies the prices, MOQs
    # and carton specs in it to the products it names. UPDATES ONLY - a row
    # matching no product is reported, never created, because creating belongs
    # to bulk-upload where the other required fields are collected.
    # -------------------------------------------------------------------------
    path('catalogue-import/', views.catalogue_import, name='catalogue_import'),

    # -------------------------------------------------------------------------
    # BROWSER EXTENSION API
    # -------------------------------------------------------------------------
    # Token-authenticated JSON endpoints called by the 1688 sourcing extension.
    # They live under /api/extension/ rather than alongside the HTML views so the
    # split between "screens a person opens" and "endpoints a script calls" stays
    # obvious — and so a future reverse-proxy rule can treat them differently.
    path('api/extension/ping/', api.extension_ping, name='extension_ping'),
    path('api/extension/extract/', api.extension_extract, name='extension_extract'),
    path('api/extension/import/', api.extension_import, name='extension_import'),
    # Lets the panel add a missing category without leaving the 1688 page.
    path('api/extension/category/', api.extension_create_category,
         name='extension_create_category'),

    # -------------------------------------------------------------------------
    # SUPPLIER QUOTE: Generate Supplier Quote Template
    # -------------------------------------------------------------------------
    # URL: /products/supplier-quote/5/
    # Creates a formatted quotation template for a specific product that can
    # be sent to suppliers to request pricing. The product_id identifies which
    # product's details to include in the quote template.
    # -------------------------------------------------------------------------
    path('supplier-quote/<int:product_id>/', views.supplier_quote_template, name='supplier_quote_template'),
]
