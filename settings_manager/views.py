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
import re

from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
# Role-aware access guard: only users whose profile grants the 'settings' module
# (admins always, or staff explicitly given perm_settings) may reach these views.
from accounts.decorators import module_required
from django.shortcuts import render
# NOTE: @csrf_exempt was removed from the views in this file. The admin UI now
# attaches X-CSRFToken to every same-origin state-changing fetch() automatically
# (see the wrapper at the top of static/main.js), so these endpoints are
# protected again without any call site needing to change.
from openpyxl import Workbook, load_workbook

from .models import (CargoType, CompanySettings, ShippingCompany,
                     ShippingDestination, ShippingRate, ShippingRateSheet,
                     TeamMember)
from . import rate_sheets


# Matches the full <meta name="google-site-verification" content="TOKEN"> tag that
# Google Search Console displays. Admins almost always copy the whole tag, so we
# pull the token out of it instead of storing markup that would then be escaped
# and rendered as visible text inside <head>.
_VERIFICATION_META_RE = re.compile(
    r'content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _to_decimal(raw, fallback):
    """
    Parse a posted decimal, falling back to the current value when unusable.

    Args:
        raw (str | None): The submitted value.
        fallback: What to keep if the value is missing or not a number.

    Returns:
        Decimal: The parsed value, or the fallback.

    Silently keeping the previous value beats writing 0, which on a percentage
    field would quietly change VAT or a deposit rate to nothing.
    """
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        return fallback


def _to_int(raw, fallback, lo=None, hi=None):
    """
    Parse a posted integer, clamped to an optional range.

    Args:
        raw (str | None): The submitted value.
        fallback (int): Kept when the value is missing or not a number.
        lo (int, optional): Minimum allowed value.
        hi (int, optional): Maximum allowed value.

    Returns:
        int: The parsed and clamped value, or the fallback.
    """
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError, AttributeError):
        return fallback
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _keep_or_replace_password(settings, field, post):
    """
    Update an SMTP password only when a new one was typed.

    The settings page no longer prints saved passwords into the HTML (anyone
    with the page open, or its source, could read them), so the box arrives
    empty unless the admin typed something. Empty therefore means "keep what
    is saved" - which is also what the field's placeholder has always promised.
    Ticking the matching ``clear_<field>`` box removes a saved password.
    """
    if post.get(f'clear_{field}') == '1':
        setattr(settings, field, '')
        return
    typed = (post.get(field) or '').strip()
    if typed:
        setattr(settings, field, typed)


def _extract_verification_token(raw):
    """
    Normalise a Search Console verification value into a bare token.

    Args:
        raw (str): Whatever the admin pasted — either the bare token
                   ("3RkoOTP7mf...") or the entire <meta ...> tag copied from the
                   Search Console verification screen.

    Returns:
        str: The token on its own, with surrounding whitespace removed.

    Why this exists:
        Google's UI presents the token wrapped in a full HTML meta tag and offers
        a "copy" button for that whole tag. If we stored the markup verbatim, the
        template would escape it and Google would never see a valid verification
        tag — the property would silently fail to verify.
    """
    value = (raw or '').strip()
    if '<' in value:
        match = _VERIFICATION_META_RE.search(value)
        if match:
            return match.group(1).strip()
    return value


@module_required('settings')
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
        # Was editable only through /admin/ despite being on the Settings screen's
        # own subject matter — the floating WhatsApp button reads it.
        settings.whatsapp_number = request.POST.get('whatsapp_number', '').strip()
        # Product-share wording. Marketing copy, so it lives here rather than in a
        # template that would need a deploy to change.
        settings.share_pitch = request.POST.get('share_pitch', '').strip()[:200]
        settings.share_contact = request.POST.get('share_contact', '').strip()[:50]
        settings.currency = request.POST.get('currency', 'AED')  # Default currency if not specified
        # Exchange rate toggle: 1 means enabled, otherwise disabled
        settings.exchange_rate_enabled = request.POST.get('exchange_rate_enabled') == '1'
        settings.exchange_rate_from = request.POST.get('exchange_rate_from', 'AED')
        settings.exchange_rate_to = request.POST.get('exchange_rate_to', 'RMB')
        # ---------------------------------------------------------------------
        # MONEY FIELDS KEEP THEIR VALUE WHEN A FIELD ARRIVES BLANK
        # ---------------------------------------------------------------------
        # Every rate below used to be parsed with float() wrapped in
        # `except ValueError: field = 0`. An empty input raises, so clearing a
        # box - or saving a form that simply did not carry that box - wrote a
        # ZERO over a live rate, under a "Settings saved successfully!" banner.
        #
        # That was not cosmetic. commission_percentage at 0 stops commission
        # being charged on new orders, and a global shipping rate at 0 means
        # "no published rate" to the quoting engine, so the public calculator
        # quietly stops quoting that route and tells customers to get in touch.
        #
        # _to_decimal keeps the CURRENT value when the input is missing or
        # unparseable, which is the only safe default for money: refusing to
        # change something is recoverable, silently zeroing it is not. It also
        # returns Decimal rather than float, so the value stored is the one that
        # was typed instead of the nearest binary approximation of it.
        # ---------------------------------------------------------------------
        settings.exchange_rate = _to_decimal(
            request.POST.get('exchange_rate'), settings.exchange_rate)
        settings.commission_percentage = _to_decimal(
            request.POST.get('commission_percentage'), settings.commission_percentage)
        # The nine global shipping rates, in one place. A loop rather than nine
        # near-identical blocks: the old shape invited a tenth rate to be added
        # by copy-paste, which is how all nine came to share the same bug.
        #
        # `in request.POST` is still checked so a form that does not carry a
        # field leaves it alone, and _to_decimal covers the field that IS
        # carried but arrives empty.
        for _rate_field in (
            'air_shipping_rate', 'sea_shipping_rate', 'ksa_shipping_rate',
            'ksa_air_shipping_rate', 'ksa_sea_shipping_rate',
            'no_brand_battery_air_shipping_rate', 'no_brand_battery_sea_shipping_rate',
            'no_brand_battery_ksa_air_shipping_rate', 'no_brand_battery_ksa_sea_shipping_rate',
        ):
            if _rate_field in request.POST:
                setattr(settings, _rate_field, _to_decimal(
                    request.POST.get(_rate_field), getattr(settings, _rate_field)))

        settings.meta_pixel_id = request.POST.get('meta_pixel_id', '').strip()

        # --- Site identity + business profile ---
        # base_url strips a trailing slash on read, but normalising here too keeps
        # the stored value tidy for anyone reading it in the admin.
        settings.site_url = request.POST.get('site_url', '').strip().rstrip('/')
        settings.business_city = request.POST.get('business_city', '').strip()
        settings.business_region = request.POST.get('business_region', '').strip()
        settings.business_country = request.POST.get('business_country', '').strip().upper()[:2]
        settings.opening_time = request.POST.get('opening_time', '').strip()
        settings.closing_time = request.POST.get('closing_time', '').strip()
        settings.working_days = request.POST.get('working_days', '').strip()
        settings.languages_spoken = request.POST.get('languages_spoken', '').strip()

        # --- Invoicing ---
        settings.tax_registration_number = request.POST.get('tax_registration_number', '').strip()
        settings.vat_percentage = _to_decimal(request.POST.get('vat_percentage'), settings.vat_percentage)
        settings.bank_name = request.POST.get('bank_name', '').strip()
        settings.bank_account_name = request.POST.get('bank_account_name', '').strip()
        settings.bank_account_number = request.POST.get('bank_account_number', '').strip()
        settings.bank_iban = request.POST.get('bank_iban', '').strip().replace(' ', '')
        settings.bank_swift = request.POST.get('bank_swift', '').strip().upper()
        settings.bank_branch = request.POST.get('bank_branch', '').strip()

        terms = request.POST.get('default_payment_terms', '').strip()
        if terms in dict(CompanySettings.PAYMENT_TERMS_CHOICES):
            settings.default_payment_terms = terms

        settings.invoice_prefix = request.POST.get('invoice_prefix', '').strip()
        settings.invoice_terms = request.POST.get('invoice_terms', '').strip()
        settings.invoice_number_padding = _to_int(
            request.POST.get('invoice_number_padding'), settings.invoice_number_padding, lo=0, hi=10)

        # next_invoice_number is only moved FORWARD. Letting it go backwards would
        # hand an already-issued reference to a second invoice, and invoice_number
        # is unique — the duplicate would fail to save at the worst possible moment.
        wanted_next = _to_int(request.POST.get('next_invoice_number'), settings.next_invoice_number, lo=1)
        if wanted_next >= settings.next_invoice_number:
            settings.next_invoice_number = wanted_next

        # --- Operations ---
        settings.lead_notification_email = request.POST.get('lead_notification_email', '').strip()
        settings.quote_validity_days = _to_int(
            request.POST.get('quote_validity_days'), settings.quote_validity_days, lo=0, hi=365)
        settings.default_deposit_percentage = _to_decimal(
            request.POST.get('default_deposit_percentage'), settings.default_deposit_percentage)
        settings.low_stock_threshold = _to_int(
            request.POST.get('low_stock_threshold'), settings.low_stock_threshold, lo=0)
        settings.stale_shipment_days = _to_int(
            request.POST.get('stale_shipment_days'), settings.stale_shipment_days, lo=0, hi=365)
        settings.order_cutoff_time = request.POST.get('order_cutoff_time', '').strip()

        # --- Third-party widgets ---
        settings.tawk_widget_id = request.POST.get('tawk_widget_id', '').strip().strip('/')

        # --- Branding ---
        if 'logo' in request.FILES:
            settings.logo = request.FILES['logo']
        if 'logo_wide' in request.FILES:
            settings.logo_wide = request.FILES['logo_wide']

        # --- Homepage credibility figures ---
        # All optional. A blank value hides that figure from the public pages
        # entirely, which is the correct outcome for anything unverified.
        settings.stat_years_in_china = request.POST.get('stat_years_in_china', '').strip()
        settings.stat_verified_suppliers = request.POST.get('stat_verified_suppliers', '').strip()
        settings.stat_products_sourced = request.POST.get('stat_products_sourced', '').strip()
        settings.stat_active_clients = request.POST.get('stat_active_clients', '').strip()
        settings.stat_response_time = request.POST.get('stat_response_time', '').strip()

        # --- Google Search Console + Google Analytics 4 ---
        # Both are optional. A blank GA ID switches Google Analytics off entirely
        # rather than shipping a broken tag. The Search Console token is stripped
        # of a pasted <meta> wrapper because that is the form Google shows on
        # screen and the most common thing an admin will paste in.
        settings.google_analytics_id = request.POST.get('google_analytics_id', '').strip()
        settings.google_site_verification = _extract_verification_token(
            request.POST.get('google_site_verification', '')
        )

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
        _keep_or_replace_password(settings, 'email_smtp_password', request.POST)
        settings.email_use_tls = request.POST.get('email_use_tls') == '1'

        # Security profile
        settings.security_email_from_address = request.POST.get('security_email_from_address', '').strip()
        settings.security_email_smtp_host = request.POST.get('security_email_smtp_host', '').strip()
        try:
            settings.security_email_smtp_port = int(request.POST.get('security_email_smtp_port', 587))
        except (ValueError, TypeError):
            settings.security_email_smtp_port = 587
        settings.security_email_smtp_user = request.POST.get('security_email_smtp_user', '').strip()
        _keep_or_replace_password(settings, 'security_email_smtp_password', request.POST)
        settings.security_email_use_tls = request.POST.get('security_email_use_tls') == '1'

        # News profile
        settings.news_email_from_address = request.POST.get('news_email_from_address', '').strip()
        settings.news_email_smtp_host = request.POST.get('news_email_smtp_host', '').strip()
        try:
            settings.news_email_smtp_port = int(request.POST.get('news_email_smtp_port', 587))
        except (ValueError, TypeError):
            settings.news_email_smtp_port = 587
        settings.news_email_smtp_user = request.POST.get('news_email_smtp_user', '').strip()
        _keep_or_replace_password(settings, 'news_email_smtp_password', request.POST)
        settings.news_email_use_tls = request.POST.get('news_email_use_tls') == '1'

        if 'og_image' in request.FILES:
            settings.og_image = request.FILES['og_image']
        settings.save()  # Persist all changes to the database
        return JsonResponse({'success': True, 'message': 'Settings saved successfully!'})
    # For GET requests, fetch all shipping companies to display in the settings page
    shipping_companies = ShippingCompany.objects.all()
    team_members = list(TeamMember.objects.all())

    return render(request, 'settings/settings.html', {
        'team_members': team_members,
        # Serialised for the edit form, so clicking Edit fills the fields from
        # data already on the page instead of a round trip per click.
        'team_members_json': json.dumps([_team_member_payload(m) for m in team_members]),
        'settings': settings,
        'shipping_companies': shipping_companies,
    })


@module_required('settings')
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

        # ---------------------------------------------------------------------
        # SAVING THIS PAGE MUST NOT DESTROY THE RATES IT IS NOT EDITING
        # ---------------------------------------------------------------------
        # These nine were each parsed with float() and zeroed on ValueError.
        # Because this form posts every rate together, changing ONE of them and
        # saving sent the rest through the same parse - and any that arrived
        # blank was written as 0. Editing the sea rate wiped the air rate, on
        # the one page in the product whose entire job is holding rates.
        #
        # A rate of 0 is not a cheap rate. The quoting engine reads it as "no
        # published rate for this lane", so the public calculator stops
        # answering for that route entirely.
        # ---------------------------------------------------------------------
        for _rate_field in (
            'air_shipping_rate', 'sea_shipping_rate', 'ksa_shipping_rate',
            'ksa_air_shipping_rate', 'ksa_sea_shipping_rate',
            'no_brand_battery_air_shipping_rate', 'no_brand_battery_sea_shipping_rate',
            'no_brand_battery_ksa_air_shipping_rate', 'no_brand_battery_ksa_sea_shipping_rate',
        ):
            if _rate_field in request.POST:
                setattr(settings, _rate_field, _to_decimal(
                    request.POST.get(_rate_field), getattr(settings, _rate_field)))

        # The air volumetric rule and the minimum charges.
        #
        # _to_decimal rather than the float() pattern above: it keeps the
        # CURRENT value when a field is missing or unparseable, instead of
        # writing 0. That matters most for the divisor, where a 0 would silently
        # switch every air quote onto the 6000 fallback, and for the minimums,
        # where a 0 would stop charging them at all. Neither failure announces
        # itself - the quotes just quietly change.
        settings.volumetric_divisor = _to_decimal(
            request.POST.get('volumetric_divisor'), settings.volumetric_divisor)
        settings.min_chargeable_kg = _to_decimal(
            request.POST.get('min_chargeable_kg'), settings.min_chargeable_kg)
        settings.min_cbm = _to_decimal(
            request.POST.get('min_cbm'), settings.min_cbm)

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

        # A rate per KG only becomes a price once you know which kilograms are
        # charged, so the divisor and the minimums are saved alongside the rates.
        # These keep their current value when the field is absent rather than
        # resetting to 0, so a form that predates them cannot wipe them.
        for field in ('volumetric_divisor', 'min_chargeable_kg', 'min_cbm'):
            setattr(company, field,
                    _to_decimal(request.POST.get(field), getattr(company, field)))

        company.save()
        _save_company_rate_sheet(company)  # Regenerate the sheet with new rates
        return JsonResponse({'success': True, 'message': f'Rates saved for {company.name}!', 'sheet_url': company.shipping_rate_sheet.url if company.shipping_rate_sheet else ''})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('settings')
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


# =============================================================================
# RATE REQUEST SHEETS
# =============================================================================
# The document a freight forwarder actually fills in: one workbook per company
# per method, one tab per destination country, one row per cargo type.
#
# These replace the single fixed eight-row sheet above, which could only ever
# express two countries and two cargo types because that is all the old columns
# could hold. The older endpoints are left alone so nothing that still points at
# them breaks.
# =============================================================================


def _method_from(request, default=ShippingRate.METHOD_AIR):
    """Read and validate the air/sea parameter from a request."""
    value = (request.GET.get('method') or request.POST.get('method') or default).lower()
    return value if value in (ShippingRate.METHOD_AIR, ShippingRate.METHOD_SEA) else default


@module_required('settings')
def rate_request_download(request, company_id):
    """
    Download the rate request workbook for one company and one method.

    Args:
        request (HttpRequest): ``?method=air`` or ``?method=sea``.
        company_id (int): the ShippingCompany.

    Returns:
        HttpResponse: the .xlsx as an attachment.

    The file streams straight back rather than being written to MEDIA_ROOT and
    linked. A rate sheet is generated fresh every time - it has to reflect the
    destinations and cargo types that exist right now - so storing each one
    would accumulate stale files that differ from what the page offers. A copy
    IS recorded against the company (ShippingRateSheet) so there is a history of
    what was sent, but the download the user gets is the live one.
    """
    try:
        company = ShippingCompany.objects.get(id=company_id)
    except ShippingCompany.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Not found'}, status=404)

    method = _method_from(request)
    settings = CompanySettings.get_settings()

    workbook = rate_sheets.build_rate_request(
        company, method, currency=settings.currency or 'AED')

    from io import BytesIO
    buffer = BytesIO()
    workbook.save(buffer)
    payload = buffer.getvalue()

    label = 'Air' if method == ShippingRate.METHOD_AIR else 'Sea'
    safe_name = re.sub(r'[^A-Za-z0-9]+', '_', company.name)[:40].strip('_') or 'Company'
    filename = f'{safe_name}_{label}_Rate_Request.xlsx'

    # Record what was issued. Failing to file the copy must not deny the user
    # their download, so this is best-effort.
    try:
        sheet = ShippingRateSheet(company=company, method=method)
        sheet.workbook.save(filename, ContentFile(payload), save=False)
        sheet.save()
    except Exception:
        pass

    response = HttpResponse(
        payload,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@module_required('settings')
def rate_request_upload(request, company_id):
    """
    Read a filled rate request back into the rate table.

    Args:
        request (HttpRequest): POST with ``sheet`` (the .xlsx) and ``method``.
        company_id (int): the ShippingCompany.

    Returns:
        JsonResponse: {'success': True, 'message': ..., 'detail': {...}}

    The response reports what changed rather than just succeeding, because the
    interesting outcome of an import is the rows that did NOT land - a rate
    silently skipped looks exactly like a rate the forwarder never quoted.
    """
    try:
        company = ShippingCompany.objects.get(id=company_id)
    except ShippingCompany.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Not found'}, status=404)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})

    uploaded = request.FILES.get('sheet')
    if not uploaded:
        return JsonResponse({'success': False, 'message': 'Choose the completed Excel file first.'})

    method = _method_from(request)

    try:
        report = rate_sheets.apply_rate_request(company, method, uploaded)
    except Exception as error:                                  # noqa: BLE001
        # The message names the file, not the code: whoever uploads this is
        # holding a spreadsheet a forwarder emailed them, and "invalid format"
        # gives them nothing to act on.
        return JsonResponse({
            'success': False,
            'message': f'That file could not be read as a rate sheet ({error}). '
                       'Please upload the .xlsx we generated, with the ref column intact.',
        })

    if not report.sheets_read:
        return JsonResponse({
            'success': False,
            'message': 'No rate rows were found. Check this is the rate request '
                       'workbook and that at least one rate has been filled in.',
        })

    ShippingRateSheet.objects.filter(company=company, method=method).update(
        imported_at=timezone.now())

    return JsonResponse({
        'success': True,
        'message': f'{company.name}: {report.summary()}',
        'detail': {
            'created': report.created,
            'updated': report.updated,
            'unchanged': report.unchanged,
            'skipped_blank': report.skipped_blank,
            'unmatched': report.unmatched,
            'sheets': report.sheets_read,
        },
    })


@module_required('settings')
def rate_matrix(request):
    """
    Every rate on file, as one table.

    Returns:
        JsonResponse: rows of company / destination / cargo type / method / rate.

    Exists so the staff screen can show what is actually configured. With rates
    spread across companies, countries and cargo types, "do we have a sea rate
    for beauty products to Saudi?" stopped being answerable by looking at a
    form.
    """
    rows = []
    for rate in (ShippingRate.objects
                 .select_related('company', 'destination', 'cargo_type')
                 .filter(rate__gt=0)):
        rows.append({
            'company': rate.company.name,
            'company_id': rate.company_id,
            'destination': rate.destination.name,
            'destination_code': rate.destination.code,
            'cargo_type': rate.cargo_type.name,
            'cargo_slug': rate.cargo_type.slug,
            'method': rate.method,
            'rate': str(rate.rate),
            'minimum': str(rate.minimum),
            'divisor': str(rate.volumetric_divisor),
            'transit_days': rate.transit_days,
        })
    return JsonResponse({'rates': rows})


# =============================================================================
# TEAM MEMBERS
# =============================================================================
# The people shown in "Meet Our Team" on the About page. Managed here rather
# than hardcoded in the template, because a named person with a job title is a
# factual claim about the business and it has to be the owner who makes it.
# =============================================================================


def _team_member_payload(member):
    """One member as the settings screen's JavaScript expects them."""
    return {
        'id': member.id,
        'name': member.name,
        'role': member.role,
        'bio': member.bio,
        'email': member.email,
        'linkedin_url': member.linkedin_url,
        'sort_order': member.sort_order,
        'is_active': member.is_active,
        'photo_url': member.photo.url if member.photo else '',
        'initials': member.initials,
    }


@module_required('settings')
def team_member_save(request, member_id=None):
    """
    Create or update a team member.

    Args:
        request (HttpRequest): multipart POST — name, role, bio, email,
            linkedin_url, sort_order, is_active, and optionally photo.
        member_id (int | None): the member to update, or None to create.

    Returns:
        JsonResponse: {'success': True, 'member': {...}}

    The photo is optional on update and left untouched when no new file is
    sent — otherwise editing somebody's job title would silently delete their
    photograph.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'}, status=405)

    if member_id:
        member = TeamMember.objects.filter(id=member_id).first()
        if member is None:
            return JsonResponse({'success': False, 'message': 'Not found'}, status=404)
    else:
        member = TeamMember()

    name = (request.POST.get('name') or '').strip()
    role = (request.POST.get('role') or '').strip()
    if not name or not role:
        return JsonResponse({
            'success': False,
            'message': 'A name and a job title are both required.',
        })

    member.name = name[:120]
    member.role = role[:120]
    member.bio = (request.POST.get('bio') or '').strip()[:250]
    member.email = (request.POST.get('email') or '').strip()[:254]
    member.linkedin_url = (request.POST.get('linkedin_url') or '').strip()[:255]
    member.sort_order = _to_int(request.POST.get('sort_order'), member.sort_order or 0, lo=0, hi=999)
    member.is_active = request.POST.get('is_active') in ('1', 'true', 'on', 'True')

    photo = request.FILES.get('photo')
    if photo:
        member.photo = photo

    member.save()
    return JsonResponse({'success': True,
                         'message': f'Saved {member.name}.',
                         'member': _team_member_payload(member)})


@module_required('settings')
def team_member_delete(request, member_id):
    """Remove a team member. The photo file goes with the row."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'}, status=405)

    member = TeamMember.objects.filter(id=member_id).first()
    if member is None:
        return JsonResponse({'success': False, 'message': 'Not found'}, status=404)

    name = member.name
    member.delete()
    return JsonResponse({'success': True, 'message': f'Removed {name}.'})


@module_required('settings')
def team_member_list(request):
    """Every team member, for the settings screen to re-render its list."""
    return JsonResponse({
        'members': [_team_member_payload(m) for m in TeamMember.objects.all()],
    })
