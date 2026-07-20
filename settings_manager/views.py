"""
Settings Manager Views — Company Configuration & Shipping Company Management

Business Context:
This module controls the "global settings" of the logistics business:
- Company name, phone, and address (appear on invoices, quotations, and labels)
- Currency and exchange rates (for multi-currency quotations and invoicing)
- Commission percentage (for calculating agent commissions on orders)
- Shipping rates for different modes (Air, Sea, KSA) and cargo types (Standard, No-Brand Battery)
- Shipping companies (freight forwarders) with their per-mode rates

The admin can update these settings, and they are used across the entire application:
quotations, invoices, shipping cost calculations, and customer-facing catalogues.

Django Concepts Used:
- @login_required: Only authenticated admin users can change company settings.
- @csrf_exempt: Allows AJAX POST requests from frontend without CSRF token.
- CompanySettings.get_settings(): Custom model method that returns a single-row settings object
  (the app uses a singleton pattern — there is only ONE settings row in the database).
- JsonResponse: Returns JSON for AJAX endpoints (used by the frontend to show success/error messages).
- Decimal: Used for precise financial calculations with shipping rates.
- openpyxl (Workbook, load_workbook): Used to create and parse Excel rate sheets for shipping companies.
"""

import json

from decimal import Decimal

from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
# Role-aware access guard: only users whose profile grants the 'settings' module
# (admins always, or staff explicitly given perm_settings) may reach these views.
from accounts.decorators import module_required
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from openpyxl import Workbook, load_workbook

from .models import CompanySettings, ShippingCompany


@module_required('settings')
@csrf_exempt
def settings_view(request):
    """
    Handle the main company settings page — view and update global business settings.

    Args:
        request (HttpRequest): The incoming HTTP request. GET shows the form; POST saves data.

    Returns:
        HttpResponse (GET): Rendered settings page with current values and shipping companies.
        JsonResponse (POST): {'success': True, 'message': '...'} after saving.

    Business Logic:
        The admin sets up the business identity here (company name, phone, address) and
        financial defaults (currency, exchange rate, commission percentage). These values
        are used on every invoice, quotation, and label. The exchange rate toggle enables
        dual-currency pricing (e.g., RMB and AED) for customers who need to see prices
        in their preferred currency. Commission is the percentage added on top of orders
        as the business's profit margin.
    """
    # Fetch the singleton settings object (always returns the same single row)
    settings = CompanySettings.get_settings()
    if request.method == 'POST':
        # Update basic company info fields from the POST form data
        settings.company_name = request.POST.get('company_name', '')
        settings.company_phone = request.POST.get('company_phone', '')
        settings.company_address = request.POST.get('company_address', '')
        settings.currency = request.POST.get('currency', 'AED')  # Default currency if not specified
        # Exchange rate toggle: 1 means enabled, otherwise disabled
        settings.exchange_rate_enabled = request.POST.get('exchange_rate_enabled') == '1'
        settings.exchange_rate_from = request.POST.get('exchange_rate_from', 'AED')
        settings.exchange_rate_to = request.POST.get('exchange_rate_to', 'RMB')
        try:
            # Convert the exchange rate string to a float; if invalid, default to 0
            settings.exchange_rate = float(request.POST.get('exchange_rate', 0))
        except ValueError:
            settings.exchange_rate = 0
        try:
            # Commission percentage: e.g., 10 means 10% markup on order totals
            settings.commission_percentage = float(request.POST.get('commission_percentage', 0))
        except ValueError:
            settings.commission_percentage = 0
        # Shipping rates are only updated if they appear in the POST data (selective update)
        if 'air_shipping_rate' in request.POST:
            try:
                settings.air_shipping_rate = float(request.POST.get('air_shipping_rate', 0))
            except ValueError:
                settings.air_shipping_rate = 0
        if 'sea_shipping_rate' in request.POST:
            try:
                settings.sea_shipping_rate = float(request.POST.get('sea_shipping_rate', 0))
            except ValueError:
                settings.sea_shipping_rate = 0
        if 'ksa_shipping_rate' in request.POST:
            try:
                settings.ksa_shipping_rate = float(request.POST.get('ksa_shipping_rate', 0))
            except ValueError:
                settings.ksa_shipping_rate = 0
        if 'ksa_air_shipping_rate' in request.POST:
            try:
                settings.ksa_air_shipping_rate = float(request.POST.get('ksa_air_shipping_rate', 0))
            except ValueError:
                settings.ksa_air_shipping_rate = 0
        if 'ksa_sea_shipping_rate' in request.POST:
            try:
                settings.ksa_sea_shipping_rate = float(request.POST.get('ksa_sea_shipping_rate', 0))
            except ValueError:
                settings.ksa_sea_shipping_rate = 0
        # No-brand battery cargo type has its own separate rates (safety regulations require different pricing)
        if 'no_brand_battery_air_shipping_rate' in request.POST:
            try:
                settings.no_brand_battery_air_shipping_rate = float(request.POST.get('no_brand_battery_air_shipping_rate', 0))
            except ValueError:
                settings.no_brand_battery_air_shipping_rate = 0
        if 'no_brand_battery_sea_shipping_rate' in request.POST:
            try:
                settings.no_brand_battery_sea_shipping_rate = float(request.POST.get('no_brand_battery_sea_shipping_rate', 0))
            except ValueError:
                settings.no_brand_battery_sea_shipping_rate = 0
        if 'no_brand_battery_ksa_air_shipping_rate' in request.POST:
            try:
                settings.no_brand_battery_ksa_air_shipping_rate = float(request.POST.get('no_brand_battery_ksa_air_shipping_rate', 0))
            except ValueError:
                settings.no_brand_battery_ksa_air_shipping_rate = 0
        if 'no_brand_battery_ksa_sea_shipping_rate' in request.POST:
            try:
                settings.no_brand_battery_ksa_sea_shipping_rate = float(request.POST.get('no_brand_battery_ksa_sea_shipping_rate', 0))
            except ValueError:
                settings.no_brand_battery_ksa_sea_shipping_rate = 0
        settings.meta_pixel_id = request.POST.get('meta_pixel_id', '').strip()

        # --- Social media links ---
        settings.facebook_url = request.POST.get('facebook_url', '').strip()
        settings.instagram_url = request.POST.get('instagram_url', '').strip()
        settings.linkedin_url = request.POST.get('linkedin_url', '').strip()
        settings.twitter_url = request.POST.get('twitter_url', '').strip()
        settings.youtube_url = request.POST.get('youtube_url', '').strip()
        settings.tiktok_url = request.POST.get('tiktok_url', '').strip()
        settings.whatsapp_channel_url = request.POST.get('whatsapp_channel_url', '').strip()

        # --- Email/SMTP profiles ---
        # Order-status profile (legacy email_* fields)
        settings.email_from_address = request.POST.get('email_from_address', '').strip()
        settings.email_smtp_host = request.POST.get('email_smtp_host', '').strip()
        try:
            settings.email_smtp_port = int(request.POST.get('email_smtp_port', 587))
        except (ValueError, TypeError):
            settings.email_smtp_port = 587
        settings.email_smtp_user = request.POST.get('email_smtp_user', '').strip()
        settings.email_smtp_password = request.POST.get('email_smtp_password', '').strip()
        settings.email_use_tls = request.POST.get('email_use_tls') == '1'

        # Security profile
        settings.security_email_from_address = request.POST.get('security_email_from_address', '').strip()
        settings.security_email_smtp_host = request.POST.get('security_email_smtp_host', '').strip()
        try:
            settings.security_email_smtp_port = int(request.POST.get('security_email_smtp_port', 587))
        except (ValueError, TypeError):
            settings.security_email_smtp_port = 587
        settings.security_email_smtp_user = request.POST.get('security_email_smtp_user', '').strip()
        settings.security_email_smtp_password = request.POST.get('security_email_smtp_password', '').strip()
        settings.security_email_use_tls = request.POST.get('security_email_use_tls') == '1'

        # News profile
        settings.news_email_from_address = request.POST.get('news_email_from_address', '').strip()
        settings.news_email_smtp_host = request.POST.get('news_email_smtp_host', '').strip()
        try:
            settings.news_email_smtp_port = int(request.POST.get('news_email_smtp_port', 587))
        except (ValueError, TypeError):
            settings.news_email_smtp_port = 587
        settings.news_email_smtp_user = request.POST.get('news_email_smtp_user', '').strip()
        settings.news_email_smtp_password = request.POST.get('news_email_smtp_password', '').strip()
        settings.news_email_use_tls = request.POST.get('news_email_use_tls') == '1'

        if 'og_image' in request.FILES:
            settings.og_image = request.FILES['og_image']
        settings.save()  # Persist all changes to the database
        return JsonResponse({'success': True, 'message': 'Settings saved successfully!'})
    # For GET requests, fetch all shipping companies to display in the settings page
    shipping_companies = ShippingCompany.objects.all()
    return render(request, 'settings/settings.html', {'settings': settings, 'shipping_companies': shipping_companies})


@module_required('settings')
@csrf_exempt
def shipping_calculator_view(request):
    """
    Handle the shipping calculator settings page — view and update shipping rates.

    Args:
        request (HttpRequest): The incoming HTTP request. GET shows the calculator; POST saves rates.

    Returns:
        HttpResponse (GET): Rendered shipping calculator page with rates and companies.
        JsonResponse (POST): {'success': True, 'message': '...'} after saving rates.

    Business Logic:
        Shipping rates vary by mode (air vs sea) and destination (KSA vs general).
        This page lets the admin set global default rates. These are used as fallbacks
        when no shipping company is selected for an order, or when auto-calculating shipping costs.
        The calculator also displays per-company rates so the admin can compare freight forwarders.
    """
    settings = CompanySettings.get_settings()
    if request.method == 'POST':
        # Update global shipping rates from the POST form data
        try:
            settings.air_shipping_rate = float(request.POST.get('air_shipping_rate', 0))
        except ValueError:
            settings.air_shipping_rate = 0
        try:
            settings.sea_shipping_rate = float(request.POST.get('sea_shipping_rate', 0))
        except ValueError:
            settings.sea_shipping_rate = 0
        try:
            settings.ksa_shipping_rate = float(request.POST.get('ksa_shipping_rate', 0))
        except ValueError:
            settings.ksa_shipping_rate = 0
        try:
            settings.ksa_air_shipping_rate = float(request.POST.get('ksa_air_shipping_rate', 0))
        except ValueError:
            settings.ksa_air_shipping_rate = 0
        try:
            settings.ksa_sea_shipping_rate = float(request.POST.get('ksa_sea_shipping_rate', 0))
        except ValueError:
            settings.ksa_sea_shipping_rate = 0
        try:
            settings.no_brand_battery_air_shipping_rate = float(request.POST.get('no_brand_battery_air_shipping_rate', 0))
        except ValueError:
            settings.no_brand_battery_air_shipping_rate = 0
        try:
            settings.no_brand_battery_sea_shipping_rate = float(request.POST.get('no_brand_battery_sea_shipping_rate', 0))
        except ValueError:
            settings.no_brand_battery_sea_shipping_rate = 0
        try:
            settings.no_brand_battery_ksa_air_shipping_rate = float(request.POST.get('no_brand_battery_ksa_air_shipping_rate', 0))
        except ValueError:
            settings.no_brand_battery_ksa_air_shipping_rate = 0
        try:
            settings.no_brand_battery_ksa_sea_shipping_rate = float(request.POST.get('no_brand_battery_ksa_sea_shipping_rate', 0))
        except ValueError:
            settings.no_brand_battery_ksa_sea_shipping_rate = 0
        settings.save()
        return JsonResponse({'success': True, 'message': 'Shipping rates saved successfully!'})

    # For GET requests, prepare shipping company data for the JavaScript frontend
    shipping_companies = list(ShippingCompany.objects.all())
    companies_for_js = []       # Data for the calculator's interactive tables
    quotation_rows = []         # Data for the rate comparison / quotation tool
    for sc in shipping_companies:
        # Standard cargo rates for this company
        standard = {
            'air': float(sc.air_rate),
            'sea': float(sc.sea_rate),
            'ksa_air': float(sc.ksa_air_rate),
            'ksa_sea': float(sc.ksa_sea_rate),
        }
        # No-brand battery cargo rates (special handling fees)
        battery = {
            'air': float(sc.nbb_air_rate),
            'sea': float(sc.nbb_sea_rate),
            'ksa_air': float(sc.nbb_ksa_air_rate),
            'ksa_sea': float(sc.nbb_ksa_sea_rate),
        }
        # Build the JavaScript-compatible data structure for this company
        companies_for_js.append({
            'id': sc.id,
            'name': sc.name,
            'website': sc.website,
            'rates': {
                'standard': standard,
                'no_brand_battery': battery,
            },
        })
        # Also build a quotation-friendly row structure
        quotation_rows.append({
            'company_id': sc.id,
            'company_name': sc.name,
            'website': sc.website,
            'rates': {
                'standard': standard,
                'no_brand_battery': battery,
            },
        })

    return render(request, 'settings/shipping_calculator.html', {
        'settings': settings,
        'shipping_companies': shipping_companies,
        'shipping_companies_json': json.dumps(companies_for_js),  # Serialized for JS use
        'shipping_quotation_json': json.dumps(quotation_rows, ensure_ascii=False, indent=2),
    })


@module_required('settings')
@csrf_exempt
def shipping_company_list(request):
    """
    AJAX endpoint: Return all shipping companies as JSON.

    Args:
        request (HttpRequest): The incoming HTTP request.

    Returns:
        JsonResponse: {'companies': [...]} with all shipping company data and rates.

    Business Logic:
        The frontend (JavaScript) fetches this list to populate dropdowns and
        rate comparison tables. Each company has rates for air, sea, KSA modes
        for both standard and no-brand battery cargo.
    """
    # Use .values() to get a dictionary representation of each company (lightweight, no model instances)
    companies = list(ShippingCompany.objects.values(
        'id', 'name', 'website',
        'air_rate', 'sea_rate', 'ksa_air_rate', 'ksa_sea_rate',
        'nbb_air_rate', 'nbb_sea_rate', 'nbb_ksa_air_rate', 'nbb_ksa_sea_rate'
    ))
    return JsonResponse({'companies': companies})


@csrf_exempt
def _build_company_rate_workbook(company):
    """
    Private helper: Build an openpyxl Workbook containing a shipping company's rate sheet.

    Args:
        company (ShippingCompany): The shipping company to generate the rate sheet for.

    Returns:
        Workbook: An openpyxl workbook with the company's rates in a table.

    Business Logic:
        Each shipping company has a downloadable Excel rate sheet. This helper creates
        the sheet structure: company name, website, then a table of (Category, Mode, Rate).
        The sheet can be downloaded, edited, and re-uploaded to update the company's rates.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = 'Rates'
    # Row 1-2: Company metadata
    ws.append(['Company', company.name])
    ws.append(['Website', company.website or ''])
    ws.append([])  # Blank row for spacing
    # Row 4: Table header
    ws.append(['Category', 'Mode', 'Rate'])
    # All rate rows to include in the sheet
    rows = [
        ('Standard', 'Air / KG', company.air_rate),
        ('Standard', 'Sea / CBM', company.sea_rate),
        ('Standard', 'KSA Air / KG', company.ksa_air_rate),
        ('Standard', 'KSA Sea / CBM', company.ksa_sea_rate),
        ('No Brand Battery', 'Air / KG', company.nbb_air_rate),
        ('No Brand Battery', 'Sea / CBM', company.nbb_sea_rate),
        ('No Brand Battery', 'KSA Air / KG', company.nbb_ksa_air_rate),
        ('No Brand Battery', 'KSA Sea / CBM', company.nbb_ksa_sea_rate),
    ]
    for row in rows:
        ws.append([row[0], row[1], float(row[2])])  # Convert Decimal to float for Excel
    # Set column widths for readability
    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 18
    ws.column_dimensions['C'].width = 14
    return wb


def _save_company_rate_sheet(company):
    """
    Private helper: Generate and save the rate sheet as a file on the company's model.

    Args:
        company (ShippingCompany): The shipping company to save the rate sheet for.

    Business Logic:
        After creating or updating a company, we auto-generate a downloadable Excel
        rate sheet and save it to the company's FileField (shipping_rate_sheet).
        This file can be downloaded by the admin or shared with the customer.
    """
    wb = _build_company_rate_workbook(company)
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        wb.save(tmp.name)
        tmp.seek(0)
        # Save the file to Django's MEDIA storage via the FileField
        company.shipping_rate_sheet.save(
            f'{company.name[:40].replace(" ", "_")}_rates.xlsx',
            ContentFile(tmp.read()),
            save=False,  # Don't save the model yet — we'll do it below
        )
    company.save(update_fields=['shipping_rate_sheet'])  # Only update the file field


def _apply_company_rate_sheet(company, uploaded_file):
    """
    Private helper: Parse an uploaded Excel rate sheet and update the company's rates.

    Args:
        company (ShippingCompany): The shipping company to update.
        uploaded_file (InMemoryUploadedFile): The uploaded Excel file from the frontend.

    Business Logic:
        The admin can download a rate sheet, edit rates in Excel, and re-upload it.
        This function parses the rows and maps them to the correct model fields.
        The mapping uses (category, mode) tuples to find the right field name.
    """
    wb = load_workbook(uploaded_file)
    ws = wb.active
    # Mapping from (category.lower(), mode.lower()) to the model field name
    mapping = {
        ('standard', 'air / kg'): 'air_rate',
        ('standard', 'sea / cbm'): 'sea_rate',
        ('standard', 'ksa air / kg'): 'ksa_air_rate',
        ('standard', 'ksa sea / cbm'): 'ksa_sea_rate',
        ('no brand battery', 'air / kg'): 'nbb_air_rate',
        ('no brand battery', 'sea / cbm'): 'nbb_sea_rate',
        ('no brand battery', 'ksa air / kg'): 'nbb_ksa_air_rate',
        ('no brand battery', 'ksa sea / cbm'): 'nbb_ksa_sea_rate',
    }
    # Start from row 5 (after header rows)
    for row in ws.iter_rows(min_row=5, values_only=True):
        if not row or len(row) < 3:
            continue
        # Normalize the category and mode strings for lookup
        key = (str(row[0]).strip().lower(), str(row[1]).strip().lower())
        field = mapping.get(key)
        if field:
            try:
                # Convert the cell value to Decimal and set the model field
                setattr(company, field, Decimal(str(row[2] or 0)))
            except Exception:
                setattr(company, field, Decimal('0'))
    company.save()  # Persist the updated rates to the database
    _save_company_rate_sheet(company)  # Regenerate the downloadable sheet with new values


@module_required('settings')
@csrf_exempt
def shipping_company_add(request):
    """
    AJAX endpoint: Add a new shipping company (freight forwarder).

    Args:
        request (HttpRequest): The incoming AJAX POST request.

    Returns:
        JsonResponse: {'success': True, 'message': '...', 'id': ..., 'name': ..., 'website': ...}

    Business Logic:
        Freight forwarders are the companies that physically ship the goods (air/sea).
        The admin adds each forwarder with their name and website, then later sets their
        per-mode rates. A rate sheet is auto-generated upon creation.
    """
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        website = request.POST.get('website', '').strip()
        if not name:
            return JsonResponse({'success': False, 'message': 'Company name is required.'})
        # Create the new shipping company with name and website
        company = ShippingCompany.objects.create(name=name[:100], website=website[:255])
        # Auto-generate and save a blank/default rate sheet for the new company
        _save_company_rate_sheet(company)
        return JsonResponse({'success': True, 'message': 'Shipping company added!', 'id': company.id, 'name': company.name, 'website': company.website})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('settings')
@csrf_exempt
def shipping_company_edit(request, company_id):
    """
    AJAX endpoint: Edit an existing shipping company's name and website.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        company_id (int): The primary key of the ShippingCompany to edit.

    Returns:
        JsonResponse: {'success': True, 'message': '...', 'id': ..., 'name': ..., 'website': ...}

    Business Logic:
        If a freight forwarder changes their name or the admin made a typo, this endpoint
        updates the basic info. The rate sheet is regenerated to reflect the new name.
    """
    try:
        company = ShippingCompany.objects.get(id=company_id)
    except ShippingCompany.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Not found'}, status=404)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        website = request.POST.get('website', '').strip()
        if not name:
            return JsonResponse({'success': False, 'message': 'Company name is required.'})
        company.name = name[:100]       # Truncate to max 100 chars
        company.website = website[:255]  # Truncate to max 255 chars
        company.save()
        _save_company_rate_sheet(company)  # Regenerate the sheet with updated name
        return JsonResponse({'success': True, 'message': 'Shipping company updated!', 'id': company.id, 'name': company.name, 'website': company.website})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('settings')
@csrf_exempt
def shipping_company_save_rates(request, company_id):
    """
    AJAX endpoint: Save per-mode shipping rates for a specific company.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        company_id (int): The primary key of the ShippingCompany to update rates for.

    Returns:
        JsonResponse: {'success': True, 'message': '...', 'sheet_url': '...'}

    Business Logic:
        This is the core of freight comparison. Each forwarder quotes different rates
        for air, sea, KSA modes. The admin inputs these rates and the system uses them
        to auto-calculate shipping costs when building orders.
    """
    try:
        company = ShippingCompany.objects.get(id=company_id)
    except ShippingCompany.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Not found'}, status=404)
    if request.method == 'POST':
        # All 8 rate fields that can be updated
        rate_fields = ['air_rate', 'sea_rate', 'ksa_air_rate', 'ksa_sea_rate',
                       'nbb_air_rate', 'nbb_sea_rate', 'nbb_ksa_air_rate', 'nbb_ksa_sea_rate']
        for field in rate_fields:
            try:
                setattr(company, field, float(request.POST.get(field, 0)))
            except (ValueError, TypeError):
                setattr(company, field, 0)
        company.save()
        _save_company_rate_sheet(company)  # Regenerate the sheet with new rates
        return JsonResponse({'success': True, 'message': f'Rates saved for {company.name}!', 'sheet_url': company.shipping_rate_sheet.url if company.shipping_rate_sheet else ''})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('settings')
@csrf_exempt
def shipping_company_delete(request, company_id):
    """
    AJAX endpoint: Delete a shipping company.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        company_id (int): The primary key of the ShippingCompany to delete.

    Returns:
        JsonResponse: {'success': True, 'message': '...'} or error.

    Business Logic:
        If a freight forwarder is no longer used, the admin removes them from the system.
        This does NOT affect historical orders — it only removes the company from future use.
    """
    try:
        company = ShippingCompany.objects.get(id=company_id)
    except ShippingCompany.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Not found'}, status=404)
    if request.method == 'POST':
        company.delete()  # Cascade delete — also removes associated files if configured
        return JsonResponse({'success': True, 'message': 'Shipping company deleted!'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('settings')
@csrf_exempt
def shipping_company_sheet_download(request, company_id):
    """
    AJAX endpoint: Get the download URL for a company's rate sheet.

    Args:
        request (HttpRequest): The incoming AJAX request.
        company_id (int): The primary key of the ShippingCompany.

    Returns:
        JsonResponse: {'success': True, 'url': '...'} or error.

    Business Logic:
        The admin can download the company's rate sheet to share it with the customer
        or to edit and re-upload. If no sheet exists yet, one is auto-generated.
    """
    try:
        company = ShippingCompany.objects.get(id=company_id)
    except ShippingCompany.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Not found'}, status=404)
    if not company.shipping_rate_sheet:
        # If the sheet hasn't been generated yet, create it now
        _save_company_rate_sheet(company)
    if company.shipping_rate_sheet:
        return JsonResponse({'success': True, 'url': company.shipping_rate_sheet.url})
    return JsonResponse({'success': False, 'message': 'Unable to generate spreadsheet'}, status=500)


@module_required('settings')
@csrf_exempt
def shipping_company_sheet_upload(request, company_id):
    """
    AJAX endpoint: Upload an edited Excel rate sheet and update company rates.

    Args:
        request (HttpRequest): The incoming AJAX POST request with a file attachment.
        company_id (int): The primary key of the ShippingCompany to update.

    Returns:
        JsonResponse: {'success': True, 'message': '...', 'url': '...'} or error.

    Business Logic:
        The admin downloads the rate sheet, fills in new rates in Excel, and uploads it
        back. This is faster than editing each rate field one by one in the browser.
        The file is parsed and the company's rates are updated accordingly.
    """
    try:
        company = ShippingCompany.objects.get(id=company_id)
    except ShippingCompany.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Not found'}, status=404)
    if request.method == 'POST':
        uploaded = request.FILES.get('sheet')
        if not uploaded:
            return JsonResponse({'success': False, 'message': 'Excel file is required.'})
        try:
            # Parse the uploaded Excel and apply changes to the company model
            _apply_company_rate_sheet(company, uploaded)
            return JsonResponse({'success': True, 'message': f'Excel sheet imported for {company.name}!', 'url': company.shipping_rate_sheet.url if company.shipping_rate_sheet else ''})
        except Exception:
            return JsonResponse({'success': False, 'message': 'Invalid Excel sheet format.'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})
