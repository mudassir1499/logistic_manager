"""
URL configuration for the noon_labels app.

This module handles shipping label generation for the Noon marketplace
(noon.com), a major e-commerce platform in the Middle East. The logistics
business needs to generate standardized labels for products and cartons
that are being shipped through Noon's fulfillment network.

This module defines URL routes for:
  - The label generation form (input data for the labels)
  - Generating product labels as PDF
  - Generating carton labels as PDF

Django URL Routing Concepts Used:
  path()       - Modern URL pattern matcher. Uses simple string patterns.
  name=        - Unique route name for templates and redirects. For example,
                 {% url 'generate_labels_pdf' %} resolves to /noon-labels/generate/.
"""

# Import path() from django.urls. path() is the standard, modern way to define
# URL routes in Django. It replaced the older url() function and is the
# recommended approach for all new Django projects.
from django.urls import path

# Import all view functions from this app's views.py module.
# The dot (.) means "from the current package" (the noon_labels app directory).
# Each function handles a specific label generation task.
from . import views

# =============================================================================
# URL PATTERNS FOR NOON LABEL GENERATION
# =============================================================================
# urlpatterns is a Python list that Django scans from top to bottom.
# When a request arrives for a URL starting with /noon-labels/ (as defined
# in the project's urls.py via include('noon_labels.urls')), Django looks for
# a match here.
# =============================================================================
urlpatterns = [
    # -------------------------------------------------------------------------
    # ROOT: Label Generation Form
    # -------------------------------------------------------------------------
    # URL: /noon-labels/
    # The main page for the Noon label generator. Displays a form where the
    # admin can enter product details (SKU, quantity, weight, dimensions, etc.)
    # or upload a file with label data. This is the input stage before PDF generation.
    # -------------------------------------------------------------------------
    path('', views.label_form, name='label_form'),

    # -------------------------------------------------------------------------
    # GENERATE LABELS: Create Product Labels PDF
    # -------------------------------------------------------------------------
    # URL: /noon-labels/generate/
    # Processes the submitted label data and generates a PDF file containing
    # individual product labels for each item. These labels are attached to
    # individual products and include barcodes, SKUs, product names, and
    # Noon-specific identifiers required for their warehouse receiving process.
    # -------------------------------------------------------------------------
    path('generate/', views.generate_labels_pdf, name='generate_labels_pdf'),

    # -------------------------------------------------------------------------
    # GENERATE CARTON LABELS: Create Carton Labels PDF
    # -------------------------------------------------------------------------
    # URL: /noon-labels/generate-carton/
    # Generates a PDF containing carton-level shipping labels. These are larger
    # labels attached to the outside of shipping boxes/cartons. They contain
    # shipment information, destination details, carton count, and master carton
    # identifiers needed for Noon's inbound logistics and inventory receiving.
    # -------------------------------------------------------------------------
    path('generate-carton/', views.generate_carton_pdf, name='generate_carton_pdf'),
]
