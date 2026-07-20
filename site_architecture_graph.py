#!/usr/bin/env python3
"""
Generate a visual architecture/ER graph for the logistic_manager Django project.
Uses Pillow (PIL) to draw models, relationships, and workflows.
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT = BASE_DIR / "site_architecture_graph.png"

# Canvas size
WIDTH, HEIGHT = 3200, 2400
BG = "#f8f9fa"

# App colors
APP_COLORS = {
    "products": "#e3f2fd",      # light blue
    "customers": "#e8f5e9",     # light green
    "orders": "#fff3e0",        # light orange
    "khata": "#fce4ec",         # light pink
    "settings_manager": "#f3e5f5",  # light purple
    "portal": "#e0f2f1",        # light teal
    "noon_labels": "#fffde7",   # light yellow
    "django": "#eeeeee",        # grey
}

HEADER_BG = "#263238"
HEADER_FG = "#ffffff"
BOX_BORDER = "#37474f"
TEXT_COLOR = "#212121"
LINK_COLOR = "#1565c0"

def get_font(size):
    """Return a TrueType font if available, else default."""
    for name in ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()

font_title = get_font(36)
font_app = get_font(24)
font_model = get_font(20)
font_field = get_font(16)
font_note = get_font(18)

def text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

def draw_rounded_rect(draw, xy, fill, outline, radius=8, width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

def draw_model_box(draw, x, y, app, model_name, fields, max_width=280):
    """Draw a model box with header and fields. Returns (width, height)."""
    color = APP_COLORS.get(app, "#ffffff")
    margin = 12
    line_h = 22
    # Header
    mw, mh = text_size(draw, model_name, font_model)
    field_lines = []
    for f in fields:
        fw, _ = text_size(draw, f, font_field)
        if fw > max_width - margin * 2:
            # simple ellipsis
            f = f[:45] + "..."
        field_lines.append(f)
    box_w = max(mw, max((text_size(draw, f, font_field)[0] for f in field_lines), default=0)) + margin * 2
    box_w = max(box_w, 180)
    box_w = min(box_w, max_width)
    header_h = mh + margin * 2
    body_h = len(field_lines) * line_h + margin
    box_h = header_h + body_h
    # box
    draw_rounded_rect(draw, (x, y, x + box_w, y + box_h), fill="#ffffff", outline=BOX_BORDER, radius=8, width=2)
    # header background
    draw.rounded_rectangle((x, y, x + box_w, y + header_h), radius=8, fill=color, outline=BOX_BORDER, width=2)
    # if body exists, redraw bottom corners as square to merge; but rounded above is fine if body fills white
    if field_lines:
        draw.rectangle((x + 1, y + header_h - 10, x + box_w - 1, y + header_h), fill=color)
    draw.text((x + margin, y + margin), model_name, fill=TEXT_COLOR, font=font_model)
    for i, f in enumerate(field_lines):
        draw.text((x + margin, y + header_h + margin + i * line_h), f, fill="#455a64", font=font_field)
    return box_w, box_h

def draw_arrow(draw, x1, y1, x2, y2, color="#546e7a", label=None, font=None):
    draw.line([(x1, y1), (x2, y2)], fill=color, width=2)
    # arrowhead
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    ah = 10
    ax1 = x2 - ah * math.cos(angle - math.pi / 6)
    ay1 = y2 - ah * math.sin(angle - math.pi / 6)
    ax2 = x2 - ah * math.cos(angle + math.pi / 6)
    ay2 = y2 - ah * math.sin(angle + math.pi / 6)
    draw.polygon([(x2, y2), (ax1, ay1), (ax2, ay2)], fill=color)
    if label and font:
        lw, lh = text_size(draw, label, font)
        mx, my = (x1 + x2) // 2 - lw // 2, (y1 + y2) // 2 - lh // 2
        draw.rectangle((mx - 2, my - 2, mx + lw + 2, my + lh + 2), fill=BG)
        draw.text((mx, my), label, fill=color, font=font)

# Model definitions: (app, model_name, fields, x, y)
# We'll compute positions manually for clarity.
models = []

# Column 1: Public/Portal + Products
def add_model(app, name, fields, x, y):
    models.append((app, name, fields, x, y))

# Products column (left)
add_model("products", "Product", [
    "name", "price", "moq", "weight",
    "carton_length/width/height", "carton_qty",
    "price_air, price_sea", "is_draft, is_private", "sku"
], 80, 160)
add_model("products", "ProductImage", ["product (FK)", "image"], 80, 440)

# Customers column
add_model("customers", "Customer", [
    "name", "phone", "address", "email", "password",
    "is_active", "created_at"
], 420, 160)
add_model("customers", "CustomerProduct", [
    "customer (FK)", "product (FK)", "note", "assigned_at"
], 420, 460)

# Orders column (center)
add_model("orders", "Order", [
    "customer (FK)", "date", "total", "commission_amount",
    "commission_percentage", "cargo_type", "shipping_method",
    "shipping_rate", "shipping_cost", "shipping_companies (M2M)",
    "other_cost", "total_weight", "total_cbm", "status",
    "payment_status", "is_placed", "notes"
], 780, 120)
add_model("orders", "OrderItem", [
    "order (FK)", "product (FK)", "shipment_no", "shipment_name",
    "shipment_company (FK)", "shipment_method", "cargo_type",
    "shipment_cbm", "shipment_weight", "shipment_volumetric_weight",
    "shipment_shipping_cost", "quantity", "price"
], 780, 540)
add_model("orders", "OrderExtraCost", ["order (FK)", "amount", "reason"], 780, 920)
add_model("orders", "OrderNote", ["order (FK)", "user_type", "message", "created_at"], 1120, 920)
add_model("orders", "Notification", [
    "user (FK)", "customer (FK)", "order (FK)",
    "message", "notification_type", "is_read"
], 1120, 1120)

# Settings column
add_model("settings_manager", "CompanySettings", [
    "company_name, phone, address", "commission_percentage",
    "air/sea/ksa shipping rates", "NBB rates", "currency",
    "exchange_rate*", "fx_rates (JSON)", "email SMTP",
    "meta_pixel_id, og_image"
], 1480, 120)
add_model("settings_manager", "ShippingCompany", [
    "name", "website", "shipping_rate_sheet",
    "air_rate, sea_rate", "ksa_air_rate, ksa_sea_rate",
    "nbb_air_rate, nbb_sea_rate", "nbb_ksa_*"
], 1480, 520)

# Khata column
add_model("khata", "LedgerEntry", [
    "customer (FK)", "entry_type (credit/debit)",
    "amount", "currency", "date", "description"
], 1480, 900)

# Portal column
add_model("portal", "PasswordResetRequest", [
    "email", "token", "created_at", "is_used"
], 2040, 120)
add_model("portal", "ProductRequest", [
    "customer (FK)", "name", "description", "product_link",
    "requested_quantity", "status", "admin_notes",
    "converted_product (FK)", "created_at", "updated_at"
], 2040, 360)
add_model("portal", "ProductRequestImage", [
    "request (FK)", "image", "uploaded_by", "uploaded_at"
], 2040, 720)
add_model("portal", "PortfolioItem", [
    "title", "description", "media_type", "file",
    "is_active", "display_order"
], 2040, 960)
add_model("portal", "CartItem", [
    "customer (FK, opt)", "session_key", "product (FK)",
    "quantity", "created_at", "updated_at"
], 2040, 1220)

# Noon labels column
add_model("noon_labels", "LabelBatch", [
    "label_mark", "label_mark_2/3", "carton_mark",
    "carton_asn", "quantity", "carton_quantity"
], 2580, 160)

# Django built-in
add_model("django", "User", ["username", "email", "password", "is_staff"], 2580, 520)

# Layout pass: draw boxes and remember centers
img = Image.new("RGB", (WIDTH, HEIGHT), BG)
draw = ImageDraw.Draw(img)

# Title bar
draw.rectangle((0, 0, WIDTH, 80), fill=HEADER_BG)
draw.text((40, 20), "Logistic Manager — Site Architecture & Entity Relationship Graph", fill=HEADER_FG, font=font_title)
draw.text((40, 52), "Django project | mudassirllc.com | Models, relationships and main URL modules", fill="#b0bec5", font=font_note)

# Legend
legend_x, legend_y = 2580, 920
legend_items = list(APP_COLORS.items())
draw.text((legend_x, legend_y - 30), "App modules", fill=TEXT_COLOR, font=font_app)
for i, (app, color) in enumerate(legend_items):
    yy = legend_y + i * 34
    draw.rounded_rectangle((legend_x, yy, legend_x + 24, yy + 24), radius=4, fill=color, outline=BOX_BORDER, width=1)
    draw.text((legend_x + 32, yy + 2), app, fill=TEXT_COLOR, font=font_field)

# Draw all model boxes and store centers
box_centers = {}
box_sizes = {}
for app, name, fields, x, y in models:
    w, h = draw_model_box(draw, x, y, app, name, fields)
    box_sizes[name] = (w, h)
    box_centers[name] = (x + w // 2, y + h // 2)

# Relationship arrows: (from_model, to_model, label, x1_offset, y1_offset, x2_offset, y2_offset)
# Offsets are applied to center coordinates.
relationships = [
    ("Customer", "Order", "1:N"),
    ("Customer", "CustomerProduct", "1:N"),
    ("Customer", "LedgerEntry", "1:N"),
    ("Customer", "ProductRequest", "1:N"),
    ("Customer", "CartItem", "1:N"),
    ("Customer", "Notification", "1:N"),
    ("Product", "ProductImage", "1:N"),
    ("Product", "CustomerProduct", "1:N"),
    ("Product", "OrderItem", "1:N"),
    ("Product", "ProductRequest", "1:0..1"),
    ("Product", "CartItem", "1:N"),
    ("Order", "OrderItem", "1:N"),
    ("Order", "OrderExtraCost", "1:N"),
    ("Order", "OrderNote", "1:N"),
    ("Order", "Notification", "1:N"),
    ("ShippingCompany", "Order", "M:N"),
    ("ShippingCompany", "OrderItem", "N:1"),
    ("ProductRequest", "ProductRequestImage", "1:N"),
    ("User", "Notification", "1:N"),
]

# Helper to find box edge point between centers
def edge_point(cx1, cy1, cx2, cy2, w, h):
    import math
    dx, dy = cx2 - cx1, cy2 - cy1
    angle = math.atan2(dy, dx)
    # intersect with rectangle around center (w/2, h/2)
    hw, hh = w / 2, h / 2
    if abs(dx) < 1 and abs(dy) < 1:
        return cx1, cy1
    # compute t for x=hw and y=hh
    tx = hw / abs(math.cos(angle)) if math.cos(angle) != 0 else float('inf')
    ty = hh / abs(math.sin(angle)) if math.sin(angle) != 0 else float('inf')
    t = min(tx, ty)
    return cx1 + t * math.cos(angle), cy1 + t * math.sin(angle)

for from_name, to_name, label in relationships:
    if from_name not in box_centers or to_name not in box_centers:
        continue
    cx1, cy1 = box_centers[from_name]
    cx2, cy2 = box_centers[to_name]
    w1, h1 = box_sizes[from_name]
    w2, h2 = box_sizes[to_name]
    x1, y1 = edge_point(cx1, cy1, cx2, cy2, w1, h1)
    x2, y2 = edge_point(cx2, cy2, cx1, cy1, w2, h2)
    # if arrow connects to itself region, skip edge adjustment
    draw_arrow(draw, x1, y1, x2, y2, label=label, font=font_field)

# Add URL module labels
url_modules = [
    ("Public pages & SEO", "/, /portfolio, /about, /services, /contact, /sitemap.xml, /robots.txt"),
    ("Admin dashboard", "/dashboard/"),
    ("Products", "/products/ (CRUD, bulk upload, catalogue, export)"),
    ("Customers", "/customers/ (CRUD, assign products, quotation)"),
    ("Orders", "/orders/ (CRUD, invoice, packing list, reports, payment)"),
    ("Khata (Ledger)", "/khata/ (customer ledgers, payments)"),
    ("Noon Labels", "/noon-labels/ (generate product/carton labels)"),
    ("Settings", "/settings/ (company, shipping companies, calculator)"),
    ("Customer Portal", "/portal/ (login, dashboard, orders, cart, requests)"),
]
yy = HEIGHT - 240
draw.text((40, yy - 30), "Main URL modules", fill=TEXT_COLOR, font=font_app)
for i, (title, paths) in enumerate(url_modules):
    col = i % 3
    row = i // 3
    xx = 40 + col * 1000
    yyy = yy + row * 50
    draw.text((xx, yyy), f"• {title}: {paths}", fill=LINK_COLOR, font=font_field)

img.save(OUTPUT)
print(f"Saved architecture graph to {OUTPUT}")
