"""
Products Views — Product Catalog Management, Quotation Generation & Bulk Import

Business Context:
This module is the heart of the product catalog system. In this logistics business, the admin:
1. Maintains a catalog of products with prices, weights, dimensions, and images
2. Generates a public-facing product catalogue for customers to browse
3. Exports Excel catalogues and supplier quote request templates
4. Bulk imports products from spreadsheets, photos, or 1688 (Chinese wholesale platform)
5. Manages product visibility (public/private) and draft status

Key Concepts:
- Product: A sellable item with name, price, MOQ, weight, carton dimensions
- ProductImage: Up to 3 images per product (stored in MEDIA_ROOT)
- CBM: Cubic Meters per carton (used for sea freight cost calculations)
- Draft vs Published: Draft products are hidden from customers; published products appear in catalogues
- Private vs Public: Private products are hidden from the general catalogue but can be assigned to specific customers

Django Concepts Used:
- @login_required: Protects admin-only views (catalogue management, export).
- @csrf_exempt: Allows AJAX endpoints to accept requests without CSRF token.
- request.FILES.getlist('images'): Handles multiple file uploads from HTML forms.
- Decimal: Used for all money calculations to avoid floating-point errors (0.1 + 0.2 != 0.3).
- prefetch_related('images'): Fetches related images in a separate query to avoid the N+1 problem.
- Product.objects.create(): Creates a new database row for a product.
- Product.objects.filter(is_draft=False): QuerySet filtering to show only published products.
"""

import csv
import io
import os
import re
from decimal import Decimal, InvalidOperation
from django.contrib.auth.decorators import login_required
# Role-aware access guard: only users whose profile grants the 'products' module
# (admins always, or staff with perm_products) may reach these views.
from accounts.decorators import module_required
from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .models import Product, ProductImage

# Paginator for list view pagination — improves performance and UX for large datasets.
from django.core.paginator import Paginator

from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from settings_manager.models import CompanySettings
from customers.models import Customer
from utils.email_utils import send_typed_email


@module_required('products')
def product_list(request):
    """
    Display the admin product list page with public and private products.

    Args:
        request (HttpRequest): The incoming HTTP request from the browser.

    Returns:
        HttpResponse: A rendered HTML page showing all products, grouped into public and private.

    Business Logic:
        The admin sees all products in one dashboard. Products are split into two tabs:
        - Public products: visible in the general catalogue
        - Private products: hidden from the general catalogue (typically assigned to specific customers)
        Shipping rates and exchange rate settings are passed to the template so the frontend
        can calculate estimated shipping costs per product.

    Django Concepts:
        - CompanySettings.get_settings(): Returns the singleton settings row (company-wide config).
        - _annotate_cbm(): A local helper that adds a 'carton_cbm' attribute to each product
          by computing (length × width × height) / 1,000,000 from the carton dimensions.
        - Product.objects.prefetch_related('images'): Fetches all images in 2 queries instead of N+1.
        - .filter(is_private=False): QuerySet filter for public products only.
    """
    # Fetch company settings to get shipping rates and exchange rate info
    settings = CompanySettings.get_settings()
    # Convert shipping rates to float for the template (used in frontend calculations)
    air_rate = float(settings.air_shipping_rate or 0)
    sea_rate = float(settings.sea_shipping_rate or 0)
    ksa_air_rate = float(settings.ksa_air_shipping_rate or 0)
    ksa_sea_rate = float(settings.ksa_sea_shipping_rate or 0)
    # Check if currency exchange is enabled (e.g., RMB to AED conversion)
    fx_enabled = settings.exchange_rate_enabled and settings.exchange_rate and settings.exchange_rate > 0
    fx_rate = float(settings.exchange_rate) if fx_enabled else 0
    fx_from = settings.exchange_rate_from if fx_enabled else ''
    fx_to = settings.exchange_rate_to if fx_enabled else ''

    # Helper function: calculate CBM (cubic meters per carton) for each product in a queryset
    def _annotate_cbm(qs):
        products = list(qs)
        for p in products:
            # If all three carton dimensions are available, compute CBM
            # CBM = (L × W × H) / 1,000,000 (converts cm³ to m³)
            if p.carton_length and p.carton_width and p.carton_height:
                p.carton_cbm = float(Decimal(str(p.carton_length)) * Decimal(str(p.carton_width)) * Decimal(str(p.carton_height)) / Decimal('1000000'))
            else:
                p.carton_cbm = None
        return products

    # --- Search ---
    # Filtering runs in the database so it covers the whole catalogue, not just the
    # 24 cards rendered on the current page.
    query = request.GET.get('q', '').strip()
    public_qs = Product.objects.prefetch_related('images').filter(is_private=False)
    private_qs = Product.objects.prefetch_related('images').filter(is_private=True)
    if query:
        search_filter = Q(name__icontains=query) | Q(sku__icontains=query)
        public_qs = public_qs.filter(search_filter)
        private_qs = private_qs.filter(search_filter)

    # Fetch public products (not private), with images, ordered by draft status then name
    products = _annotate_cbm(public_qs.order_by('is_draft', 'name'))
    # Fetch private products (hidden from general catalogue)
    private_products = _annotate_cbm(private_qs.order_by('is_draft', 'name'))

    # --- Pagination ---
    # The page number comes from the URL query string: ?page=N
    page_number = request.GET.get('page', 1)
    paginator = Paginator(products, 24)
    page_obj = paginator.get_page(page_number)

    return render(request, 'products/product_list.html', {
        'products': products,
        'private_products': private_products,
        'page_obj': page_obj,
        'query': query,
        'public_count': paginator.count,
        'private_count': len(private_products),
        'air_rate': air_rate,
        'sea_rate': sea_rate,
        'ksa_air_rate': ksa_air_rate,
        'ksa_sea_rate': ksa_sea_rate,
        'currency': settings.currency,
        'fx_enabled': fx_enabled,
        'fx_rate': fx_rate,
        'fx_from': fx_from,
        'fx_to': fx_to,
    })


def _notify_new_marketplace_product(product, settings):
    """
    Send a news email to all active customers when an Amazon/Noon product is published.

    Args:
        product (Product): The newly published marketplace product.
        settings (CompanySettings): Company settings for context.

    Returns:
        int: Number of emails sent.
    """
    if product.is_draft or product.source not in {'amazon', 'noon'}:
        return 0

    customers = Customer.objects.filter(is_active=True).exclude(email__isnull=True).exclude(email='')
    if not customers.exists():
        return 0

    first_image = product.images.first()
    first_image_url = ''
    if first_image and first_image.image:
        try:
            first_image_url = first_image.image.url
        except Exception:
            first_image_url = ''

    context = {
        'product': product,
        'source': product.source,
        'settings': settings,
        'first_image': first_image,
        'first_image_url': first_image_url,
        'url': f'/portal/products/{product.source}/',
    }
    html_message = render_to_string('emails/new_product_announcement.html', context)
    plain_message = strip_tags(html_message)

    recipients = [c.email for c in customers]
    return send_typed_email(
        email_type='news',
        subject=f'New {product.source.title()} Product: {product.name}',
        message=plain_message,
        recipient_list=recipients,
        html_message=html_message,
    )


@module_required('products')
@csrf_exempt
def add_product(request):
    """
    AJAX endpoint: Add a new product to the catalog.

    Args:
        request (HttpRequest): The incoming AJAX POST request with product data and images.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        When the admin sources a new product from a supplier, they add it here with:
        - Name, price, MOQ (minimum order quantity)
        - Weight, carton dimensions (for shipping calculations)
        - Up to 3 images
        - Draft status (can save as draft before publishing)

    Django Concepts:
        - request.POST.get('name'): Extracts text form data.
        - request.FILES.getlist('images'): Gets multiple uploaded image files.
        - request.POST.get('is_draft') == '1': Checkbox values come as '1' or None.
        - Product.objects.create(): Creates and saves the product in one database call.
        - ProductImage.objects.create(product=product, image=img): Links each image to the product.
    """
    if request.method == 'POST':
        name = request.POST.get('name')
        price = request.POST.get('price')
        moq = request.POST.get('moq')
        # Optional fields: default to None if not provided or empty string
        weight = request.POST.get('weight') or None
        carton_length = request.POST.get('carton_length') or None
        carton_width = request.POST.get('carton_width') or None
        carton_height = request.POST.get('carton_height') or None
        carton_qty = request.POST.get('carton_qty') or None
        sku = request.POST.get('sku', '').strip()
        images = request.FILES.getlist('images')  # Multiple image files from the form
        is_draft = request.POST.get('is_draft') == '1'  # Checkbox: '1' means checked
        source = request.POST.get('source', 'general').strip().lower()
        if source not in {'general', 'amazon', 'noon'}:
            source = 'general'
        ready_to_ship = request.POST.get('ready_to_ship') == '1'
        # Create the product in the database
        product = Product.objects.create(
            name=name,
            price=price,
            moq=moq,
            weight=weight,
            carton_length=carton_length,
            carton_width=carton_width,
            carton_height=carton_height,
            carton_qty=carton_qty,
            sku=sku,
            is_draft=is_draft,
            source=source,
            ready_to_ship=ready_to_ship,
        )
        # Create ProductImage records for each uploaded image (limit to first 3)
        for img in images[:3]:
            ProductImage.objects.create(product=product, image=img)
        # Notify customers if this is a published Amazon/Noon product
        settings = CompanySettings.get_settings()
        _notify_new_marketplace_product(product, settings)
        # Return a different message depending on whether it was saved as draft or published
        label = 'Draft saved!' if is_draft else 'Product added successfully!'
        return JsonResponse({'success': True, 'message': label})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('products')
@csrf_exempt
def edit_product(request, product_id):
    """
    AJAX endpoint: Edit an existing product's details.

    Args:
        request (HttpRequest): The incoming GET or POST request.
        product_id (int): The primary key of the product to edit.

    Returns:
        JsonResponse (GET): The product's current data including images.
        JsonResponse (POST): {'success': True/False, 'message': '...'} after saving.

    Business Logic:
        The admin can edit any product field. For GET requests, the frontend fetches the
        current data to populate an edit form. For POST requests, the updated data is saved.
        Images can be deleted or added (up to 3 total).

    Django Concepts:
        - get_object_or_404(Product, id=product_id): Safely fetches the product or returns 404.
        - product.images.all(): Returns all ProductImage objects linked to this product.
        - request.POST.getlist('delete_image_ids'): Gets multiple values for the same key (checkbox array).
        - max(0, 3 - current_count): Calculates how many new images can be added without exceeding the limit.
    """
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'GET':
        # Build a list of image dictionaries for the frontend edit form
        images = [{'id': img.id, 'url': img.image.url} for img in product.images.all()]
        return JsonResponse({
            'id': product.id,
            'name': product.name,
            'price': str(product.price),
            'moq': product.moq,
            'weight': str(product.weight) if product.weight else '',
            'carton_length': str(product.carton_length) if product.carton_length else '',
            'carton_width': str(product.carton_width) if product.carton_width else '',
            'carton_height': str(product.carton_height) if product.carton_height else '',
            'carton_qty': product.carton_qty or '',
            'sku': product.sku,
            'is_draft': product.is_draft,
            'source': product.source,
            'ready_to_ship': product.ready_to_ship,
            'images': images,
        })
    if request.method == 'POST':
        # Update product fields from POST data; use existing values as defaults
        product.name = request.POST.get('name', product.name)
        product.price = request.POST.get('price', product.price)
        product.moq = request.POST.get('moq', product.moq)
        product.weight = request.POST.get('weight') or None
        product.carton_length = request.POST.get('carton_length') or None
        product.carton_width = request.POST.get('carton_width') or None
        product.carton_height = request.POST.get('carton_height') or None
        product.carton_qty = request.POST.get('carton_qty') or None
        product.sku = request.POST.get('sku', '').strip()
        product.is_draft = request.POST.get('is_draft') == '1'
        source = request.POST.get('source', product.source).strip().lower()
        if source in {'general', 'amazon', 'noon'}:
            product.source = source
        product.ready_to_ship = request.POST.get('ready_to_ship') == '1'
        was_draft = product.is_draft
        product.is_draft = request.POST.get('is_draft') == '1'
        product.save()
        # If a marketplace product was just published, notify customers
        if was_draft and not product.is_draft and product.source in {'amazon', 'noon'}:
            settings = CompanySettings.get_settings()
            _notify_new_marketplace_product(product, settings)
        # Handle deleted images: remove the specified image IDs from the database
        delete_ids = request.POST.getlist('delete_image_ids')
        if delete_ids:
            ProductImage.objects.filter(id__in=delete_ids, product=product).delete()
        # Add new images, but don't exceed the 3-image limit per product
        new_images = request.FILES.getlist('images')
        current_count = product.images.count()
        for img in new_images[:max(0, 3 - current_count)]:
            ProductImage.objects.create(product=product, image=img)
        return JsonResponse({'success': True, 'message': f'{product.name} updated!'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('products')
@csrf_exempt
def save_product_prices(request, product_id):
    """
    AJAX endpoint: Save the air and sea shipping-inclusive prices for a product.

    Args:
        request (HttpRequest): The incoming AJAX POST request with JSON body.
        product_id (int): The primary key of the product to update prices for.

    Returns:
        JsonResponse: {'success': True/False} or error status.

    Business Logic:
        The admin can set the "landed cost" prices for each product:
        - price_air: unit price + air shipping cost per piece
        - price_sea: unit price + sea shipping cost per piece
        These are pre-calculated so customers can see all-inclusive prices in the catalogue.

    Django Concepts:
        - json.loads(request.body): Parses the JSON body of the AJAX request.
        - Decimal(str(air)).quantize(Decimal('0.01')): Converts to Decimal and rounds to 2 decimal places.
        - product.save(update_fields=[...]): Only updates the specified fields (more efficient).
    """
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        import json
        data = json.loads(request.body)
        air = data.get('price_air')
        sea = data.get('price_sea')
        # Convert to Decimal and round to 2 decimal places for precise money storage
        product.price_air = Decimal(str(air)).quantize(Decimal('0.01')) if air is not None else None
        product.price_sea = Decimal(str(sea)).quantize(Decimal('0.01')) if sea is not None else None
        product.save(update_fields=['price_air', 'price_sea'])
        return JsonResponse({'success': True})
    return JsonResponse({'success': False}, status=400)


@module_required('products')
def product_catalogue(request):
    """
    Display the public-facing product catalogue for customers.

    Args:
        request (HttpRequest): The incoming HTTP request from the browser.

    Returns:
        HttpResponse: A rendered HTML page showing all published, non-private products.

    Business Logic:
        This is the "storefront" view that customers see. It shows only published products
        (not drafts) that are not private. If exchange rate is enabled, prices are shown
        in both the base currency and the converted currency (e.g., RMB and AED).

    Django Concepts:
        - Product.objects.prefetch_related('images').filter(is_draft=False, is_private=False):
          Only shows published, public products. prefetch_related avoids N+1 queries for images.
        - Decimal(str(settings.exchange_rate)): Converts the exchange rate to Decimal for precise math.
        - p.price_converted: A dynamically added attribute (not a DB field) for template use.
    """
    from settings_manager.models import CompanySettings
    from decimal import Decimal
    # Fetch only published, non-private products with their images, ordered alphabetically
    products = Product.objects.prefetch_related('images').filter(is_draft=False, is_private=False).order_by('name')
    settings = CompanySettings.get_settings()
    # Check if dual-currency display is enabled
    fx_enabled = settings.exchange_rate_enabled and settings.exchange_rate and settings.exchange_rate > 0
    fx_rate = Decimal(str(settings.exchange_rate)) if fx_enabled else None
    # Pre-compute converted price for every product so the template doesn't need to do math
    for p in products:
        if fx_enabled and p.price:
            # Converted price = base price / exchange rate (e.g., RMB to AED)
            p.price_converted = (Decimal(str(p.price)) / fx_rate).quantize(Decimal('0.01'))
        else:
            p.price_converted = None
    return render(request, 'products/catalogue.html', {
        'products': products,
        'settings': settings,
        'fx_enabled': fx_enabled,
        'fx_rate': fx_rate,
        'fx_from': settings.exchange_rate_from if fx_enabled else '',
        'fx_to': settings.exchange_rate_to if fx_enabled else '',
    })


@module_required('products')
def catalogue_excel_export(request):
    """
    Export all published products as a styled Excel (.xlsx) catalogue with embedded images.

    Args:
        request (HttpRequest): The incoming HTTP request.

    Returns:
        HttpResponse: A downloadable Excel file with all product data and images.

    Business Logic:
        The admin can download the full catalogue as an Excel file to share with customers
        via email or WhatsApp. The file includes product images, prices, shipping prices,
        dimensions, and CBM calculations. This is useful for offline sharing with buyers.

    Django Concepts:
        - Workbook() from openpyxl creates a new Excel file in memory.
        - ws.freeze_panes = 'A6': Keeps the header row visible when scrolling.
        - XLImage: Embeds actual image files into Excel cells.
        - io.BytesIO: Creates an in-memory buffer so no temp files are needed.
        - Content-Disposition: 'attachment' forces the browser to download the file.
    """
    import datetime
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.drawing.image import Image as XLImage
    from django.conf import settings as django_settings

    company = CompanySettings.get_settings()
    # Fetch all non-draft products with their images
    products = list(Product.objects.prefetch_related('images').filter(is_draft=False).order_by('name'))

    wb = Workbook()
    ws = wb.active
    ws.title = 'Product Catalogue'

    # --- Color palette for the dark-themed Excel style ---
    DARK_BG = '0F1117'
    MID_BG  = '141924'
    ACCENT  = '1E293B'
    BLUE    = '1D4ED8'
    ORANGE  = 'FF8C00'

    # --- Column definitions: (header text, width) ---
    IMG_COL = 2  # Column B is the image column
    cols = [
        ('No.',           6),
        ('Image',        12),
        ('Product Name', 34),
        ('Price',        13),
        ('Air Price',    13),
        ('Sea Price',    13),
        ('MOQ',           9),
        ('Weight (KG)',  13),
        ('L (CM)',        9),
        ('W (CM)',        9),
        ('H (CM)',        9),
        ('Pcs/Ctn',      10),
        ('CBM/Ctn',      11),
    ]
    NUM_COLS = len(cols)
    last_col = get_column_letter(NUM_COLS)

    # --- Row 1: Company name header (merged across all columns) ---
    ws.merge_cells(f'A1:{last_col}1')
    ws['A1'] = company.company_name or 'Product Catalogue'
    ws['A1'].font = Font(name='Calibri', size=16, bold=True, color='FFFFFF')
    ws['A1'].fill = PatternFill('solid', fgColor=BLUE)
    ws['A1'].alignment = Alignment(horizontal='left', vertical='center', indent=2)
    ws.row_dimensions[1].height = 36

    # --- Row 2: Contact info (phone and address) ---
    ws.merge_cells(f'A2:{last_col}2')
    parts = []
    if company.company_phone:
        parts.append(f'\U0001f4de {company.company_phone}')
    if company.company_address:
        parts.append(f'\U0001f4cd {company.company_address.replace(chr(10), "  ").strip()}')
    ws['A2'] = '    '.join(parts) if parts else ''
    ws['A2'].font = Font(name='Calibri', size=10, color='CBD5E1')
    ws['A2'].fill = PatternFill('solid', fgColor='1E3A5F')
    ws['A2'].alignment = Alignment(horizontal='left', vertical='center', indent=2)
    ws.row_dimensions[2].height = 22

    # --- Row 3: Catalogue title with date and product count ---
    ws.merge_cells(f'A3:{last_col}3')
    ws['A3'] = f'PRODUCT CATALOGUE  \u00b7  {datetime.date.today().strftime("%B %d, %Y")}  \u00b7  {len(products)} products'
    ws['A3'].font = Font(name='Calibri', size=9, bold=True, color=ORANGE)
    ws['A3'].fill = PatternFill('solid', fgColor=DARK_BG)
    ws['A3'].alignment = Alignment(horizontal='left', vertical='center', indent=2)
    ws.row_dimensions[3].height = 18

    # --- Row 4: Spacer row ---
    for c in range(1, NUM_COLS + 1):
        ws.cell(row=4, column=c).fill = PatternFill('solid', fgColor=DARK_BG)
    ws.row_dimensions[4].height = 6

    # --- Row 5: Column headers ---
    header_fill   = PatternFill('solid', fgColor=BLUE)
    header_border = Border(bottom=Side(style='medium', color='3B82F6'))
    for ci, (hdr, width) in enumerate(cols, start=1):
        cell = ws.cell(row=5, column=ci)
        cell.value = hdr
        cell.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        cell.fill = header_fill
        cell.border = header_border
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(ci)].width = width
    ws.row_dimensions[5].height = 28
    ws.freeze_panes = 'A6'  # Keep the header row visible when scrolling

    # --- Data rows: one row per product ---
    IMG_PX    = 70   # Target pixel size for embedded images
    ROW_H_IMG = 56   # Row height in points when an image is present
    ROW_H_STD = 22   # Standard row height when no image

    fill_odd   = PatternFill('solid', fgColor=MID_BG)
    fill_even  = PatternFill('solid', fgColor=ACCENT)
    row_border = Border(bottom=Side(style='thin', color='1F2937'))

    for i, p in enumerate(products, start=1):
        r = i + 5  # Data starts at row 6
        fill = fill_odd if i % 2 == 1 else fill_even  # Alternating row colors

        # Font styles for different data types
        no_font    = Font(name='Calibri', size=11, color='6B7280')
        name_font  = Font(name='Calibri', size=11, bold=True, color='F9FAFB')
        data_font  = Font(name='Calibri', size=11, color='D1D5DB')
        price_font = Font(name='Calibri', size=11, bold=True, color='FCD34D')

        # Calculate CBM per carton if dimensions are available
        cbm = '\u2014'
        if p.carton_length and p.carton_width and p.carton_height:
            cbm = round(float(p.carton_length) * float(p.carton_width) * float(p.carton_height) / 1_000_000, 4)

        # All values for this row, with their font and alignment
        row_vals = [
            (i,                                                         no_font,    'center'),
            (None,                                                      data_font,  'center'),  # image placeholder
            (p.name,                                                    name_font,  'left'),
            (float(p.price),                                            price_font, 'center'),
            (float(p.price_air)    if p.price_air    else '\u2014',     data_font,  'center'),
            (float(p.price_sea)    if p.price_sea    else '\u2014',     data_font,  'center'),
            (p.moq,                                                     data_font,  'center'),
            (float(p.weight)       if p.weight       else '\u2014',     data_font,  'center'),
            (float(p.carton_length) if p.carton_length else '\u2014',   data_font,  'center'),
            (float(p.carton_width)  if p.carton_width  else '\u2014',   data_font,  'center'),
            (float(p.carton_height) if p.carton_height else '\u2014',   data_font,  'center'),
            (p.carton_qty          if p.carton_qty   else '\u2014',     data_font,  'center'),
            (cbm,                                                       data_font,  'center'),
        ]

        has_image = False
        for ci, (val, font, align) in enumerate(row_vals, start=1):
            cell = ws.cell(row=r, column=ci, value=val)
            cell.font = font
            cell.fill = fill
            cell.border = row_border
            cell.alignment = Alignment(horizontal=align, vertical='center')

        # Try to embed the first product image in column B
        first_img = p.images.all().first()
        if first_img and first_img.image:
            img_path = os.path.join(django_settings.MEDIA_ROOT, str(first_img.image))
            if os.path.exists(img_path):
                try:
                    xl_img = XLImage(img_path)
                    # Scale to fit the cell while maintaining aspect ratio
                    orig_w = xl_img.width or IMG_PX
                    orig_h = xl_img.height or IMG_PX
                    scale = min(IMG_PX / orig_w, IMG_PX / orig_h)
                    xl_img.width  = int(orig_w * scale)
                    xl_img.height = int(orig_h * scale)
                    xl_img.anchor = f'{get_column_letter(IMG_COL)}{r}'
                    ws.add_image(xl_img)
                    has_image = True
                except Exception:
                    pass  # If image embedding fails, just skip it

        ws.row_dimensions[r].height = ROW_H_IMG if has_image else ROW_H_STD

    # --- Footer row ---
    foot_r = len(products) + 6
    ws.merge_cells(f'A{foot_r}:{last_col}{foot_r}')
    ws[f'A{foot_r}'] = f'Total: {len(products)} product(s)  \u00b7  Generated {datetime.date.today().strftime("%d %b %Y")}'
    ws[f'A{foot_r}'].font = Font(name='Calibri', size=9, italic=True, color='6B7280')
    ws[f'A{foot_r}'].fill = PatternFill('solid', fgColor=DARK_BG)
    ws[f'A{foot_r}'].alignment = Alignment(horizontal='right', vertical='center', indent=2)
    ws.row_dimensions[foot_r].height = 18

    # --- Output the Excel file as a download ---
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    filename = f'catalogue_{datetime.date.today().strftime("%Y%m%d")}.xlsx'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@module_required('products')
def supplier_quote_template(request, product_id):
    """
    Generate a per-product Supplier Quote Request Excel file.

    Args:
        request (HttpRequest): The incoming HTTP request.
        product_id (int): The primary key of the product to request a quote for.

    Returns:
        HttpResponse: A downloadable Excel file pre-filled with product specs,
                      with empty fields for the supplier to fill in their offer.

    Business Logic:
        When sourcing a product from a new supplier, the admin sends them this Excel file.
        Section 1 is pre-filled with the product's known specs (name, MOQ, target price).
        Section 2 is blank for the supplier to fill in their best offer (unit price, lead time, etc.).
        The supplier fills it in and returns it, allowing the admin to compare offers.

    Django Concepts:
        - get_object_or_404: Safely fetches the product.
        - openpyxl: Creates a structured Excel document with two sections.
        - PatternFill, Font, Alignment, Border, Side: Style the Excel cells for a professional look.
    """
    import datetime
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    product = get_object_or_404(Product, id=product_id)
    company = CompanySettings.get_settings()

    wb = Workbook()
    ws = wb.active
    ws.title = 'Supplier Quote Request'

    # --- Color palette ---
    BLUE      = '1D4ED8'
    DARK_BG   = '0F1117'
    NAVY      = '1E3A5F'
    ORANGE    = 'FF8C00'
    AMBER_BG  = '1C1A0F'
    GREEN_BG  = '0D1F0D'

    ws.column_dimensions['A'].width = 28
    ws.column_dimensions['B'].width = 44

    # --- Helper: create a styled header/label cell ---
    def _hdr_cell(r, label):
        c = ws.cell(row=r, column=1, value=label)
        c.font      = Font(name='Calibri', size=10, bold=True, color='94A3B8')
        c.fill      = PatternFill('solid', fgColor='141924')
        c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        c.border    = Border(bottom=Side(style='thin', color='1F2937'))
        return c

    # --- Helper: create a styled value cell ---
    def _val_cell(r, value, bg='141924', color='F9FAFB', bold=False):
        c = ws.cell(row=r, column=2, value=value)
        c.font      = Font(name='Calibri', size=11, bold=bold, color=color)
        c.fill      = PatternFill('solid', fgColor=bg)
        c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        c.border    = Border(bottom=Side(style='thin', color='1F2937'))
        return c

    # --- Helper: create a section title row (merged across both columns) ---
    def _section_title(r, text, bg=BLUE, color='FFFFFF'):
        ws.merge_cells(f'A{r}:B{r}')
        c = ws.cell(row=r, column=1, value=text)
        c.font      = Font(name='Calibri', size=11, bold=True, color=color)
        c.fill      = PatternFill('solid', fgColor=bg)
        c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        ws.row_dimensions[r].height = 24
        return c

    # --- Row 1: Company name ---
    ws.merge_cells('A1:B1')
    ws['A1'] = company.company_name or 'Quote Request'
    ws['A1'].font      = Font(name='Calibri', size=15, bold=True, color='FFFFFF')
    ws['A1'].fill      = PatternFill('solid', fgColor=BLUE)
    ws['A1'].alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[1].height = 34

    # --- Row 2: Contact info ---
    ws.merge_cells('A2:B2')
    parts = []
    if company.company_phone:
        parts.append(f'\U0001f4de {company.company_phone}')
    if company.company_address:
        parts.append(f'\U0001f4cd {company.company_address.replace(chr(10), "  ").strip()}')
    ws['A2'] = '    '.join(parts) if parts else ''
    ws['A2'].font      = Font(name='Calibri', size=9, color='CBD5E1')
    ws['A2'].fill      = PatternFill('solid', fgColor=NAVY)
    ws['A2'].alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[2].height = 20

    # --- Row 3: Document title and date ---
    ws.merge_cells('A3:B3')
    ws['A3'] = f'SUPPLIER QUOTE REQUEST  \u00b7  {datetime.date.today().strftime("%d %B %Y")}'
    ws['A3'].font      = Font(name='Calibri', size=9, bold=True, color=ORANGE)
    ws['A3'].fill      = PatternFill('solid', fgColor=DARK_BG)
    ws['A3'].alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[3].height = 16

    # --- Row 4: Spacer ---
    for col in range(1, 3):
        ws.cell(row=4, column=col).fill = PatternFill('solid', fgColor=DARK_BG)
    ws.row_dimensions[4].height = 8

    # --- Section 1: Product Specifications (pre-filled, read-only) ---
    _section_title(5, '\u25a3  SECTION 1 \u2014 Product Specifications  (pre-filled, do not edit)', bg='1E3A5F', color='93C5FD')

    # Calculate CBM if all dimensions are available
    cbm = None
    if product.carton_length and product.carton_width and product.carton_height:
        cbm = round(float(product.carton_length) * float(product.carton_width) * float(product.carton_height) / 1_000_000, 4)
    dim_str = (
        f'{product.carton_length} \u00d7 {product.carton_width} \u00d7 {product.carton_height} CM'
        if product.carton_length and product.carton_width and product.carton_height else '\u2014'
    )

    # Pre-filled specification rows for the supplier to see
    spec_rows = [
        ('Product Name',      product.name),
        ('Our MOQ',           product.moq),
        ('Weight per Unit',   f'{product.weight} KG' if product.weight else '\u2014'),
        ('Carton Dimensions', dim_str),
        ('CBM per Carton',    cbm if cbm else '\u2014'),
        ('Pcs per Carton',    product.carton_qty if product.carton_qty else '\u2014'),
        ('Our Target Price',  f'{product.price} {company.currency or "USD"}'),
    ]

    for ri, (lbl, val) in enumerate(spec_rows, start=6):
        _hdr_cell(ri, lbl)
        # Highlight the target price in orange for emphasis
        _val_cell(ri, str(val), bg=AMBER_BG,
                  color=ORANGE if lbl == 'Our Target Price' else 'F9FAFB',
                  bold=(lbl == 'Our Target Price'))
        ws.row_dimensions[ri].height = 22

    SPEC_END = 6 + len(spec_rows) - 1  # Index of the last specification row

    # --- Instruction banner asking the supplier to fill Section 2 ---
    BANNER_R = SPEC_END + 1
    ws.merge_cells(f'A{BANNER_R}:B{BANNER_R}')
    ws[f'A{BANNER_R}'] = (
        '\u2709  Dear Supplier \u2014 Please complete Section 2 below with your best offer and return this file.'
    )
    ws[f'A{BANNER_R}'].font      = Font(name='Calibri', size=10, bold=True, color='FEF9C3')
    ws[f'A{BANNER_R}'].fill      = PatternFill('solid', fgColor='78350F')
    ws[f'A{BANNER_R}'].alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[BANNER_R].height = 26

    # --- Spacer ---
    SP2 = BANNER_R + 1
    for col in range(1, 3):
        ws.cell(row=SP2, column=col).fill = PatternFill('solid', fgColor=DARK_BG)
    ws.row_dimensions[SP2].height = 8

    # --- Section 2: Supplier Offer (blank fields for the supplier to fill in) ---
    SEC2_R = SP2 + 1
    _section_title(SEC2_R, '\u25a3  SECTION 2 \u2014 Supplier Offer  (please fill in)', bg='14532D', color='86EFAC')

    offer_fields = [
        'Supplier / Company Name',
        'Contact Person',
        'Email / Phone',
        'Unit Price (per piece)',
        'Minimum Order Quantity',
        'Lead Time (days)',
        'Sample Available? (Yes / No)',
        'Sample Price',
        'Payment Terms',
        'Price Validity Date',
        'Remarks / Notes',
    ]

    for ri, lbl in enumerate(offer_fields, start=SEC2_R + 1):
        c_lbl = _hdr_cell(ri, lbl)
        c_lbl.fill = PatternFill('solid', fgColor='141924')
        # Blank value cells with green background to indicate they should be filled in
        c_val = ws.cell(row=ri, column=2, value='')
        c_val.fill      = PatternFill('solid', fgColor=GREEN_BG)
        c_val.border    = Border(
            bottom=Side(style='thin', color='166534'),
            left=Side(style='thin',   color='166534'),
        )
        c_val.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        ws.row_dimensions[ri].height = 22

    # --- Footer ---
    FOOT_R = SEC2_R + 1 + len(offer_fields) + 1
    ws.merge_cells(f'A{FOOT_R}:B{FOOT_R}')
    ws[f'A{FOOT_R}'] = f'{company.company_name or ""}  \u00b7  Confidential \u2014 for supplier use only'
    ws[f'A{FOOT_R}'].font      = Font(name='Calibri', size=8, italic=True, color='4B5563')
    ws[f'A{FOOT_R}'].fill      = PatternFill('solid', fgColor=DARK_BG)
    ws[f'A{FOOT_R}'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[FOOT_R].height = 16

    # --- Output as downloadable Excel file ---
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    safe_name = re.sub(r'[^\w\s-]', '', product.name).strip().replace(' ', '_')
    filename   = f'{safe_name}_quote_request.xlsx'
    response   = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@module_required('products')
@csrf_exempt
def delete_product(request, product_id):
    """
    AJAX endpoint: Delete a product from the catalog.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        product_id (int): The primary key of the Product to delete.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        If a product is discontinued or was added by mistake, the admin removes it.
        This also deletes associated images (if the model uses CASCADE on_delete).

    Django Concepts:
        - product.delete(): Removes the product from the database. Related ProductImage
          records will also be deleted if their foreign key uses on_delete=models.CASCADE.
    """
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        name = product.name
        product.delete()
        return JsonResponse({'success': True, 'message': f'{name} deleted!'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('products')
def bulk_upload_template(request):
    """
    Generate a bulk product upload template Excel file.

    Args:
        request (HttpRequest): The incoming HTTP request.

    Returns:
        HttpResponse: A downloadable Excel template with example data.

    Business Logic:
        When the admin needs to add many products at once (e.g., 50 new items from a supplier),
        they download this template, fill it in with product data, and upload it back.
        The template includes required fields (name, price, MOQ) and optional fields (weight, dimensions).
        It also has example rows showing the expected format.

    Django Concepts:
        - openpyxl Workbook: Creates an Excel file with headers, instructions, and example data.
        - ws.freeze_panes = 'A8': Keeps the header row visible when scrolling through data.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    company = CompanySettings.get_settings()

    wb = Workbook()
    ws = wb.active
    ws.title = 'Products'

    # Column definitions: (field name, width, required, example1, example2)
    columns = [
        ('name',           30, True,  'Red Widget Pro',    'Blue Water Bottle'),
        ('image',          20, False, '',                  ''),
        ('price',          14, True,  '12.50',             '8.00'),
        ('moq',            10, True,  '100',               '50'),
        ('weight',         14, False, '0.500',             '0.350'),
        ('carton_length',  18, False, '35',                '28'),
        ('carton_width',   16, False, '25',                '20'),
        ('carton_height',  16, False, '20',                '15'),
        ('carton_qty',     14, False, '12',                '24'),
        ('source',         12, False, 'general',           'amazon'),
        ('ready_to_ship',  16, False, '0',                 '1'),
    ]
    IMAGE_COL = 2  # Column index (1-based) of the image column
    NUM_COLS = len(columns)
    last_col = get_column_letter(NUM_COLS)

    DARK_BG    = '0F1117'
    MID_BG     = '141924'
    ACCENT_BG  = '1E293B'
    BLUE       = '1D4ED8'
    ORANGE     = 'FF8C00'

    # --- Row 1: Company name ---
    ws.merge_cells(f'A1:{last_col}1')
    ws['A1'] = company.company_name or 'My Company'
    ws['A1'].font = Font(name='Calibri', size=16, bold=True, color='FFFFFF')
    ws['A1'].fill = PatternFill('solid', fgColor=BLUE)
    ws['A1'].alignment = Alignment(horizontal='left', vertical='center', indent=2)
    ws.row_dimensions[1].height = 36

    # --- Row 2: Phone and Address ---
    ws.merge_cells(f'A2:{last_col}2')
    contact_parts = []
    if company.company_phone:
        contact_parts.append(f'📞 {company.company_phone}')
    if company.company_address:
        addr = company.company_address.replace('\n', '  ').strip()
        contact_parts.append(f'📍 {addr}')
    ws['A2'] = '    '.join(contact_parts) if contact_parts else ''
    ws['A2'].font = Font(name='Calibri', size=10, color='CBD5E1')
    ws['A2'].fill = PatternFill('solid', fgColor='1E3A5F')
    ws['A2'].alignment = Alignment(horizontal='left', vertical='center', indent=2)
    ws.row_dimensions[2].height = 22

    # --- Row 3: Template label ---
    ws.merge_cells(f'A3:{last_col}3')
    ws['A3'] = 'PRODUCT BULK UPLOAD TEMPLATE'
    ws['A3'].font = Font(name='Calibri', size=9, bold=True, color=ORANGE)
    ws['A3'].fill = PatternFill('solid', fgColor=DARK_BG)
    ws['A3'].alignment = Alignment(horizontal='left', vertical='center', indent=2)
    ws.row_dimensions[3].height = 18

    # --- Row 4: Spacer ---
    for c in range(1, NUM_COLS + 1):
        ws.cell(row=4, column=c).fill = PatternFill('solid', fgColor=DARK_BG)
    ws.row_dimensions[4].height = 6

    # --- Row 5: Instruction banner ---
    ws.merge_cells(f'A5:{last_col}5')
    ws['A5'] = 'Fill in product data below (* = required). For the Image column: click the cell, then use Insert > Picture (Excel) or Insert > Image (Sheets) to embed a photo.'
    ws['A5'].font = Font(name='Calibri', size=10, italic=True, color='9CA3AF')
    ws['A5'].fill = PatternFill('solid', fgColor=MID_BG)
    ws['A5'].alignment = Alignment(horizontal='left', vertical='center', indent=2)
    ws.row_dimensions[5].height = 22

    # --- Row 6: REQUIRED / optional labels ---
    for col_idx, (name, width, required, *_) in enumerate(columns, start=1):
        cell = ws.cell(row=6, column=col_idx)
        cell.value = 'REQUIRED' if required else 'optional'
        cell.font = Font(name='Calibri', size=9, bold=True, color=ORANGE if required else '6B7280')
        cell.fill = PatternFill('solid', fgColor=MID_BG)
        cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[6].height = 18

    # --- Row 7: Column headers ---
    header_fill   = PatternFill('solid', fgColor=BLUE)
    header_border = Border(bottom=Side(style='medium', color='3B82F6'))
    for col_idx, (name, width, required, *_) in enumerate(columns, start=1):
        cell = ws.cell(row=7, column=col_idx)
        cell.value = name + (' *' if required else '')
        cell.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        cell.fill = header_fill
        cell.border = header_border
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[7].height = 26

    # --- Rows 8-9: Example data rows ---
    IMG_FILL  = PatternFill('solid', fgColor='1A1040')
    IMG_BORDER = Border(
        top=Side(style='dashed', color='7C3AED'),
        bottom=Side(style='dashed', color='7C3AED'),
        left=Side(style='dashed', color='7C3AED'),
        right=Side(style='dashed', color='7C3AED'),
    )
    fill_odd  = PatternFill('solid', fgColor=MID_BG)
    fill_even = PatternFill('solid', fgColor=ACCENT_BG)
    ex_font   = Font(name='Calibri', size=11, color='D1D5DB')
    ex_border = Border(bottom=Side(style='thin', color='1F2937'))
    for row_offset, ex_idx in enumerate([0, 1], start=8):
        for col_idx, (name, width, required, ex1, ex2) in enumerate(columns, start=1):
            cell = ws.cell(row=row_offset, column=col_idx)
            if col_idx == IMAGE_COL:
                # Special styling for the image column (shows a camera icon hint)
                cell.value = '📷 insert image'
                cell.font = Font(name='Calibri', size=10, italic=True, color='A78BFA')
                cell.fill = IMG_FILL
                cell.border = IMG_BORDER
                cell.alignment = Alignment(horizontal='center', vertical='center')
            else:
                cell.value = ex1 if ex_idx == 0 else ex2
                cell.font = ex_font
                cell.fill = fill_odd if ex_idx == 0 else fill_even
                cell.border = ex_border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=False)
        ws.row_dimensions[row_offset].height = 40  # Taller rows to show embedded images

    # Freeze panes so the header row stays visible when scrolling
    ws.freeze_panes = 'A8'

    # --- Output as downloadable file ---
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="products_template.xlsx"'
    return response


def _normalize_name(s):
    """
    Normalize a string for matching purposes (lowercase, alphanumeric only).

    Args:
        s (str): The string to normalize (e.g., a product name or filename).

    Returns:
        str: The normalized string (lowercase, with only a-z and 0-9 characters).

    Business Logic:
        When matching uploaded images to products by filename, we need to ignore
        case differences, spaces, and special characters. This function converts
        "Red Widget Pro!" to "redwidgetpro" for reliable matching.
    """
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _parse_upload_rows(upload_file):
    """
    Parse uploaded CSV or XLSX files into a list of dictionaries.

    Args:
        upload_file (InMemoryUploadedFile): The uploaded file from the request.

    Returns:
        list[dict]: Each dict contains keys like 'name', 'price', 'moq', etc.

    Business Logic:
        The admin uploads a bulk product file (CSV or XLSX). This function normalizes
        the column headers and returns a list of row dictionaries so the view can
        create products one by one. It supports both Excel and CSV formats.
    """
    FIELDS = ['name', 'image', 'price', 'moq', 'weight', 'carton_length', 'carton_width', 'carton_height', 'carton_qty']
    filename = upload_file.name.lower()

    if filename.endswith('.xlsx'):
        from openpyxl import load_workbook
        wb = load_workbook(filename=io.BytesIO(upload_file.read()), data_only=True)
        ws = wb.active
        # Find the header row (the row with 'name' in column A), search first 10 rows
        header_row = None
        for r in range(1, min(11, ws.max_row + 1)):
            val = str(ws.cell(row=r, column=1).value or '').strip().lower().replace(' *', '')
            if val == 'name':
                header_row = r
                break
        if header_row is None:
            raise ValueError('Could not find a header row with "name" in column A')
        # Read the header names from the found row
        headers = [
            str(ws.cell(row=header_row, column=c).value or '').strip().lower().replace(' *', '')
            for c in range(1, len(FIELDS) + 1)
        ]
        rows = []
        # Read each data row and create a dictionary mapping header -> value
        for r in range(header_row + 1, ws.max_row + 1):
            vals = [str(ws.cell(row=r, column=c).value or '').strip() for c in range(1, len(FIELDS) + 1)]
            if any(vals):  # Skip completely empty rows
                rows.append(dict(zip(headers, vals)))
        return rows
    else:
        # CSV parsing: read as UTF-8 with BOM handling, use DictReader for header-based mapping
        decoded = upload_file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(decoded))
        # Normalize header names and strip whitespace from values
        return [
            {k.strip().lower().replace(' *', ''): (v or '').strip() for k, v in row.items()}
            for row in reader
        ]


def _extract_xlsx_images(file_bytes):
    """
    Extract embedded images from an XLSX file and map them to data row indices.

    Args:
        file_bytes (bytes): The raw bytes of the XLSX file.

    Returns:
        dict: {data_row_idx (0-based): (image_bytes, file_extension)}

    Business Logic:
        When the admin uploads an XLSX with images embedded in cells, we need to
        extract those images and match them to the correct product rows. This function
        parses the XLSX's internal image structure and returns a mapping.
    """
    result = {}
    try:
        from openpyxl import load_workbook
        wb = load_workbook(filename=io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
        # Find the header row (same logic as _parse_upload_rows)
        header_row_1 = None
        for r in range(1, min(11, ws.max_row + 1)):
            val = str(ws.cell(row=r, column=1).value or '').strip().lower().replace(' *', '')
            if val == 'name':
                header_row_1 = r
                break
        if header_row_1 is None:
            return {}
        # Iterate over all embedded images in the worksheet
        for img in getattr(ws, '_images', []):
            try:
                anchor = img.anchor
                # Different openpyxl versions store anchor differently; handle both
                if hasattr(anchor, '_from'):
                    img_row_0 = anchor._from.row   # 0-indexed row
                elif hasattr(anchor, 'row'):
                    img_row_0 = anchor.row
                else:
                    continue
                # Calculate which data row this image belongs to (0-based from first data row)
                data_row_idx = img_row_0 - header_row_1
                if data_row_idx < 0:
                    continue
                # Extract the raw image bytes
                if hasattr(img, '_data') and callable(img._data):
                    data = img._data()
                else:
                    continue
                if not data:
                    continue
                # Determine the file extension from the image format
                fmt = (getattr(img, 'format', None) or 'png').lower().replace('jpeg', 'jpg')
                result[data_row_idx] = (data, fmt)
            except Exception:
                continue
    except Exception:
        pass
    return result


@module_required('products')
@csrf_exempt
def bulk_upload_from_images(request):
    """
    AJAX endpoint: Create products directly from uploaded photos — no spreadsheet needed.

    Args:
        request (HttpRequest): The incoming POST request with images and product data arrays.

    Returns:
        JsonResponse: {'success': True/False, 'created': N, 'errors': [...], 'message': '...'}

    Business Logic:
        The admin can take photos of products and upload them directly. Each photo is paired
        with name, price, and MOQ (sent as parallel arrays). This is the fastest way to add
        a few products quickly without preparing a spreadsheet.

    Django Concepts:
        - request.FILES.getlist('images[]'): Gets multiple image files from the form.
        - request.POST.getlist('names[]'): Gets parallel arrays of form data.
        - Decimal(raw): Converts string values to precise Decimal for price.
        - Product.objects.filter(name__iexact=name).exists(): Checks for duplicate product names (case-insensitive).
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})

    # Get parallel arrays of form data (one entry per product)
    images         = request.FILES.getlist('images[]')
    names          = request.POST.getlist('names[]')
    prices         = request.POST.getlist('prices[]')
    moqs           = request.POST.getlist('moqs[]')
    weights        = request.POST.getlist('weights[]')
    carton_lengths = request.POST.getlist('carton_lengths[]')
    carton_widths  = request.POST.getlist('carton_widths[]')
    carton_heights = request.POST.getlist('carton_heights[]')
    carton_qtys    = request.POST.getlist('carton_qtys[]')
    sources        = request.POST.getlist('sources[]')

    if not images:
        return JsonResponse({'success': False, 'message': 'No images uploaded'})

    def _dec(lst, i):
        """Return Decimal or None for an optional numeric field at index i."""
        raw = (lst[i] if i < len(lst) else '').strip()
        if not raw:
            return None
        try:
            return Decimal(raw)
        except InvalidOperation:
            return None

    def _int(lst, i):
        """Return int or None for an optional integer field at index i."""
        raw = (lst[i] if i < len(lst) else '').strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    created    = 0
    duplicates = 0
    errors     = []

    for i, img in enumerate(images):
        name      = (names[i]  if i < len(names)  else '').strip()
        price_raw = (prices[i] if i < len(prices) else '').strip()
        moq_raw   = (moqs[i]   if i < len(moqs)   else '').strip()

        # Name, price, and MOQ are required fields
        if not name or not price_raw or not moq_raw:
            errors.append(f'Row {i + 1}: missing required fields \u2014 skipped')
            continue

        # Check for duplicate product names (case-insensitive exact match)
        if Product.objects.filter(name__iexact=name).exists():
            duplicates += 1
            errors.append(f'Row {i + 1}: \u201c{name}\u201d already exists \u2014 skipped')
            continue

        try:
            price_val = Decimal(price_raw)
            moq_val   = int(moq_raw)
        except (ValueError, InvalidOperation):
            errors.append(f'Row {i + 1}: invalid price or MOQ \u2014 skipped')
            continue

        # Create the product with the provided data
        source = (sources[i] if i < len(sources) else 'general').strip().lower()
        if source not in {'general', 'amazon', 'noon'}:
            source = 'general'
        product = Product.objects.create(
            name=name, price=price_val, moq=moq_val,
            weight=_dec(weights, i),
            carton_length=_dec(carton_lengths, i),
            carton_width=_dec(carton_widths, i),
            carton_height=_dec(carton_heights, i),
            carton_qty=_int(carton_qtys, i),
            source=source,
        )
        # Create the ProductImage linking the uploaded photo to this product
        ProductImage.objects.create(product=product, image=img)
        created += 1

    # Build a summary message for the admin
    msg = f'{created} product(s) created with images.'
    if duplicates:
        msg += f' {duplicates} duplicate(s) skipped.'
    if len(errors) - duplicates > 0:
        msg += f' {len(errors) - duplicates} row(s) had errors.'
    return JsonResponse({'success': True, 'created': created, 'errors': errors, 'message': msg})


@module_required('products')
@csrf_exempt
def bulk_upload_1688(request):
    r"""
    AJAX endpoint: Import products from a 1688.com / aiprice CSV export.

    Args:
        request (HttpRequest): The incoming POST request with a CSV file.

    Returns:
        JsonResponse: {'success': True/False, 'created': N, 'errors': [...], 'message': '...'}

    Business Logic:
        1688.com is the largest Chinese wholesale platform (like Alibaba but domestic).
        The admin can export a CSV from 1688 and upload it here. The system extracts:
        - Product name, Price (in RMB with ¥ symbol), Quantity (MOQ), and Image URL
        - It then downloads the product image from the CDN and creates the product.
        This automates the tedious process of manually copying product data from 1688.

    Django Concepts:
        - csv.DictReader: Reads CSV with headers and returns dictionaries per row.
        - urllib.request: Downloads product images from external URLs.
        - ContentFile: Wraps raw bytes into a Django file object for saving to MEDIA_ROOT.
        - re.search(r'¥([\d.]+)', price_raw): Extracts the RMB price using regex.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})

    csv_file = request.FILES.get('csv_file')
    if not csv_file:
        return JsonResponse({'success': False, 'message': 'No file uploaded'})

    import urllib.request as _urlreq
    from django.core.files.base import ContentFile

    try:
        # Decode with utf-8-sig to handle BOM (Byte Order Mark) at the start of the file
        content = csv_file.read().decode('utf-8-sig')
        reader  = csv.DictReader(io.StringIO(content))
    except Exception as exc:
        return JsonResponse({'success': False, 'message': f'Failed to read CSV: {exc}'})

    created    = 0
    duplicates = 0
    errors     = []

    for i, row in enumerate(reader, start=1):
        name      = (row.get('Product name') or '').strip()
        price_raw = (row.get('Price')        or '').strip()
        moq_raw   = (row.get('Quantity')     or '').strip()
        image_url = (row.get('Image link')   or '').strip()

        if not name:
            errors.append(f'Row {i}: missing product name — skipped')
            continue

        # Extract RMB price from strings like "¥51.00 ($7.43)" using regex
        price_match = re.search(r'¥([\d.]+)', price_raw)
        if not price_match:
            errors.append(f'Row {i}: \u201c{name}\u201d \u2014 cannot parse price \u201c{price_raw}\u201d \u2014 skipped')
            continue

        try:
            price_val = Decimal(price_match.group(1))
        except InvalidOperation:
            errors.append(f'Row {i}: \u201c{name}\u201d \u2014 invalid price value \u2014 skipped')
            continue

        try:
            moq_val = max(1, int(moq_raw))
        except (ValueError, TypeError):
            moq_val = 1  # Default to 1 if MOQ is invalid

        if Product.objects.filter(name__iexact=name).exists():
            duplicates += 1
            errors.append(f'Row {i}: \u201c{name}\u201d already exists \u2014 skipped')
            continue

        # Create the product with extracted data
        product = Product.objects.create(name=name, price=price_val, moq=moq_val)

        # Download the product image from the CDN URL and save it
        if image_url:
            try:
                req = _urlreq.Request(
                    image_url,
                    headers={'User-Agent': 'Mozilla/5.0 (compatible; logistic-manager/1.0)'},
                )
                with _urlreq.urlopen(req, timeout=10) as resp:
                    img_data = resp.read()
                # Determine file extension from the URL (ignore query parameters)
                url_path = image_url.split('?')[0]
                ext = url_path.rsplit('.', 1)[-1].lower()
                if ext not in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
                    ext = 'jpg'  # Default to jpg if extension is unknown
                safe_name = re.sub(r'[^\w\-]', '_', name)[:50]
                ProductImage.objects.create(
                    product=product,
                    image=ContentFile(img_data, name=f'{safe_name}.{ext}'),
                )
            except Exception:
                pass  # If image download fails, the product is still created successfully

        created += 1

    # Build the summary response message
    msg = f'{created} product(s) imported from 1688.'
    if duplicates:
        msg += f' {duplicates} duplicate(s) skipped.'
    err_count = len(errors) - duplicates
    if err_count > 0:
        msg += f' {err_count} row(s) had errors.'
    return JsonResponse({'success': True, 'created': created, 'errors': errors, 'message': msg})


@module_required('products')
@csrf_exempt
def bulk_upload(request):
    """
    AJAX endpoint: Bulk import products from a CSV or XLSX file.

    Args:
        request (HttpRequest): The incoming POST request with a file upload.

    Returns:
        JsonResponse: {'success': True/False, 'created': N, 'errors': [...], 'message': '...'}

    Business Logic:
        The admin uploads a filled-in bulk upload template (or any compatible CSV/XLSX).
        The system parses the file, validates each row, creates new products, and matches
        images either embedded in the XLSX or uploaded as separate files. Selected rows
        can be imported (the frontend sends which rows the user selected).

    Django Concepts:
        - request.FILES.get('csv_file'): Gets the uploaded file.
        - _parse_upload_rows(): Helper that handles both CSV and XLSX parsing.
        - _extract_xlsx_images(): Extracts images from the XLSX for matching.
        - request.POST.get('selected_rows'): Optional JSON array of row indices to import.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})

    upload_file = request.FILES.get('csv_file')
    if not upload_file:
        return JsonResponse({'success': False, 'message': 'No file uploaded'})

    ext = upload_file.name.lower()
    if not (ext.endswith('.csv') or ext.endswith('.xlsx')):
        return JsonResponse({'success': False, 'message': 'File must be .csv or .xlsx'})

    try:
        file_bytes = upload_file.read()
        upload_file.seek(0)
        row_dicts = _parse_upload_rows(upload_file)
        # Optional: the frontend may send a subset of row indices to import
        selected_rows_raw = request.POST.get('selected_rows', '')
        selected_rows = None
        if selected_rows_raw:
            try:
                selected_rows = set(int(v) for v in __import__('json').loads(selected_rows_raw))
            except Exception:
                selected_rows = None
            
        created_products = []
        errors = []

        for i, row in enumerate(row_dicts, start=2):
            data_idx = i - 2  # 0-based index from the first data row
            if selected_rows is not None and data_idx not in selected_rows:
                continue  # Skip rows not selected by the user
            name = (row.get('name') or '').strip()
            price_raw = (row.get('price') or '').strip()
            moq_raw = (row.get('moq') or '').strip()

            # Name, price, and MOQ are required for every product
            if not name or not price_raw or not moq_raw:
                errors.append(f'Row {i}: name, price, and moq are required — skipped')
                continue

            # Skip if a product with the same name already exists (case-insensitive)
            if Product.objects.filter(name__iexact=name).exists():
                errors.append(f'Row {i}: "{name}" already exists — skipped')
                continue

            try:
                price_val = Decimal(price_raw)
                moq_val = int(moq_raw)
            except (ValueError, InvalidOperation):
                errors.append(f'Row {i}: invalid price or moq value — skipped')
                continue

            # Extract optional fields from the row (default to None if empty)
            weight = (row.get('weight') or '').strip() or None
            carton_length = (row.get('carton_length') or '').strip() or None
            carton_width = (row.get('carton_width') or '').strip() or None
            carton_height = (row.get('carton_height') or '').strip() or None
            carton_qty = (row.get('carton_qty') or '').strip() or None
            image_filename = (row.get('image_filename') or '').strip()
            source = (row.get('source') or 'general').strip().lower()
            if source not in {'general', 'amazon', 'noon'}:
                source = 'general'
            ready_to_ship = str(row.get('ready_to_ship', '')).strip().lower() in {'1', 'yes', 'true'}

            # Create the product in the database
            product = Product.objects.create(
                name=name,
                price=price_val,
                moq=moq_val,
                weight=weight,
                carton_length=carton_length,
                carton_width=carton_width,
                carton_height=carton_height,
                carton_qty=carton_qty,
                source=source,
                ready_to_ship=ready_to_ship,
            )
            created_products.append((product, image_filename))

        # --- Match images to the created products ---
        # 1) Extract images embedded in the XLSX (matched by row position)
        embedded_images = {}
        if upload_file.name.lower().endswith('.xlsx'):
            embedded_images = _extract_xlsx_images(file_bytes)

        # Build a mapping from normalized names to product objects for filename matching
        product_map = {}
        for product, image_filename in created_products:
            product_map[_normalize_name(product.name)] = product
            if image_filename:
                stem = os.path.splitext(image_filename)[0]
                product_map[_normalize_name(stem)] = product

        images_matched = 0
        # Match embedded images by row index (most reliable for XLSX uploads)
        for row_idx, (img_bytes, ext) in embedded_images.items():
            if row_idx < len(created_products):
                product = created_products[row_idx][0]
                from django.core.files.base import ContentFile
                ProductImage.objects.create(
                    product=product,
                    image=ContentFile(img_bytes, name=f'{_normalize_name(product.name)}.{ext}'),
                )
                images_matched += 1
                product_map.pop(_normalize_name(product.name), None)  # Don't match by name for this product

        # Match separate uploaded image files by normalized filename
        for img_file in request.FILES.getlist('images[]'):
            base = os.path.splitext(img_file.name)[0]
            key = _normalize_name(base)
            if key in product_map:
                ProductImage.objects.create(product=product_map[key], image=img_file)
                images_matched += 1

        # Build the summary response
        created = len(created_products)
        duplicates = sum(1 for e in errors if 'already exists' in e)
        msg = f'{created} product(s) uploaded successfully.'
        if images_matched:
            msg += f' {images_matched} image(s) matched.'
        if duplicates:
            msg += f' {duplicates} duplicate(s) skipped.'
        other_errors = len(errors) - duplicates
        if other_errors:
            msg += f' {other_errors} row(s) had errors.'
        return JsonResponse({'success': True, 'created': created, 'errors': errors, 'message': msg})

    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error processing file: {str(e)}'})


@module_required('products')
@csrf_exempt
def toggle_private(request, product_id):
    """
    AJAX endpoint: Toggle a product's private/public visibility status.

    Args:
        request (HttpRequest): The incoming POST request.
        product_id (int): The primary key of the product to toggle.

    Returns:
        JsonResponse: {'success': True, 'is_private': bool, 'name': '...'}

    Business Logic:
        Private products are hidden from the general catalogue. This is useful for
        exclusive products or products that should only be shown to specific customers.
        Toggling makes it easy to show/hide products without deleting them.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=400)
    product = get_object_or_404(Product, id=product_id)
    product.is_private = not product.is_private  # Flip the boolean flag
    product.save(update_fields=['is_private'])    # Only update the changed field (efficient)
    return JsonResponse({'success': True, 'is_private': product.is_private, 'name': product.name})


@module_required('products')
@csrf_exempt
def bulk_action(request):
    """
    AJAX endpoint: Perform bulk actions on multiple selected products.

    Args:
        request (HttpRequest): The incoming POST request with a JSON body containing IDs and action.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        The admin can select multiple products and perform actions on all of them at once:
        - delete: Remove all selected products
        - private: Hide from public catalogue
        - public: Make visible in public catalogue
        - draft: Mark as draft (not yet ready for customers)
        - publish: Mark as published (visible to customers)
        - save_prices: Auto-calculate air and sea shipping-inclusive prices based on global rates

    Django Concepts:
        - json.loads(request.body): Parses the JSON request body.
        - Product.objects.filter(id__in=ids): Fetches all selected products in one query.
        - products.update(is_private=True): Bulk update (one SQL UPDATE for all selected products).
        - products.delete(): Bulk delete (one SQL DELETE for all selected products).
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})

    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid request data'})

    ids = data.get('ids', [])
    action = data.get('action', '')

    if not ids:
        return JsonResponse({'success': False, 'message': 'No products selected'})

    products = Product.objects.filter(id__in=ids)
    count = products.count()
    if count == 0:
        return JsonResponse({'success': False, 'message': 'No matching products found'})

    # --- Delete selected products ---
    if action == 'delete':
        products.delete()
        return JsonResponse({'success': True, 'message': f'{count} product(s) deleted'})

    # --- Move to private (hide from public catalogue) ---
    if action == 'private':
        updated = products.update(is_private=True)
        return JsonResponse({'success': True, 'message': f'{updated} product(s) moved to private'})

    # --- Make public (show in public catalogue) ---
    if action == 'public':
        updated = products.update(is_private=False)
        return JsonResponse({'success': True, 'message': f'{updated} product(s) restored to public'})

    # --- Mark as draft (not ready for customers) ---
    if action == 'draft':
        updated = products.update(is_draft=True)
        return JsonResponse({'success': True, 'message': f'{updated} product(s) marked as draft'})

    # --- Publish (make available to customers) ---
    if action == 'publish':
        updated = products.update(is_draft=False)
        return JsonResponse({'success': True, 'message': f'{updated} product(s) published'})

    # --- Auto-calculate and save shipping-inclusive prices ---
    if action == 'save_prices':
        settings = CompanySettings.get_settings()
        air_rate = Decimal(str(settings.air_shipping_rate or 0))
        sea_rate = Decimal(str(settings.sea_shipping_rate or 0))
        saved = 0
        skipped = 0
        for product in products:
            air_val = None
            sea_val = None
            # Calculate air shipping price: (weight * air_rate) / carton_qty + base price
            if product.weight and product.carton_qty and air_rate > 0:
                air_ship = (Decimal(str(product.weight)) * air_rate) / Decimal(str(product.carton_qty))
                air_val = (Decimal(str(product.price)) + air_ship).quantize(Decimal('0.01'))
            # Calculate sea shipping price: (CBM * sea_rate) / carton_qty + base price
            if product.carton_length and product.carton_width and product.carton_height and product.carton_qty and sea_rate > 0:
                cbm = (
                    Decimal(str(product.carton_length))
                    * Decimal(str(product.carton_width))
                    * Decimal(str(product.carton_height))
                    / Decimal('1000000')
                )
                sea_ship = (cbm / Decimal(str(product.carton_qty))) * sea_rate
                sea_val = (Decimal(str(product.price)) + sea_ship).quantize(Decimal('0.01'))
            # Save the calculated prices if at least one was computed
            if air_val is not None or sea_val is not None:
                product.price_air = air_val
                product.price_sea = sea_val
                product.save(update_fields=['price_air', 'price_sea'])
                saved += 1
            else:
                skipped += 1
        msg = f'Prices saved for {saved} product(s)'
        if skipped:
            msg += f' ({skipped} skipped — missing weight/carton data or rates)'
        return JsonResponse({'success': True, 'message': msg})

    return JsonResponse({'success': False, 'message': 'Unknown action'})
