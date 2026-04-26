import io
from django.shortcuts import render
from django.http import HttpResponse
from .models import LabelBatch

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.graphics.barcode import code128


# Label size: 100mm x 150mm (standard shipping label)
LABEL_WIDTH = 100 * mm
LABEL_HEIGHT = 150 * mm


def label_form(request):
    """Render the label generator form with batch history."""
    batches = LabelBatch.objects.all()[:20]
    return render(request, 'noon_labels/label_form.html', {'batches': batches})


from reportlab.lib.pagesizes import A4

def generate_labels_pdf(request):
    """Generate Product Label PDF (label mark focused)."""
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)

    quantity = int(request.POST.get('quantity', 1))
    carton_quantity = int(request.POST.get('carton_quantity', 1))
    label_mark = request.POST.get('label_mark', 'N/A')
    label_mark_2 = request.POST.get('label_mark_2', '')
    label_mark_3 = request.POST.get('label_mark_3', '')
    carton_mark = request.POST.get('carton_mark', 'N/A')
    carton_asn = request.POST.get('carton_asn', '')
    paper_format = request.POST.get('paper_format', 'a4')

    # Save to history
    LabelBatch.objects.create(
        label_mark=label_mark,
        label_mark_2=label_mark_2,
        label_mark_3=label_mark_3,
        carton_mark=carton_mark,
        carton_asn=carton_asn,
        quantity=quantity,
        carton_quantity=carton_quantity,
    )

    buffer = io.BytesIO()
    
    if paper_format != 'thermal':
        c = canvas.Canvas(buffer, pagesize=A4)
        c.setTitle(f'Product Labels - {label_mark}')
        # 4 cols, 5 rows = 20 labels per page
        cols, rows = 4, 5
        scale_f = 0.38
        bw, bh = LABEL_WIDTH * scale_f, LABEL_HEIGHT * scale_f
        x_margin = (A4[0] - (cols * bw)) / 2
        y_margin = (A4[1] - (rows * bh)) / 2
        
        idx = 0
        for i in range(quantity):
            if idx > 0 and idx % (cols * rows) == 0:
                c.showPage()
            
            grid_idx = idx % (cols * rows)
            col = grid_idx % cols
            row = grid_idx // cols  # 0 is top
            
            x = x_margin + col * bw
            y = A4[1] - y_margin - (row + 1) * bh
            
            c.saveState()
            c.translate(x, y)
            c.scale(scale_f, scale_f)
            _draw_product_label(c, label_mark, quantity, i + 1, label_mark_2, label_mark_3)
            c.restoreState()
            idx += 1
            
        if idx > 0:
            c.showPage()
    else:
        # Thermal
        c = canvas.Canvas(buffer, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))
        c.setTitle(f'Product Labels - {label_mark}')
        for i in range(quantity):
            _draw_product_label(c, label_mark, quantity, i + 1, label_mark_2, label_mark_3)
            c.showPage()

    c.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="noon_label_{label_mark}.pdf"'
    return response


def generate_carton_pdf(request):
    """Generate Carton Label PDF (carton mark focused) — separate file."""
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)

    quantity = int(request.POST.get('quantity', 1))
    carton_quantity = int(request.POST.get('carton_quantity', 1))
    label_mark = request.POST.get('label_mark', 'N/A')
    label_mark_2 = request.POST.get('label_mark_2', '')
    label_mark_3 = request.POST.get('label_mark_3', '')
    carton_mark = request.POST.get('carton_mark', 'N/A')
    carton_asn = request.POST.get('carton_asn', '')
    paper_format = request.POST.get('paper_format', 'a4')
    
    buffer = io.BytesIO()
    
    if paper_format != 'thermal':
        c = canvas.Canvas(buffer, pagesize=A4)
        c.setTitle(f'Carton Labels - {carton_mark}')
        # 4 cols, 5 rows = 20 labels per page
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
        # Thermal
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
    """Draw a single PRODUCT label on the canvas."""
    w = LABEL_WIDTH
    h = LABEL_HEIGHT

    # Background
    c.setFillColor(HexColor('#FFFFFF'))
    c.rect(0, 0, w, h, fill=1, stroke=0)

    # Border
    c.setStrokeColor(HexColor('#333333'))
    c.setLineWidth(1.5)
    c.rect(3 * mm, 3 * mm, w - 6 * mm, h - 6 * mm, fill=0, stroke=1)

    # ===== noon Logo Bar =====
    logo_y = h - 28 * mm
    c.setFillColor(HexColor('#FEEE00'))
    c.rect(3 * mm, logo_y, w - 6 * mm, 22 * mm, fill=1, stroke=0)

    c.setFillColor(HexColor('#2D2D2D'))
    c.setFont('Helvetica-Bold', 28)
    c.drawCentredString(w / 2, logo_y + 6 * mm, 'noon')

    # "PRODUCT LABEL" subtitle
    y = logo_y - 4 * mm
    c.setFillColor(HexColor('#FEEE00'))
    c.setFont('Helvetica-Bold', 9)
    c.drawCentredString(w / 2, logo_y - 1 * mm, '')  # spacer
    c.setFillColor(HexColor('#333333'))
    c.setFont('Helvetica-Bold', 10)
    c.drawCentredString(w / 2, y, 'PRODUCT LABEL')

    # Divider
    y -= 6 * mm
    c.setStrokeColor(HexColor('#CCCCCC'))
    c.setLineWidth(0.5)
    c.line(8 * mm, y, w - 8 * mm, y)

    # ===== Label Mark (large) =====
    y -= 10 * mm
    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 8)
    c.drawString(8 * mm, y + 3 * mm, 'LABEL MARK')
    c.setFillColor(HexColor('#000000'))
    c.setFont('Helvetica-Bold', 20)
    c.drawString(8 * mm, y - 8 * mm, label_mark)
    
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
    c.setStrokeColor(HexColor('#EEEEEE'))
    c.setDash(3, 2)
    c.line(8 * mm, y + 4 * mm, w - 8 * mm, y + 4 * mm)
    c.setDash()

    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 8)
    c.drawString(8 * mm, y, 'PRODUCT QUANTITY')
    c.setFillColor(HexColor('#000000'))
    c.setFont('Helvetica-Bold', 26)
    c.drawString(8 * mm, y - 12 * mm, str(total_qty))

    # Label counter
    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 9)
    c.drawRightString(w - 8 * mm, y - 8 * mm, f'Label {current_num} of {total_qty}')

    # ===== Barcode =====
    y -= 28 * mm
    c.setStrokeColor(HexColor('#EEEEEE'))
    c.setLineWidth(0.5)
    c.line(8 * mm, y + 2 * mm, w - 8 * mm, y + 2 * mm)

    barcode_value = label_mark.replace(' ', '_')
    try:
        barcode = code128.Code128(barcode_value, barWidth=0.6 * mm, barHeight=15 * mm)
        barcode_width = barcode.width
        x_pos = (w - barcode_width) / 2
        barcode.drawOn(c, x_pos, y - 18 * mm)
    except Exception:
        c.setFont('Courier', 10)
        c.drawCentredString(w / 2, y - 10 * mm, barcode_value)

    # Barcode text
    c.setFillColor(HexColor('#666666'))
    c.setFont('Courier', 8)
    c.drawCentredString(w / 2, y - 22 * mm, barcode_value)

    # Footer
    c.setFillColor(HexColor('#AAAAAA'))
    c.setFont('Helvetica', 6)
    c.drawCentredString(w / 2, 6 * mm, 'noon Seller Product Label \u2014 100mm x 150mm')


# =========================================================================
#  Carton Label Drawing
# =========================================================================

def _draw_carton_label(c, carton_mark, label_mark, total_qty, current_num, label_mark_2=None, label_mark_3=None, total_cartons=1, carton_asn=None):
    """Draw a single CARTON label on the canvas."""
    w = LABEL_WIDTH
    h = LABEL_HEIGHT

    # Background
    c.setFillColor(HexColor('#FFFFFF'))
    c.rect(0, 0, w, h, fill=1, stroke=0)

    # Thick border for carton
    c.setStrokeColor(HexColor('#2D2D2D'))
    c.setLineWidth(2.5)
    c.rect(3 * mm, 3 * mm, w - 6 * mm, h - 6 * mm, fill=0, stroke=1)

    # ===== noon Logo Bar (dark bg for carton) =====
    logo_y = h - 28 * mm
    c.setFillColor(HexColor('#2D2D2D'))
    c.rect(3 * mm, logo_y, w - 6 * mm, 22 * mm, fill=1, stroke=0)

    # noon text in yellow on dark
    c.setFillColor(HexColor('#FEEE00'))
    c.setFont('Helvetica-Bold', 28)
    c.drawCentredString(w / 2, logo_y + 6 * mm, 'noon')

    # "CARTON LABEL" subtitle
    y = logo_y - 4 * mm
    c.setFillColor(HexColor('#333333'))
    c.setFont('Helvetica-Bold', 10)
    c.drawCentredString(w / 2, y, 'CARTON LABEL')

    # Divider
    y -= 6 * mm
    c.setStrokeColor(HexColor('#CCCCCC'))
    c.setLineWidth(0.5)
    c.line(8 * mm, y, w - 8 * mm, y)

    # ===== Carton Mark (large, prominent) =====
    y -= 10 * mm
    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 8)
    c.drawString(8 * mm, y + 3 * mm, 'CARTON MARK')
    c.setFillColor(HexColor('#000000'))
    c.setFont('Helvetica-Bold', 22)
    c.drawString(8 * mm, y - 9 * mm, carton_mark)

    if carton_asn:
        y -= 17 * mm
        c.setFillColor(HexColor('#888888'))
        c.setFont('Helvetica', 8)
        c.drawString(8 * mm, y + 3 * mm, 'CARTON ASN')
        c.setFillColor(HexColor('#333333'))
        c.setFont('Helvetica-Bold', 18)
        c.drawString(8 * mm, y - 8 * mm, carton_asn)
        y -= 7 * mm
    else:
        y -= 14 * mm

    # ===== Product Quantity =====
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

    # Carton counter
    c.setFillColor(HexColor('#888888'))
    c.setFont('Helvetica', 9)
    c.drawRightString(w - 8 * mm, y - 6 * mm, f'Carton {current_num} of {total_cartons}')

    # ===== Barcode (encodes carton mark) =====
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

    # Barcode text
    c.setFillColor(HexColor('#666666'))
    c.setFont('Courier', 8)
    c.drawCentredString(w / 2, y - 22 * mm, barcode_value)

    # Footer
    c.setFillColor(HexColor('#AAAAAA'))
    c.setFont('Helvetica', 6)
    c.drawCentredString(w / 2, 6 * mm, 'noon Seller Carton Label \u2014 100mm x 150mm')
