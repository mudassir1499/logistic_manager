"""
Noon Label Generator Views — Shipping Label PDF Generator for Noon.com Sellers

Business Context:
Noon is a major Middle Eastern e-commerce marketplace (like Amazon for the UAE/Saudi).
Sellers on Noon must attach specific product and carton labels to every shipment.
This module generates printable PDF labels that comply with Noon's format requirements:
- Product labels: stuck on individual products (item-level tracking)
- Carton labels: stuck on shipping boxes/cartons (box-level tracking)

The labels include barcodes (Code 128), product quantities, carton marks, and ASN numbers
so Noon warehouses can scan and receive inventory efficiently.

Django Concepts Used:
- @login_required: Only logged-in admins can generate labels (security).
- HttpResponse with PDF content_type: Returns a downloadable PDF directly to the browser.
- reportlab: A Python library for generating PDFs programmatically — used instead of
  templates because labels require precise positioning, barcodes, and exact measurements.
- LabelBatch: A model that stores the history of generated labels for reference.
- canvas (reportlab.pdfgen.canvas): The low-level PDF drawing API that gives pixel-perfect control.
"""

import io
from django.contrib.auth.decorators import login_required
# Role-aware access guard: only users whose profile grants the 'noon_labels' module
# (admins always, or staff with perm_noon_labels) may reach these views.
from accounts.decorators import module_required
from django.shortcuts import render
from django.http import HttpResponse
from .models import LabelBatch

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.graphics.barcode import code128


# Label size: 100mm x 150mm (standard shipping label dimensions used by Noon)
LABEL_WIDTH = 100 * mm
LABEL_HEIGHT = 150 * mm


@module_required('noon_labels')
def label_form(request):
    """
    Render the label generator form page with batch history.

    Args:
        request (HttpRequest): The incoming HTTP request from the browser.

    Returns:
        HttpResponse: A rendered HTML page with a form to generate labels and
                      a list of recently generated label batches.

    Business Logic:
        The admin uses this page to enter label parameters (quantity, carton count,
        label marks, carton marks, ASN). The page also shows the last 20 generated
        batches so the admin can re-reference previous labels if needed.
    """
    # Fetch the most recent 20 label batches to show in the history sidebar
    batches = LabelBatch.objects.all()[:20]
    return render(request, 'noon_labels/label_form.html', {'batches': batches})


from reportlab.lib.pagesizes import A4

@module_required('noon_labels')
def generate_labels_pdf(request):
    """
    Generate a PDF of PRODUCT labels (one label per product item).

    Args:
        request (HttpRequest): The incoming POST request with label parameters.

    Returns:
        HttpResponse: A PDF file with product labels, served inline in the browser.

    Business Logic:
        When a seller ships 100 units of a product to Noon's warehouse, each unit needs
        a product label. This view generates a PDF with one page per label (thermal mode)
        or multiple labels per page (A4 mode) for efficient printing. The label includes:
        - Noon logo bar
        - Label mark (seller's SKU identifier)
        - Product quantity (how many units per carton or total)
        - Barcode (encoded label mark for warehouse scanning)
    """
    # Only accept POST requests; GET would have no data to generate labels from
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)

    # Extract form data from the POST request
    quantity = int(request.POST.get('quantity', 1))          # How many product labels to generate
    carton_quantity = int(request.POST.get('carton_quantity', 1))  # How many cartons (for reference)
    label_mark = request.POST.get('label_mark', 'N/A')          # Seller's SKU / product identifier
    label_mark_2 = request.POST.get('label_mark_2', '')         # Extra line 1 (e.g., model variant)
    label_mark_3 = request.POST.get('label_mark_3', '')         # Extra line 2 (e.g., color, size)
    carton_mark = request.POST.get('carton_mark', 'N/A')        # Carton-level identifier (not used on product labels but saved)
    carton_asn = request.POST.get('carton_asn', '')             # Advanced Shipment Notice number
    paper_format = request.POST.get('paper_format', 'a4')       # 'a4' or 'thermal' printing mode

    # Save this generation to the database for history/audit purposes
    LabelBatch.objects.create(
        label_mark=label_mark,
        label_mark_2=label_mark_2,
        label_mark_3=label_mark_3,
        carton_mark=carton_mark,
        carton_asn=carton_asn,
        quantity=quantity,
        carton_quantity=carton_quantity,
    )

    # Create an in-memory buffer for the PDF (no temp files needed)
    buffer = io.BytesIO()
    
    if paper_format != 'thermal':
        # --- A4 Mode: Fit multiple labels on a standard A4 page ---
        # A4 is 210mm x 297mm. We fit 4 columns x 5 rows = 20 labels per page.
        c = canvas.Canvas(buffer, pagesize=A4)
        c.setTitle(f'Product Labels - {label_mark}')
        cols, rows = 4, 5
        scale_f = 0.38  # Scale down the 100x150mm label to fit on A4
        bw, bh = LABEL_WIDTH * scale_f, LABEL_HEIGHT * scale_f  # Scaled label dimensions
        # Calculate margins to center the label grid on the page
        x_margin = (A4[0] - (cols * bw)) / 2
        y_margin = (A4[1] - (rows * bh)) / 2
        
        idx = 0
        for i in range(quantity):
            # Start a new page if we've filled the current one (every 20 labels)
            if idx > 0 and idx % (cols * rows) == 0:
                c.showPage()
            
            # Calculate grid position (0 = top-left, reading left-to-right, top-to-bottom)
            grid_idx = idx % (cols * rows)
            col = grid_idx % cols
            row = grid_idx // cols  # 0 is the top row
            
            # Calculate x,y coordinates for this label on the A4 page
            x = x_margin + col * bw
            y = A4[1] - y_margin - (row + 1) * bh
            
            # Save the current canvas state so we can translate/scale for this label only
            c.saveState()
            c.translate(x, y)       # Move the origin to this label's position
            c.scale(scale_f, scale_f)  # Scale down so the label fits in the cell
            # Draw the product label content at the scaled origin
            _draw_product_label(c, label_mark, quantity, i + 1, label_mark_2, label_mark_3)
            c.restoreState()      # Restore the original canvas state for the next label
            idx += 1
            
        # If at least one label was drawn, we need a final showPage to render the last page
        if idx > 0:
            c.showPage()
    else:
        # --- Thermal Mode: One label per page, exact 100x150mm size ---
        # This is for dedicated thermal label printers (e.g., Zebra, Dymo)
        c = canvas.Canvas(buffer, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))
        c.setTitle(f'Product Labels - {label_mark}')
        for i in range(quantity):
            _draw_product_label(c, label_mark, quantity, i + 1, label_mark_2, label_mark_3)
            c.showPage()  # Each label gets its own page

    c.save()  # Finalize the PDF
    buffer.seek(0)  # Rewind the buffer to the beginning for reading
    # Return the PDF as an HTTP response with the correct content type
    response = HttpResponse(buffer, content_type='application/pdf')
    # 'inline' means the browser will open it in a viewer; 'attachment' would force download
    response['Content-Disposition'] = f'inline; filename="noon_label_{label_mark}.pdf"'
    return response


@module_required('noon_labels')
def generate_carton_pdf(request):
    """
    Generate a PDF of CARTON labels (one label per shipping box/carton).

    Args:
        request (HttpRequest): The incoming POST request with label parameters.

    Returns:
        HttpResponse: A PDF file with carton labels, served inline in the browser.

    Business Logic:
        When shipping to Noon, each physical box needs a carton label. The carton label
        has a thicker border and a "CARTON LABEL" subtitle to distinguish it from
        product labels. It includes the carton mark (the box identifier), ASN number,
        product quantity, and a barcode. Carton labels are generated per carton, not per
        product, so if you have 10 cartons, you get 10 labels.
    """
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)

    quantity = int(request.POST.get('quantity', 1))          # Total product quantity across all cartons
    carton_quantity = int(request.POST.get('carton_quantity', 1))  # Number of cartons (labels to generate)
    label_mark = request.POST.get('label_mark', 'N/A')          # Product identifier (shown on carton for reference)
    label_mark_2 = request.POST.get('label_mark_2', '')
    label_mark_3 = request.POST.get('label_mark_3', '')
    carton_mark = request.POST.get('carton_mark', 'N/A')        # Carton-specific identifier (barcode value)
    carton_asn = request.POST.get('carton_asn', '')             # ASN for this carton
    paper_format = request.POST.get('paper_format', 'a4')
    
    buffer = io.BytesIO()
    
    if paper_format != 'thermal':
        # A4 mode: multiple carton labels per page (4x5 grid)
        c = canvas.Canvas(buffer, pagesize=A4)
        c.setTitle(f'Carton Labels - {carton_mark}')
        cols, rows = 4, 5
        scale_f = 0.38
        bw, bh = LABEL_WIDTH * scale_f, LABEL_HEIGHT * scale_f
        x_margin = (A4[0] - (cols * bw)) / 2
        y_margin = (A4[1] - (rows * bh)) / 2
        
        idx = 0
        for i in range(carton_quantity):
            if idx > 0 and idx % (cols * rows) == 0:
                c.showPage()
            
            grid_idx = idx % (cols * rows)
            col = grid_idx % cols
            row = grid_idx // cols
            
            x = x_margin + col * bw
            y = A4[1] - y_margin - (row + 1) * bh
            
            c.saveState()
            c.translate(x, y)
            c.scale(scale_f, scale_f)
            _draw_carton_label(c, carton_mark, label_mark, quantity, i + 1, label_mark_2, label_mark_3, carton_quantity, carton_asn)
            c.restoreState()
            idx += 1
            
        if idx > 0:
            c.showPage()
    else:
        # Thermal mode: one label per page, exact 100x150mm
        c = canvas.Canvas(buffer, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))
        c.setTitle(f'Carton Labels - {carton_mark}')
        for i in range(carton_quantity):
            _draw_carton_label(c, carton_mark, label_mark, quantity, i + 1, label_mark_2, label_mark_3, carton_quantity, carton_asn)
            c.showPage()

    c.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="noon_carton_{carton_mark}.pdf"'
    return response


# =========================================================================
#  Product Label Drawing
# =========================================================================

def _draw_product_label(c, label_mark, total_qty, current_num, label_mark_2=None, label_mark_3=None):
    """
    Draw a single PRODUCT label on the ReportLab canvas.

    Args:
        c (canvas.Canvas): The ReportLab canvas to draw on.
        label_mark (str): The primary SKU/identifier printed in large text.
        total_qty (int): The total product quantity (e.g., items per carton).
        current_num (int): Which label this is (e.g., "Label 5 of 100").
        label_mark_2 (str, optional): Extra line 1 (e.g., variant info).
        label_mark_3 (str, optional): Extra line 2 (e.g., more variant info).

    Business Logic:
        This function draws the exact layout of a Noon product label:
        - Yellow Noon logo bar at the top
        - "PRODUCT LABEL" subtitle
        - Large label mark (the SKU) for human readability
        - Optional secondary marks for variants
        - Product quantity (how many units)
        - Label counter (e.g., "Label 3 of 50") for tracking
        - Code 128 barcode for warehouse scanning
    """
    w = LABEL_WIDTH
    h = LABEL_HEIGHT

    # White background fill for the entire label area
    c.setFillColor(HexColor('#FFFFFF'))
    c.rect(0, 0, w, h, fill=1, stroke=0)

    # Border around the label (1.5pt line, dark gray)
    c.setStrokeColor(HexColor('#333333'))
    c.setLineWidth(1.5)
    c.rect(3 * mm, 3 * mm, w - 6 * mm, h - 6 * mm, fill=0, stroke=1)

    # ===== Noon Logo Bar (yellow background) =====
    logo_y = h - 28 * mm
    c.setFillColor(HexColor('#FEEE00'))  # Noon's signature yellow
    c.rect(3 * mm, logo_y, w - 6 * mm, 22 * mm, fill=1, stroke=0)

    # "noon" text in bold dark gray on the yellow bar
    c.setFillColor(HexColor('#2D2D2D'))
    c.setFont('Helvetica-Bold', 28)
    c.drawCentredString(w / 2, logo_y + 6 * mm, 'noon')

    # "PRODUCT LABEL" subtitle below the logo bar
    y = logo_y - 4 * mm
    c.setFillColor(HexColor('#FEEE00'))
    c.setFont('Helvetica-Bold', 9)
    c.drawCentredString(w / 2, logo_y - 1 * mm, '')  # Spacer line
    c.setFillColor(HexColor('#333333'))
    c.setFont('Helvetica-Bold', 10)
    c.drawCentredString(w / 2, y, 'PRODUCT LABEL')

    # Divider line between header and content
    y -= 6 * mm
    c.setStrokeColor(HexColor('#CCCCCC'))
    c.setLineWidth(0.5)
    c.line(8 * mm, y, w - 8 * mm, y)

    # ===== Label Mark (large, prominent SKU) =====
    y -= 10 * mm
    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 8)
    c.drawString(8 * mm, y + 3 * mm, 'LABEL MARK')
    c.setFillColor(HexColor('#000000'))
    c.setFont('Helvetica-Bold', 20)
    c.drawString(8 * mm, y - 8 * mm, label_mark)
    
    # Optional secondary marks (e.g., for product variants)
    offset = 0
    if label_mark_2:
        c.setFont('Helvetica', 12)
        c.setFillColor(HexColor('#555555'))
        c.drawString(8 * mm, y - 15 * mm, label_mark_2)
        offset += 6 * mm
    if label_mark_3:
        c.setFont('Helvetica', 12)
        c.setFillColor(HexColor('#555555'))
        c.drawString(8 * mm, y - 15 * mm - offset, label_mark_3)
        offset += 6 * mm

    # ===== Product Quantity =====
    y -= (22 * mm + offset)
    # Dashed separator line above the quantity
    c.setStrokeColor(HexColor('#EEEEEE'))
    c.setDash(3, 2)
    c.line(8 * mm, y + 4 * mm, w - 8 * mm, y + 4 * mm)
    c.setDash()  # Reset dash to solid line

    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 8)
    c.drawString(8 * mm, y, 'PRODUCT QUANTITY')
    c.setFillColor(HexColor('#000000'))
    c.setFont('Helvetica-Bold', 26)
    c.drawString(8 * mm, y - 12 * mm, str(total_qty))

    # Label counter (e.g., "Label 5 of 100") — right-aligned
    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 9)
    c.drawRightString(w - 8 * mm, y - 8 * mm, f'Label {current_num} of {total_qty}')

    # ===== Barcode =====
    y -= 28 * mm
    c.setStrokeColor(HexColor('#EEEEEE'))
    c.setLineWidth(0.5)
    c.line(8 * mm, y + 2 * mm, w - 8 * mm, y + 2 * mm)

    # Encode the label mark as a Code 128 barcode (spaces replaced with underscores for compatibility)
    barcode_value = label_mark.replace(' ', '_')
    try:
        # barWidth=0.6mm, barHeight=15mm are standard sizes for warehouse scanning
        barcode = code128.Code128(barcode_value, barWidth=0.6 * mm, barHeight=15 * mm)
        barcode_width = barcode.width
        # Center the barcode horizontally on the label
        x_pos = (w - barcode_width) / 2
        barcode.drawOn(c, x_pos, y - 18 * mm)
    except Exception:
        # Fallback: if barcode generation fails, just print the text in monospace
        c.setFont('Courier', 10)
        c.drawCentredString(w / 2, y - 10 * mm, barcode_value)

    # Barcode text printed below the barcode for human verification
    c.setFillColor(HexColor('#666666'))
    c.setFont('Courier', 8)
    c.drawCentredString(w / 2, y - 22 * mm, barcode_value)

    # Footer with label dimensions
    c.setFillColor(HexColor('#AAAAAA'))
    c.setFont('Helvetica', 6)
    c.drawCentredString(w / 2, 6 * mm, 'noon Seller Product Label \u2014 100mm x 150mm')


# =========================================================================
#  Carton Label Drawing
# =========================================================================

def _draw_carton_label(c, carton_mark, label_mark, total_qty, current_num, label_mark_2=None, label_mark_3=None, total_cartons=1, carton_asn=None):
    """
    Draw a single CARTON label on the ReportLab canvas.

    Args:
        c (canvas.Canvas): The ReportLab canvas to draw on.
        carton_mark (str): The carton identifier (barcode value, primary identifier).
        label_mark (str): The product identifier (shown for reference).
        total_qty (int): Total product quantity inside this carton.
        current_num (int): Which carton this is (e.g., "Carton 2 of 10").
        label_mark_2 (str, optional): Extra product info line 1.
        label_mark_3 (str, optional): Extra product info line 2.
        total_cartons (int): Total number of cartons in this shipment.
        carton_asn (str, optional): Advanced Shipment Notice number for this carton.

    Business Logic:
        Carton labels are different from product labels:
        - They have a THICKER border (2.5pt vs 1.5pt) to distinguish them at a glance.
        - The "noon" logo bar has a DARK background (vs yellow on product labels).
        - The primary identifier is the CARTON MARK (not the label mark).
        - They include an ASN number (Advanced Shipment Notice) for inbound tracking.
        - The barcode encodes the carton mark (for box-level scanning at the warehouse).
    """
    w = LABEL_WIDTH
    h = LABEL_HEIGHT

    # White background
    c.setFillColor(HexColor('#FFFFFF'))
    c.rect(0, 0, w, h, fill=1, stroke=0)

    # Thick border for carton labels (2.5pt, dark gray)
    c.setStrokeColor(HexColor('#2D2D2D'))
    c.setLineWidth(2.5)
    c.rect(3 * mm, 3 * mm, w - 6 * mm, h - 6 * mm, fill=0, stroke=1)

    # ===== Noon Logo Bar (dark background for carton) =====
    logo_y = h - 28 * mm
    c.setFillColor(HexColor('#2D2D2D'))  # Dark gray instead of yellow
    c.rect(3 * mm, logo_y, w - 6 * mm, 22 * mm, fill=1, stroke=0)

    # "noon" text in yellow on the dark bar (inverted colors from product label)
    c.setFillColor(HexColor('#FEEE00'))
    c.setFont('Helvetica-Bold', 28)
    c.drawCentredString(w / 2, logo_y + 6 * mm, 'noon')

    # "CARTON LABEL" subtitle
    y = logo_y - 4 * mm
    c.setFillColor(HexColor('#333333'))
    c.setFont('Helvetica-Bold', 10)
    c.drawCentredString(w / 2, y, 'CARTON LABEL')

    # Divider line
    y -= 6 * mm
    c.setStrokeColor(HexColor('#CCCCCC'))
    c.setLineWidth(0.5)
    c.line(8 * mm, y, w - 8 * mm, y)

    # ===== Carton Mark (large, prominent — this is the box identifier) =====
    y -= 10 * mm
    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 8)
    c.drawString(8 * mm, y + 3 * mm, 'CARTON MARK')
    c.setFillColor(HexColor('#000000'))
    c.setFont('Helvetica-Bold', 22)
    c.drawString(8 * mm, y - 9 * mm, carton_mark)

    # ===== ASN (Advanced Shipment Notice) — optional but important for warehouse receiving =====
    if carton_asn:
        y -= 17 * mm
        c.setFillColor(HexColor('#888888'))
        c.setFont('Helvetica', 8)
        c.drawString(8 * mm, y + 3 * mm, 'CARTON ASN')
        c.setFillColor(HexColor('#333333'))
        c.setFont('Helvetica-Bold', 18)
        c.drawString(8 * mm, y - 8 * mm, carton_asn)
        y -= 7 * mm  # Adjust vertical position for the next section
    else:
        y -= 14 * mm  # No ASN, so less space is used

    # ===== Product Quantity (how many units are inside this carton) =====
    c.setStrokeColor(HexColor('#EEEEEE'))
    c.setDash(3, 2)
    c.line(8 * mm, y + 4 * mm, w - 8 * mm, y + 4 * mm)
    c.setDash()

    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 8)
    c.drawString(8 * mm, y, 'PRODUCT QUANTITY')
    c.setFillColor(HexColor('#000000'))
    c.setFont('Helvetica-Bold', 22)
    c.drawString(8 * mm, y - 10 * mm, str(total_qty))

    # Carton counter (e.g., "Carton 3 of 10") — right-aligned
    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 9)
    c.drawRightString(w - 8 * mm, y - 6 * mm, f'Carton {current_num} of {total_cartons}')

    # ===== Barcode (encodes the carton mark for box-level scanning) =====
    y -= 24 * mm
    c.setStrokeColor(HexColor('#EEEEEE'))
    c.setLineWidth(0.5)
    c.line(8 * mm, y + 2 * mm, w - 8 * mm, y + 2 * mm)

    barcode_value = carton_mark.replace(' ', '_')
    try:
        barcode = code128.Code128(barcode_value, barWidth=0.6 * mm, barHeight=15 * mm)
        barcode_width = barcode.width
        x_pos = (w - barcode_width) / 2
        barcode.drawOn(c, x_pos, y - 18 * mm)
    except Exception:
        c.setFont('Courier', 10)
        c.drawCentredString(w / 2, y - 10 * mm, barcode_value)

    # Barcode text below for human verification
    c.setFillColor(HexColor('#666666'))
    c.setFont('Courier', 8)
    c.drawCentredString(w / 2, y - 22 * mm, barcode_value)

    # Footer
    c.setFillColor(HexColor('#AAAAAA'))
    c.setFont('Helvetica', 6)
    c.drawCentredString(w / 2, 6 * mm, 'noon Seller Carton Label \u2014 100mm x 150mm')
