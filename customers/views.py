"""
Customers Views — Customer Management & Product Assignment for Logistics Business

Business Context:
This module manages the customer database and assigns products to customers for quotations.
In this logistics business, customers are typically B2B buyers (wholesalers, retailers) who
place bulk orders. The admin needs to:
1. View all customers in a list
2. Add, edit, and delete customer records (name, phone, address)
3. Assign products to customers (each customer sees only their assigned products in quotations)
4. Generate professional Excel quotations for customers with their assigned products

Django Concepts Used:
- @login_required: Protects admin-only views; redirects to login if user is not authenticated.
- @csrf_exempt: Allows AJAX requests from the frontend without a CSRF token (internal tool).
- Customer.objects.all(): Django QuerySet to fetch all customer records from the database.
- get_object_or_404: Safely fetches a customer by ID; returns HTTP 404 if not found.
- select_related('product'): SQL JOIN to fetch related Product data in one query (performance optimization).
- prefetch_related('product__images'): Fetches related images in a separate query to avoid N+1 problem.
- JsonResponse: Returns JSON data for AJAX endpoints (success/error messages).
- openpyxl: Python library for generating Excel files (quotations).
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from .models import Customer, CustomerProduct

from django.core.paginator import Paginator

from products.models import Product
from settings_manager.models import CompanySettings
import io
import os
import re
import datetime


@login_required
def customer_list(request):
    """
    Display the customer list page for the admin dashboard.

    Args:
        request (HttpRequest): The incoming HTTP request from the browser.

    Returns:
        HttpResponse: A rendered HTML page showing all customers sorted by newest first.

    Business Logic:
        The admin needs to see all customers in one place to manage relationships,
        contact details, and product assignments. The list is ordered by ID descending
        so the most recently added customers appear at the top.

    Django Concepts:
        - Customer.objects.all() returns a QuerySet of ALL customer records.
        - .order_by('-id') sorts in descending order (newest customers first).
        - render() combines the template with the data and returns an HttpResponse.
        - @login_required ensures only logged-in users can see customer data (privacy).
    """
    # Fetch all customers from the database, ordered by newest first (highest ID first)
    customers = Customer.objects.all().order_by('-id')

    # --- Search ---
    # Filtering happens in the database, not in the browser. Client-side filtering
    # would only ever search the 25 rows on the current page.
    query = request.GET.get('q', '').strip()
    if query:
        customers = customers.filter(
            Q(name__icontains=query)
            | Q(phone__icontains=query)
            | Q(email__icontains=query)
            | Q(address__icontains=query)
        )

    # --- Pagination ---
    # The page number comes from the URL query string: ?page=N
    page_number = request.GET.get('page', 1)
    paginator = Paginator(customers, 25)
    page_obj = paginator.get_page(page_number)

    return render(request, 'customers/customer_list.html', {
        'page_obj': page_obj,
        'query': query,
        'total_count': paginator.count,
    })


@login_required
@csrf_exempt
def add_customer(request):
    """
    AJAX endpoint: Add a new customer to the database.

    Args:
        request (HttpRequest): The incoming AJAX POST request with customer data.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        When a new buyer contacts the business, the admin adds their details (name, phone,
        address) so they can be selected later when creating orders or quotations.

    Django Concepts:
        - request.POST.get('name') extracts form data from the POST request.
        - Customer.objects.create() creates and saves a new database row in one call.
        - JsonResponse serializes the Python dict to JSON for the frontend AJAX handler.
    """
    if request.method == 'POST':
        # Extract the form fields from the POST request body
        name = request.POST.get('name')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        # Create a new Customer record in the database with the provided details
        Customer.objects.create(name=name, phone=phone, address=address)
        return JsonResponse({'success': True, 'message': 'Customer added successfully!'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
@csrf_exempt
def edit_customer(request):
    """
    AJAX endpoint: Edit an existing customer's details.

    Args:
        request (HttpRequest): The incoming AJAX POST request with updated customer data.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        If a customer changes their phone number or address, the admin updates their record
        so invoices and quotations always show correct contact info.

    Django Concepts:
        - Customer.objects.get(id=customer_id) fetches the specific customer by primary key.
        - request.POST.get('name', customer.name) uses the existing value as a fallback
          if the field is not provided in the POST data.
        - customer.save() persists the updated fields to the database.
    """
    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        try:
            # Fetch the customer by ID; if not found, catch the exception below
            customer = Customer.objects.get(id=customer_id)
            # Update fields: use the POST value if provided, otherwise keep the existing value
            customer.name = request.POST.get('name', customer.name)
            customer.phone = request.POST.get('phone', customer.phone)
            customer.address = request.POST.get('address', customer.address)
            customer.save()  # Save the changes to the database
            return JsonResponse({'success': True, 'message': 'Customer updated successfully!'})
        except Customer.DoesNotExist:
            # This exception is raised if no customer with the given ID exists in the database
            return JsonResponse({'success': False, 'message': 'Customer not found'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
@csrf_exempt
def delete_customer(request, customer_id):
    """
    AJAX endpoint: Delete a customer from the database.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        customer_id (int): The primary key of the Customer to delete.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        If a customer is no longer active or was added by mistake, the admin removes them.
        Note: This may fail if the customer has related orders (foreign key constraints).

    Django Concepts:
        - customer.delete() removes the row from the database. This can cascade to related
          objects if the foreign key has on_delete=CASCADE set in the model.
    """
    if request.method == 'POST':
        try:
            customer = Customer.objects.get(id=customer_id)
            customer.delete()
            return JsonResponse({'success': True, 'message': 'Customer deleted!'})
        except Customer.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Customer not found'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def customer_products(request, customer_id):
    """
    Display the product assignment page for a specific customer.

    Args:
        request (HttpRequest): The incoming HTTP request from the browser.
        customer_id (int): The primary key of the customer whose products we are managing.

    Returns:
        HttpResponse: A rendered HTML page showing:
            - Assigned products (products already linked to this customer)
            - Available products (products not yet linked to this customer)

    Business Logic:
        Different customers buy different products. The admin "assigns" products to a customer
        so that when generating a quotation, only relevant products appear. This keeps
        quotations focused and prevents confusion.

    Django Concepts:
        - get_object_or_404: Returns a 404 page if the customer doesn't exist (user-friendly error).
        - CustomerProduct.objects.filter(customer=customer): Gets the join table rows linking this customer to products.
        - values_list('product_id', flat=True): Returns a flat list of just the product IDs (efficient).
        - set(): Converts the list to a Python set for fast O(1) lookup when excluding products.
        - Product.objects.exclude(id__in=assigned_ids): QuerySet excluding already-assigned products.
        - prefetch_related('images'): Fetches product images in a separate query to avoid N+1 queries.
    """
    # Safely fetch the customer or return a 404 error page
    customer = get_object_or_404(Customer, id=customer_id)
    # Get the IDs of all products already assigned to this customer (using a flat list for efficiency)
    assigned_ids = set(CustomerProduct.objects.filter(customer=customer).values_list('product_id', flat=True))
    # Fetch the assigned products with related product data and images (performance optimization)
    assigned = CustomerProduct.objects.filter(customer=customer).select_related('product').prefetch_related('product__images')
    # Fetch all products NOT assigned to this customer, with images, ordered alphabetically by name
    available = Product.objects.exclude(id__in=assigned_ids).prefetch_related('images').order_by('name')
    # Render the template with three context variables for the frontend to display
    return render(request, 'customers/customer_products.html', {
        'customer': customer,
        'assigned': assigned,
        'available': available,
    })


@login_required
@csrf_exempt
def assign_product(request, customer_id):
    """
    AJAX endpoint: Assign a product to a customer.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        customer_id (int): The primary key of the customer to assign the product to.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        When a customer expresses interest in a product, the admin "assigns" it to them.
        This links the product to the customer so it appears in their quotations.
        A note can be added (e.g., "Customer wants in red color").

    Django Concepts:
        - get_object_or_404: Safely fetches both the customer and the product.
        - CustomerProduct.objects.get_or_create(): Tries to get an existing link; if none exists,
          it creates one. Returns (object, created_boolean).
        - If not created, the product was already assigned — return a helpful error message.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})
    # Fetch the customer and product; return 404 if either doesn't exist
    customer = get_object_or_404(Customer, id=customer_id)
    product_id = request.POST.get('product_id')
    note = request.POST.get('note', '').strip()  # Optional note about this assignment
    product = get_object_or_404(Product, id=product_id)
    # get_or_create tries to find an existing CustomerProduct row; if not found, creates one
    _, created = CustomerProduct.objects.get_or_create(customer=customer, product=product, defaults={'note': note})
    if not created:
        # The assignment already existed — inform the admin so they don't duplicate it
        return JsonResponse({'success': False, 'message': f'"{product.name}" is already assigned to this customer.'})
    return JsonResponse({'success': True, 'message': f'"{product.name}" assigned successfully.'})


@login_required
@csrf_exempt
def remove_product(request, customer_id, product_id):
    """
    AJAX endpoint: Remove a product assignment from a customer.

    Args:
        request (HttpRequest): The incoming AJAX POST request.
        customer_id (int): The primary key of the customer.
        product_id (int): The primary key of the product to remove.

    Returns:
        JsonResponse: {'success': True/False, 'message': '...'}

    Business Logic:
        If a customer is no longer interested in a product, or it was assigned by mistake,
        the admin removes the link. This does NOT delete the product — only the assignment.

    Django Concepts:
        - CustomerProduct.objects.filter(...).delete(): Deletes the join table rows.
          Returns (count_deleted, count_per_model_dict).
        - We check if count_deleted > 0 to determine if the assignment actually existed.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})
    # Delete the CustomerProduct join row that matches both customer_id and product_id
    deleted, _ = CustomerProduct.objects.filter(customer_id=customer_id, product_id=product_id).delete()
    if deleted:
        return JsonResponse({'success': True, 'message': 'Product removed.'})
    return JsonResponse({'success': False, 'message': 'Assignment not found.'})


@login_required
def customer_quotation(request, customer_id):
    """
    Generate a professional customer quotation as a styled Excel (.xlsx) file.

    Args:
        request (HttpRequest): The incoming HTTP request.
        customer_id (int): The primary key of the customer to generate the quotation for.

    Returns:
        HttpResponse: An Excel file download with the customer's assigned products,
                      including unit prices, MOQ, order quantity columns, and totals.

    Business Logic:
        This is the core sales tool of the business. The admin selects a customer and
        generates a quotation Excel that the customer can fill in with desired quantities.
        The Excel includes:
        - Company branding (name, phone, address)
        - Today's date and customer info
        - Product list with photos, prices, MOQ
        - Empty "Order Qty" column for the customer to fill in
        - Auto-calculated totals in both base currency and converted currency
        - Grand total row at the bottom

    Django Concepts:
        - get_object_or_404: Safely fetches the customer.
        - CompanySettings.get_settings(): Singleton pattern to get the single settings row.
        - select_related('product') and prefetch_related('product__images'): Optimize queries.
        - HttpResponse with content_type and Content-Disposition: Forces the browser to download the file.
    """
    # Import openpyxl components for Excel generation (done inside the function to avoid startup overhead)
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.drawing.image import Image as XLImage
    from django.conf import settings as django_settings

    # Fetch the customer and company settings for the quotation header
    customer = get_object_or_404(Customer, id=customer_id)
    company = CompanySettings.get_settings()
    # Fetch all products assigned to this customer, with related product data and images
    assigned = list(
        CustomerProduct.objects
        .filter(customer=customer)
        .select_related('product')
        .prefetch_related('product__images')
    )

    # If the customer has no assigned products, return an error message
    if not assigned:
        return HttpResponse('No products assigned to this customer.', status=400)

    # --- Exchange rate configuration ---
    # Check if currency conversion is enabled and the exchange rate is valid (> 0)
    fx_enabled = bool(
        company.exchange_rate_enabled
        and company.exchange_rate
        and float(company.exchange_rate) > 0
    )
    # If enabled, convert to float; otherwise None
    fx_rate = float(company.exchange_rate) if fx_enabled else None
    # Labels for the two currencies (e.g., 'RMB' and 'AED')
    base_lbl = company.currency or 'RMB'
    aed_lbl = (company.exchange_rate_from or 'AED') if fx_enabled else 'AED'

    # --- Color palette (hex strings for Excel styling) ---
    # These are dark-theme colors for a professional, modern-looking quotation
    BG_DARK   = '0F1117'   # Very dark background
    NAVY      = '1E3A5F'   # Navy blue for header rows
    TEAL      = '0F4C75'   # Teal for contact strip
    HDR_BG    = '1A2744'   # Header background for column titles
    ROW_A     = '141924'   # Alternating row color A
    ROW_B     = '0D1520'   # Alternating row color B
    QTY_BG    = '0A2535'   # Background for the editable quantity column
    TOTAL_BG  = '0D1F0D'   # Background for total columns
    GRAND_BG  = '14532D'   # Dark green for the grand total row
    ORANGE    = 'FF8C00'   # Orange for emphasis
    GREEN     = '4ADE80'   # Light green for totals
    TEAL_C    = '38BDF8'   # Cyan for quantity column header
    PURPLE    = 'A78BFA'   # Purple accent
    BORDER_C  = '1F2937'   # Border color
    WHITE     = 'FFFFFF'   # White text
    GREY      = '94A3B8'   # Gray text for secondary info
    LIGHT     = 'E2E8F0'   # Light text color

    # --- Column layout definition ---
    # C1:No  C2:Photo  C3:Name  C4:UnitRMB  C5:UnitAED  C6:MOQ  C7:OrderQty  C8:TotalRMB  C9:TotalAED
    IMG_COL   = 2    # Column B is the image column
    IMG_PX    = 60   # Target image size in pixels
    ROW_H_IMG = 50   # Row height when an image is present
    ROW_H_STD = 20   # Standard row height when no image

    # Dictionary mapping column index -> column width
    col_widths = {1:5, 2:10, 3:34, 4:15, 5:15, 6:8, 7:13, 8:16, 9:16}
    # Dictionary mapping column index -> header text (with newlines for multi-line headers)
    col_hdrs = {
        1:  'No.',
        2:  '',
        3:  'Product Name',
        4:  f'Unit Price\n({base_lbl})',
        5:  f'Unit Price\n({aed_lbl})',
        6:  'MOQ',
        7:  'Order Qty\n(fill in)',
        8:  f'Total\n({base_lbl})',
        9:  f'Total\n({aed_lbl})',
    }
    LAST_COL = max(col_widths.keys())  # The rightmost column number (9)
    last_col_letter = get_column_letter(LAST_COL)  # 'I' for column 9

    # Create a new Excel workbook and get the active worksheet
    wb = Workbook()
    ws = wb.active
    ws.title = 'Quotation'

    # Set the column widths for each column
    for c, w in col_widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w

    # --- Helper function: apply a border to a cell ---
    def _border(cell, color=BORDER_C, style='thin'):
        s = Side(style=style, color=color)
        cell.border = Border(bottom=s, right=s, top=s, left=s)

    # --- Helper function: create a styled merged cell ---
    def _mcell(row, col, value, fg, font_color=WHITE, size=10, bold=False, align='center', wrap=False, indent=0):
        cell = ws.cell(row=row, column=col, value=value)
        cell.font      = Font(name='Calibri', size=size, bold=bold, color=font_color)
        cell.fill      = PatternFill('solid', fgColor=fg)
        cell.alignment = Alignment(horizontal=align, vertical='center', wrap_text=wrap, indent=indent)
        _border(cell)
        return cell

    # --- Row 1: Company name header (merged across all columns) ---
    ws.merge_cells(f'A1:{last_col_letter}1')
    c = ws['A1']
    c.value     = company.company_name or 'Quotation'
    c.font      = Font(name='Calibri', size=16, bold=True, color=WHITE)
    c.fill      = PatternFill('solid', fgColor=NAVY)
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[1].height = 36

    # --- Row 2: Contact info (phone and address) ---
    ws.merge_cells(f'A2:{last_col_letter}2')
    c = ws['A2']
    parts = []
    if company.company_phone:   parts.append(f'\U0001f4de {company.company_phone}')
    if company.company_address: parts.append(f'\U0001f4cd {company.company_address.replace(chr(10),"  ").strip()}')
    c.value     = '    '.join(parts)
    c.font      = Font(name='Calibri', size=9, color='CBD5E1')
    c.fill      = PatternFill('solid', fgColor=TEAL)
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[2].height = 18

    # --- Row 3: Document title and today's date ---
    ws.merge_cells(f'A3:{last_col_letter}3')
    c = ws['A3']
    c.value     = f'CUSTOMER QUOTATION  \u00b7  {datetime.date.today().strftime("%d %B %Y")}'
    c.font      = Font(name='Calibri', size=9, bold=True, color=ORANGE)
    c.fill      = PatternFill('solid', fgColor=BG_DARK)
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[3].height = 16

    # --- Row 4: Customer info (prepared for whom) ---
    ws.merge_cells(f'A4:{last_col_letter}4')
    c = ws['A4']
    cust_line = f'Prepared for:  {customer.name}'
    if customer.phone:   cust_line += f'    \U0001f4de {customer.phone}'
    if customer.address: cust_line += f'    \U0001f4cd {customer.address.replace(chr(10),"  ").strip()}'
    c.value     = cust_line
    c.font      = Font(name='Calibri', size=10, bold=True, color='93C5FD')
    c.fill      = PatternFill('solid', fgColor='0A1628')
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[4].height = 22

    # --- Row 5: Instruction banner telling the customer what to do ---
    ws.merge_cells(f'A5:{last_col_letter}5')
    c = ws['A5']
    c.value     = (
        '\u270d  Fill in column G (Order Qty) for each product you wish to order.  '
        f'Totals in {base_lbl} and {aed_lbl} will be calculated automatically.'
    )
    c.font      = Font(name='Calibri', size=9, italic=True, bold=True, color='FEF9C3')
    c.fill      = PatternFill('solid', fgColor='1C1A0F')
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[5].height = 18

    # --- Row 6: Spacer row (small visual gap) ---
    for col in range(1, LAST_COL + 1):
        ws.cell(row=6, column=col).fill = PatternFill('solid', fgColor=BG_DARK)
    ws.row_dimensions[6].height = 5

    # --- Row 7: Column headers ---
    HDR_ROW = 7
    for col, lbl in col_hdrs.items():
        cell            = ws.cell(row=HDR_ROW, column=col, value=lbl)
        cell.font       = Font(name='Calibri', size=9, bold=True, color=WHITE)
        cell.fill       = PatternFill('solid', fgColor=HDR_BG)
        cell.alignment  = Alignment(horizontal='center', vertical='center', wrap_text=True)
        _border(cell, '2C3E6B')
        # Extra visual highlight for the quantity and total columns
        if col == 7:
            cell.fill = PatternFill('solid', fgColor='0F3460')
            cell.font = Font(name='Calibri', size=9, bold=True, color=TEAL_C)
        elif col in (8, 9):
            cell.fill = PatternFill('solid', fgColor='0D2B0D')
            cell.font = Font(name='Calibri', size=9, bold=True, color=GREEN)
    ws.row_dimensions[HDR_ROW].height = 30

    # --- Product data rows (starting from row 8) ---
    FIRST_DATA = 8
    for i, cp in enumerate(assigned):
        r    = FIRST_DATA + i  # Current row number
        prod = cp.product        # The actual Product object
        bg   = ROW_A if i % 2 == 0 else ROW_B  # Alternating row colors for readability

        # Calculate the AED price from the base price using the exchange rate
        price_val = float(prod.price)
        aed_val   = round(price_val / fx_rate, 2) if fx_rate else None
        QC        = get_column_letter(7)   # Get the letter 'G' for the Order Qty column

        # Helper function for creating styled data cells in this row
        def _c(col, value, bold=False, fc=LIGHT, bg_=bg, nf=None):
            cell            = ws.cell(row=r, column=col, value=value)
            cell.font       = Font(name='Calibri', size=10, bold=bold, color=fc)
            cell.fill       = PatternFill('solid', fgColor=bg_)
            cell.alignment  = Alignment(horizontal='center', vertical='center')
            _border(cell)
            if nf: cell.number_format = nf
            return cell

        # Column 1: Row number
        _c(1, i + 1, fc=GREY)
        # Column 2: Empty placeholder for the image
        _c(2, '')
        # Column 3: Product name (left-aligned for readability)
        nc = ws.cell(row=r, column=3, value=prod.name)
        nc.font      = Font(name='Calibri', size=10, bold=True, color=WHITE)
        nc.fill      = PatternFill('solid', fgColor=bg)
        nc.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        _border(nc)

        # Column 4: Unit price in base currency (e.g., RMB)
        _c(4, price_val, bold=True, fc=ORANGE, nf=f'#,##0.00 "{base_lbl}"')
        # Column 5: Unit price in converted currency (e.g., AED), or '—' if conversion disabled
        if aed_val is not None:
            _c(5, aed_val, bold=True, fc=TEAL_C, nf=f'#,##0.00 "{aed_lbl}"')
        else:
            _c(5, '—', fc=GREY)
        # Column 6: MOQ (Minimum Order Quantity)
        _c(6, prod.moq, fc=LIGHT)

        # Column 7: ORDER QTY — left blank for the customer to fill in, with a highlighted border
        oq = ws.cell(row=r, column=7, value=None)
        oq.fill       = PatternFill('solid', fgColor=QTY_BG)
        oq.font       = Font(name='Calibri', size=11, bold=True, color=TEAL_C)
        oq.alignment  = Alignment(horizontal='center', vertical='center')
        oq.border     = Border(
            top=Side(style='medium',    color=TEAL_C),
            bottom=Side(style='medium', color=TEAL_C),
            left=Side(style='medium',   color=TEAL_C),
            right=Side(style='medium',  color=TEAL_C),
        )
        oq.number_format = '#,##0'

        # Column 8: Total in base currency = Order Qty × Unit Price (Excel formula)
        tc_rmb = ws.cell(row=r, column=8,
            value=f'=IF({QC}{r}="","",{QC}{r}*{price_val})')
        tc_rmb.font       = Font(name='Calibri', size=10, bold=True, color=GREEN)
        tc_rmb.fill       = PatternFill('solid', fgColor=TOTAL_BG)
        tc_rmb.alignment  = Alignment(horizontal='center', vertical='center')
        tc_rmb.number_format = f'#,##0.00 "{base_lbl}"'
        _border(tc_rmb, '166534')

        # Column 9: Total in converted currency = Order Qty × AED Price (Excel formula)
        if aed_val is not None:
            tc_aed = ws.cell(row=r, column=9,
                value=f'=IF({QC}{r}="","",{QC}{r}*{aed_val})')
            tc_aed.font       = Font(name='Calibri', size=10, bold=True, color=GREEN)
            tc_aed.fill       = PatternFill('solid', fgColor=TOTAL_BG)
            tc_aed.alignment  = Alignment(horizontal='center', vertical='center')
            tc_aed.number_format = f'#,##0.00 "{aed_lbl}"'
            _border(tc_aed, '166534')
        else:
            _c(9, '—', fc=GREY, bg_=TOTAL_BG)

        # Embed the first product image in column 2 (if available)
        has_image = False
        first_img = prod.images.first()
        if first_img:
            # Construct the full filesystem path to the image
            img_path = os.path.join(django_settings.MEDIA_ROOT, str(first_img.image))
            if os.path.exists(img_path):
                try:
                    xl_img        = XLImage(img_path)
                    orig_w        = xl_img.width  or IMG_PX
                    orig_h        = xl_img.height or IMG_PX
                    # Scale the image to fit within IMG_PX while maintaining aspect ratio
                    scale         = min(IMG_PX / orig_w, IMG_PX / orig_h)
                    xl_img.width  = int(orig_w * scale)
                    xl_img.height = int(orig_h * scale)
                    xl_img.anchor = f'{get_column_letter(IMG_COL)}{r}'
                    ws.add_image(xl_img)
                    has_image = True
                except Exception:
                    # If image loading fails (corrupt file, etc.), skip it gracefully
                    pass
        # Set row height based on whether an image was embedded
        ws.row_dimensions[r].height = ROW_H_IMG if has_image else ROW_H_STD

    # --- Totals row (below all product rows) ---
    n       = len(assigned)
    tot_r   = FIRST_DATA + n          # Row number for the totals row
    last_dr = FIRST_DATA + n - 1     # Row number of the last data row

    # Label span: merge columns A-F and write "TOTALS"
    ws.merge_cells(f'A{tot_r}:F{tot_r}')
    lc = ws['A' + str(tot_r)]
    lc.value     = 'TOTALS'
    lc.font      = Font(name='Calibri', size=11, bold=True, color=GREEN)
    lc.fill      = PatternFill('solid', fgColor=GRAND_BG)
    lc.alignment = Alignment(horizontal='right', vertical='center', indent=1)
    _border(lc, '166534', 'medium')

    # Column 7: Total quantity (SUM of all order quantities entered by the customer)
    tot_qty = ws.cell(row=tot_r, column=7,
        value=f'=SUM(G{FIRST_DATA}:G{last_dr})')
    tot_qty.font         = Font(name='Calibri', size=11, bold=True, color=TEAL_C)
    tot_qty.fill         = PatternFill('solid', fgColor=GRAND_BG)
    tot_qty.alignment    = Alignment(horizontal='center', vertical='center')
    tot_qty.number_format = '#,##0'
    _border(tot_qty, '166534', 'medium')

    # Column 8: Grand total in base currency (SUM of all line totals where qty is not empty)
    tot_rmb = ws.cell(row=tot_r, column=8,
        value=f'=SUMIF(G{FIRST_DATA}:G{last_dr},"<>",H{FIRST_DATA}:H{last_dr})')
    tot_rmb.font         = Font(name='Calibri', size=11, bold=True, color=GREEN)
    tot_rmb.fill         = PatternFill('solid', fgColor=GRAND_BG)
    tot_rmb.alignment    = Alignment(horizontal='center', vertical='center')
    tot_rmb.number_format = f'#,##0.00 "{base_lbl}"'
    _border(tot_rmb, '166534', 'medium')

    # Column 9: Grand total in converted currency (SUM of all converted line totals)
    tot_aed = ws.cell(row=tot_r, column=9,
        value=f'=SUMIF(G{FIRST_DATA}:G{last_dr},"<>",I{FIRST_DATA}:I{last_dr})')
    tot_aed.font         = Font(name='Calibri', size=11, bold=True, color=GREEN)
    tot_aed.fill         = PatternFill('solid', fgColor=GRAND_BG)
    tot_aed.alignment    = Alignment(horizontal='center', vertical='center')
    tot_aed.number_format = f'#,##0.00 "{aed_lbl}"'
    _border(tot_aed, '166534', 'medium')

    ws.row_dimensions[tot_r].height = 26

    # --- Footer row ---
    foot_r = tot_r + 1
    ws.merge_cells(f'A{foot_r}:{last_col_letter}{foot_r}')
    c = ws[f'A{foot_r}']
    c.value     = (
        f'{company.company_name or ""}  \u00b7  '
        f'Prices valid as of {datetime.date.today().strftime("%d %b %Y")}  \u00b7  Confidential'
    )
    c.font      = Font(name='Calibri', size=8, italic=True, color='4B5563')
    c.fill      = PatternFill('solid', fgColor=BG_DARK)
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[foot_r].height = 16

    # --- Output the Excel file as an HTTP response ---
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    # Create a safe filename by removing special characters and replacing spaces with underscores
    safe_cust = re.sub(r'[^\w\s-]', '', customer.name).strip().replace(' ', '_')
    filename  = f'{safe_cust}_quotation_{datetime.date.today().strftime("%Y%m%d")}.xlsx'
    response  = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    # Content-Disposition: 'attachment' forces the browser to download the file
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
