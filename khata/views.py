"""
Khata (Ledger) Views — Customer Credit & Debit Tracking System

Business Context:
"Khata" is a traditional South Asian term for a ledger/account book. In this logistics
business, customers typically deposit money in advance (credit) and the company records
goods/services given against that deposit (debit). This module tracks every dirham/yuan
the customer has paid in or been charged. The admin can record entries, view running
balances, and print ledger reports for settling accounts with customers.

Sign Convention (consistent across admin khata and customer portal):
    - CREDIT = money RECEIVED from the customer (payment/deposit).
    - DEBIT  = value GIVEN to the customer (goods, shipping, fees).
    - Balance = Total Credit - Total Debit.
      Positive balance  -> the customer has an advance/unused deposit with us.
      Negative balance  -> the customer owes us money (receivable).

Django Concepts Used:
- @login_required: Ensures only logged-in admin users can view or modify ledgers.
- get_object_or_404: Safely fetches a customer; returns 404 if not found instead of crashing.
- Django ORM aggregations (Sum): Used to calculate total credit and debit per currency.
- Decimal: Used for all money calculations to avoid floating-point errors.
"""

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
# Role-aware access guard: only users whose profile grants the 'khata' module
# (admins always, or staff with perm_khata) may reach these views.
from accounts.decorators import module_required
from django.db import transaction
from django.db.models import Count, Sum
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from customers.models import Customer
from .models import LedgerEntry, CURRENCY_CHOICES

# Set of valid currency codes for fast validation of user input.
VALID_CURRENCIES = {code for code, _ in CURRENCY_CHOICES}


# ---------------------------------------------------------------------------
# PDF font selection
# ---------------------------------------------------------------------------
# ReportLab's built-in Helvetica is Latin-1 only. Real ledger descriptions in
# this business contain Chinese characters (sourcing notes) and emoji pasted
# from WhatsApp, both of which Helvetica renders as garbage glyphs. We therefore
# register a Unicode TrueType font when one can be found on the host, preferring
# fonts that also cover CJK. The result is cached because probing the filesystem
# on every export would be wasteful.
#
# Candidates are ordered best-first: CJK-capable system fonts, then ReportLab's
# bundled Vera (Latin/Greek/Cyrillic, always present), then Helvetica.
_PDF_FONT_CANDIDATES = [
    # Windows (development machines)
    ('MicrosoftYaHei', r'C:\Windows\Fonts\msyh.ttc', True),
    ('SimSun', r'C:\Windows\Fonts\simsun.ttc', True),
    ('ArialUnicode', r'C:\Windows\Fonts\arialuni.ttf', True),
    # Linux (cPanel / typical server images)
    ('NotoSansCJK', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', True),
    ('NotoSansCJK', '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc', True),
    ('DejaVuSans', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', False),
    ('DejaVuSans', '/usr/share/fonts/dejavu/DejaVuSans.ttf', False),
]

_pdf_font_cache = None


def _register_pdf_font():
    """
    Register and return the best available Unicode font name for the ledger PDF.

    Returns:
        tuple: (regular_font_name, bold_font_name, supports_cjk)

    Falls back to Helvetica if nothing else can be registered, so the export
    always produces a PDF rather than failing on a host with no extra fonts.
    """
    global _pdf_font_cache
    if _pdf_font_cache is not None:
        return _pdf_font_cache

    import os as _os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for name, path, has_cjk in _PDF_FONT_CANDIDATES:
        if not _os.path.exists(path):
            continue
        try:
            # subfontIndex=0 picks the first face out of a .ttc collection.
            if path.lower().endswith('.ttc'):
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont(name, path))
            _pdf_font_cache = (name, name, has_cjk)
            return _pdf_font_cache
        except Exception:
            continue

    # ReportLab ships Vera; use it for broader Latin coverage than Helvetica.
    try:
        import reportlab
        fonts_dir = _os.path.join(_os.path.dirname(reportlab.__file__), 'fonts')
        pdfmetrics.registerFont(TTFont('Vera', _os.path.join(fonts_dir, 'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('VeraBd', _os.path.join(fonts_dir, 'VeraBd.ttf')))
        _pdf_font_cache = ('Vera', 'VeraBd', False)
    except Exception:
        _pdf_font_cache = ('Helvetica', 'Helvetica-Bold', False)
    return _pdf_font_cache


# Invisible characters that carry no meaning in a printed statement but render as
# stray glyphs: emoji variation selectors, the combining keycap, and zero-widths.
# Stripping U+FE0F/U+20E3 turns a pasted "1<keycap>" back into a plain "1".
_INVISIBLE_CHARS = dict.fromkeys(
    [0xFE0F, 0xFE0E, 0x20E3, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF], None
)


def _parse_date_range(request):
    """
    Read optional ?from=YYYY-MM-DD and ?to=YYYY-MM-DD query parameters.

    Returns:
        tuple: (date_from, date_to) as date objects or None when not supplied
               or unparseable. If both are given and reversed, they are swapped
               so the caller always receives a sane range.
    """
    def _parse(value):
        value = (value or '').strip()
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    date_from = _parse(request.GET.get('from'))
    date_to = _parse(request.GET.get('to'))
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    return date_from, date_to


def _filter_by_date(entries, date_from, date_to):
    """
    Narrow a LedgerEntry queryset to an inclusive [date_from, date_to] window.

    `date` is a timezone-aware DateTimeField, so we build aware datetime bounds
    covering the whole of each day rather than comparing against bare dates.
    That keeps the last day of the range fully included regardless of the time
    each entry was recorded.
    """
    if date_from:
        start = datetime.combine(date_from, time.min)
        if timezone.is_naive(start):
            start = timezone.make_aware(start)
        entries = entries.filter(date__gte=start)
    if date_to:
        end = datetime.combine(date_to, time.max)
        if timezone.is_naive(end):
            end = timezone.make_aware(end)
        entries = entries.filter(date__lte=end)
    return entries


def _per_currency_balances(entries):
    """
    Return {currency: balance} for a queryset of ledger entries.

    Balance = credit (received) - debit (given). Positive means the customer
    has an advance with us; negative means the customer owes us.
    """
    balances = {}
    rows = (
        entries.values('currency', 'entry_type')
        .annotate(total=Sum('amount'))
    )
    for row in rows:
        cur = row['currency']
        amount = row['total'] or Decimal('0')
        balances.setdefault(cur, Decimal('0'))
        if row['entry_type'] == LedgerEntry.CREDIT:
            balances[cur] += amount
        else:
            balances[cur] -= amount
    return balances


def _entries_with_running_balance(entries):
    """
    Return a list of {'entry': entry, 'running': Decimal} dicts with a
    per-currency running balance after each transaction (chronological order).
    """
    entries_with_running = []
    running = defaultdict(lambda: Decimal('0'))
    for entry in entries:
        if entry.entry_type == LedgerEntry.CREDIT:
            running[entry.currency] += entry.amount
        else:
            running[entry.currency] -= entry.amount
        entries_with_running.append({
            'entry': entry,
            'running': running[entry.currency],
        })
    return entries_with_running


@module_required('khata')
def ledger_home(request):
    """
    Display the ledger homepage showing ALL customers with their balance summaries.

    For each customer we show per-currency balances (credit - debit) and the
    number of transactions. Aggregation is done in a single grouped query
    instead of one query per customer per currency.
    """
    customers = Customer.objects.all()

    # One grouped query for all customers: (customer, currency, entry_type) -> Sum
    rows = (
        LedgerEntry.objects
        .values('customer_id', 'currency', 'entry_type')
        .annotate(total=Sum('amount'))
    )
    balances_by_customer = defaultdict(lambda: defaultdict(lambda: Decimal('0')))
    for row in rows:
        sign = Decimal('1') if row['entry_type'] == LedgerEntry.CREDIT else Decimal('-1')
        balances_by_customer[row['customer_id']][row['currency']] += sign * (row['total'] or Decimal('0'))

    # One grouped query for entry counts per customer
    counts = dict(
        LedgerEntry.objects
        .values('customer_id')
        .annotate(n=Count('id'))
        .values_list('customer_id', 'n')
    )

    customer_summaries = []
    with_balance_count = 0
    total_entries_all = 0
    for customer in customers:
        balances = {
            cur: bal for cur, bal in balances_by_customer.get(customer.id, {}).items()
            if bal != 0
        }
        total_entries = counts.get(customer.id, 0)
        total_entries_all += total_entries
        if balances:
            with_balance_count += 1
        customer_summaries.append({
            'customer': customer,
            'balances': balances,
            'total_entries': total_entries,
        })

    return render(request, 'khata/ledger_home.html', {
        'customer_summaries': customer_summaries,
        'currencies': CURRENCY_CHOICES,
        'with_balance_count': with_balance_count,
        'total_entries_all': total_entries_all,
    })


@module_required('khata')
def customer_ledger(request, customer_id):
    """
    Display the detailed ledger for a SINGLE customer with all transactions
    and a per-currency running balance.
    """
    customer = get_object_or_404(Customer, id=customer_id)
    entries = LedgerEntry.objects.filter(customer=customer).order_by('date')

    # An optional date filter drives both the on-screen table and the PDF export
    # link, so what the admin sees is exactly what gets exported.
    date_from, date_to = _parse_date_range(request)
    visible_entries = _filter_by_date(entries, date_from, date_to)

    return render(request, 'khata/customer_ledger.html', {
        'customer': customer,
        'entries_with_running': _entries_with_running_balance(visible_entries),
        # Balances always reflect the full ledger — the customer's real position
        # does not change just because the admin narrowed the view to a date range.
        'balances': _per_currency_balances(entries),
        'currencies': CURRENCY_CHOICES,
        'date_from': date_from.isoformat() if date_from else '',
        'date_to': date_to.isoformat() if date_to else '',
        'is_filtered': bool(date_from or date_to),
        'filtered_count': visible_entries.count(),
        'total_count': entries.count(),
    })


@module_required('khata')
def print_ledger(request, customer_id):
    """
    Generate a printable ledger report for a specific customer
    (same data as customer_ledger, print-friendly template).
    """
    customer = get_object_or_404(Customer, id=customer_id)
    entries = LedgerEntry.objects.filter(customer=customer).order_by('date')

    from settings_manager.models import CompanySettings
    settings = CompanySettings.get_settings()

    return render(request, 'khata/print_ledger.html', {
        'customer': customer,
        'entries_with_running': _entries_with_running_balance(entries),
        'balances': _per_currency_balances(entries),
        'settings': settings,
    })


@module_required('khata')
def export_ledger_pdf(request, customer_id):
    """
    Download a customer's ledger as a PDF, optionally restricted to a date range.

    Query parameters:
        from (YYYY-MM-DD, optional): Include entries on or after this date.
        to   (YYYY-MM-DD, optional): Include entries on or before this date.

    Both are optional; omitting them exports the full ledger.

    The PDF carries an opening balance line whenever a start date is given, so a
    date-range statement still reconciles: opening balance + movements in the
    period = closing balance. Without that, a mid-year statement would appear to
    start from zero and the totals would not match the customer's actual position.

    Built with ReportLab (pure Python) rather than WeasyPrint, which needs GTK
    system libraries that are not present on Windows or on cPanel shared hosting.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    from settings_manager.models import CompanySettings

    customer = get_object_or_404(Customer, id=customer_id)
    settings = CompanySettings.get_settings()
    date_from, date_to = _parse_date_range(request)

    all_entries = LedgerEntry.objects.filter(customer=customer).order_by('date')
    entries = list(_filter_by_date(all_entries, date_from, date_to))

    # Opening balance = net position before the window starts. Only meaningful
    # when a start date was supplied.
    opening = defaultdict(lambda: Decimal('0'))
    if date_from:
        start = datetime.combine(date_from, time.min)
        if timezone.is_naive(start):
            start = timezone.make_aware(start)
        for prior in all_entries.filter(date__lt=start):
            sign = Decimal('1') if prior.entry_type == LedgerEntry.CREDIT else Decimal('-1')
            opening[prior.currency] += sign * prior.amount

    # Brand palette, matching the on-screen admin theme.
    ACCENT = colors.HexColor('#C84B31')
    INK = colors.HexColor('#0F172A')
    MUTED = colors.HexColor('#64748B')
    LINE = colors.HexColor('#E2E8F0')
    GREEN = colors.HexColor('#16A34A')
    RED = colors.HexColor('#DC2626')
    ZEBRA = colors.HexColor('#F8FAFC')

    buffer = io.BytesIO()
    if date_from and date_to:
        period = f"{date_from.strftime('%d %b %Y')} — {date_to.strftime('%d %b %Y')}"
    elif date_from:
        period = f"From {date_from.strftime('%d %b %Y')}"
    elif date_to:
        period = f"Up to {date_to.strftime('%d %b %Y')}"
    else:
        period = 'All transactions'

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f'Ledger — {customer.name}',
        author=settings.company_name,
        subject=f'Account statement ({period})',
    )

    FONT, FONT_BOLD, _ = _register_pdf_font()

    base = getSampleStyleSheet()
    s_company = ParagraphStyle('company', parent=base['Normal'], fontName=FONT_BOLD,
                               fontSize=15, textColor=ACCENT, leading=18)
    s_meta = ParagraphStyle('meta', parent=base['Normal'], fontName=FONT,
                            fontSize=8, textColor=MUTED, leading=11)
    s_meta_r = ParagraphStyle('metar', parent=s_meta, alignment=TA_RIGHT)
    s_title = ParagraphStyle('title', parent=base['Normal'], fontName=FONT_BOLD,
                             fontSize=11, textColor=INK, leading=14)
    s_cell = ParagraphStyle('cell', parent=base['Normal'], fontName=FONT,
                            fontSize=8, textColor=INK, leading=10)
    s_foot = ParagraphStyle('foot', parent=base['Normal'], fontName=FONT,
                            fontSize=7, textColor=MUTED, alignment=TA_CENTER, leading=9)

    def money(value):
        """Format a Decimal with thousands separators and two decimals."""
        return f'{value:,.2f}'

    def para(text_value, style=None):
        """
        Build a Paragraph from untrusted text.

        ReportLab parses Paragraph content as mini-HTML, so a description
        containing '<' or '&' would raise and abort the whole PDF. Entry
        descriptions are free text typed by staff and routinely contain
        newlines and arithmetic like '96x6.8=652.8', so escape the markup
        characters and collapse whitespace into single spaces first.
        """
        cleaned = str(text_value or '').translate(_INVISIBLE_CHARS)
        cleaned = ' '.join(cleaned.split())
        cleaned = cleaned.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return Paragraph(cleaned, style or s_cell)

    story = []

    # ---- Header: company on the left, statement meta on the right ----
    def esc(value):
        """Escape markup characters while keeping the text otherwise intact."""
        return str(value or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    company_lines = ['']  # placeholder; the name is rendered in the header table below
    if settings.company_address:
        # Deliberate <br/>: the address is multi-line and should stay that way.
        company_lines.append(esc(settings.company_address).replace('\n', '<br/>'))
    if settings.company_phone:
        company_lines.append(esc(settings.company_phone))

    story.append(Table(
        [[
            para(settings.company_name, s_company),
            Paragraph(f'<b>ACCOUNT STATEMENT</b><br/>{period}<br/>'
                      f'Generated {timezone.localtime().strftime("%d %b %Y, %H:%M")}', s_meta_r),
        ]],
        colWidths=[105 * mm, 73 * mm],
        style=TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]),
    ))
    if len(company_lines) > 1:
        story.append(Spacer(1, 3))
        story.append(Paragraph('<br/>'.join(company_lines[1:]), s_meta))

    story.append(Spacer(1, 10))
    story.append(Table([['']], colWidths=[178 * mm], rowHeights=[1.6],
                       style=TableStyle([('BACKGROUND', (0, 0), (-1, -1), ACCENT)])))
    story.append(Spacer(1, 12))

    # ---- Customer block ----
    contact = ' · '.join(x for x in [customer.phone, customer.email] if x)
    story.append(para(customer.name, ParagraphStyle('cust', parent=s_title)))
    if contact:
        story.append(para(contact, s_meta))
    story.append(Spacer(1, 12))

    # ---- Transactions, grouped per currency ----
    currencies = sorted({e.currency for e in entries} | set(opening.keys()))
    if not currencies:
        story.append(Paragraph('No transactions in this period.', s_cell))

    closing_rows = []
    for currency in currencies:
        rows = [[
            Paragraph('<b>Date</b>', s_cell), Paragraph('<b>Description</b>', s_cell),
            Paragraph('<b>Credit</b>', s_cell), Paragraph('<b>Debit</b>', s_cell),
            Paragraph('<b>Balance</b>', s_cell),
        ]]

        running = opening.get(currency, Decimal('0'))
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
            ('LINEBELOW', (0, 0), (-1, 0), 0.7, ACCENT),
            ('GRID', (0, 0), (-1, -1), 0.25, LINE),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]

        # Opening balance row (only when the statement starts mid-ledger).
        if date_from:
            rows.append([
                Paragraph(date_from.strftime('%d %b %Y'), s_cell),
                Paragraph('<i>Opening balance</i>', s_cell),
                '', '', money(running),
            ])
            style_cmds.append(('TEXTCOLOR', (0, 1), (-1, 1), MUTED))

        for entry in (e for e in entries if e.currency == currency):
            is_credit = entry.entry_type == LedgerEntry.CREDIT
            running += entry.amount if is_credit else -entry.amount
            row_index = len(rows)
            rows.append([
                Paragraph(timezone.localtime(entry.date).strftime('%d %b %Y'), s_cell),
                para(entry.description or '—'),
                money(entry.amount) if is_credit else '',
                money(entry.amount) if not is_credit else '',
                money(running),
            ])
            style_cmds.append(('TEXTCOLOR', (2, row_index), (2, row_index), GREEN))
            style_cmds.append(('TEXTCOLOR', (3, row_index), (3, row_index), RED))
            style_cmds.append(('TEXTCOLOR', (4, row_index), (4, row_index), GREEN if running >= 0 else RED))
            if row_index % 2 == 0:
                style_cmds.append(('BACKGROUND', (0, row_index), (-1, row_index), ZEBRA))

        # Period totals + closing balance.
        total_credit = sum((e.amount for e in entries if e.currency == currency and e.entry_type == LedgerEntry.CREDIT), Decimal('0'))
        total_debit = sum((e.amount for e in entries if e.currency == currency and e.entry_type == LedgerEntry.DEBIT), Decimal('0'))
        total_index = len(rows)
        rows.append([
            Paragraph('<b>Closing balance</b>', s_cell), '',
            money(total_credit), money(total_debit), money(running),
        ])
        style_cmds += [
            ('SPAN', (0, total_index), (1, total_index)),
            ('BACKGROUND', (0, total_index), (-1, total_index), colors.HexColor('#F1F5F9')),
            ('LINEABOVE', (0, total_index), (-1, total_index), 0.7, ACCENT),
            ('FONTNAME', (2, total_index), (-1, total_index), FONT_BOLD),
            ('TEXTCOLOR', (4, total_index), (4, total_index), GREEN if running >= 0 else RED),
        ]

        story.append(KeepTogether([
            Paragraph(f'<b>{currency}</b>', s_title),
            Spacer(1, 5),
            Table(rows, colWidths=[24 * mm, 78 * mm, 25 * mm, 25 * mm, 26 * mm],
                  style=TableStyle(style_cmds), repeatRows=1),
            Spacer(1, 14),
        ]))
        closing_rows.append((currency, running))

    # ---- Summary of closing balances ----
    if closing_rows:
        summary = [[Paragraph('<b>Currency</b>', s_cell),
                    Paragraph('<b>Closing balance</b>', s_cell),
                    Paragraph('<b>Position</b>', s_cell)]]
        summary_style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
            ('GRID', (0, 0), (-1, -1), 0.25, LINE),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]
        for i, (currency, balance) in enumerate(closing_rows, start=1):
            # Positive = the customer is in credit with us; negative = they owe us.
            position = 'Advance held' if balance >= 0 else 'Customer owes'
            summary.append([currency, money(balance), position])
            summary_style.append(('TEXTCOLOR', (1, i), (1, i), GREEN if balance >= 0 else RED))
            summary_style.append(('FONTNAME', (1, i), (1, i), FONT_BOLD))

        story.append(Paragraph('<b>Summary</b>', s_title))
        story.append(Spacer(1, 5))
        story.append(Table(summary, colWidths=[30 * mm, 40 * mm, 40 * mm], style=TableStyle(summary_style)))

    story.append(Spacer(1, 18))
    story.append(Paragraph(
        'Credit = payment received from customer · Debit = goods or services provided. '
        'A positive closing balance means the customer holds an advance with us.', s_foot))

    def _decorate(canvas_obj, doc_obj):
        """Draw the page number in the footer of every page."""
        canvas_obj.saveState()
        canvas_obj.setFont(FONT, 7)
        canvas_obj.setFillColor(MUTED)
        canvas_obj.drawCentredString(A4[0] / 2, 10 * mm, f'Page {doc_obj.page}')
        canvas_obj.restoreState()

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    buffer.seek(0)

    slug = ''.join(c if c.isalnum() else '-' for c in customer.name).strip('-').lower() or 'customer'
    suffix = ''
    if date_from or date_to:
        suffix = f"_{date_from or 'start'}_to_{date_to or 'today'}"
    return FileResponse(buffer, as_attachment=True, filename=f'ledger_{slug}{suffix}.pdf')


# =============================================================================
# CSV IMPORT / EXPORT
# =============================================================================
# The ledger could only leave the system as a PDF, which is a document for a
# human to read, not data. There was no way to get an existing account book IN
# at all, so a business moving over from a spreadsheet had to retype years of
# history, and no way to get the numbers OUT into anything an accountant could
# reconcile.
#
# The export and the import speak the SAME column set deliberately: whatever you
# download can be edited and uploaded back without translation.
# =============================================================================

# The canonical column order. Export writes these; import accepts them in any
# order, matched by header name.
LEDGER_CSV_COLUMNS = ['date', 'customer', 'entry_type', 'amount', 'currency', 'description']

# Words people actually type in a spreadsheet for the two entry types. The
# ledger's own vocabulary ("credit" money in, "debit" money owed) is not what a
# non-accountant reaches for, and rejecting a file over the word "payment" is a
# pointless obstacle.
ENTRY_TYPE_SYNONYMS = {
    'credit': LedgerEntry.CREDIT,
    'cr': LedgerEntry.CREDIT,
    'payment': LedgerEntry.CREDIT,
    'paid': LedgerEntry.CREDIT,
    'received': LedgerEntry.CREDIT,
    'in': LedgerEntry.CREDIT,
    'debit': LedgerEntry.DEBIT,
    'dr': LedgerEntry.DEBIT,
    'charge': LedgerEntry.DEBIT,
    'invoice': LedgerEntry.DEBIT,
    'owed': LedgerEntry.DEBIT,
    'out': LedgerEntry.DEBIT,
}

# Accepted date formats, tried in order. ISO first because that is what the
# export writes and therefore what a round-tripped file contains. The rest cover
# what Excel produces in a UAE/UK locale.
_DATE_FORMATS = [
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d %H:%M',
    '%Y-%m-%d',
    '%d/%m/%Y %H:%M',
    '%d/%m/%Y',
    '%d-%m-%Y',
    '%d.%m.%Y',
]


def _parse_entry_datetime(raw):
    """
    Parse a user-supplied date into an aware datetime, or None if unparseable.

    Args:
        raw (str): Date text from a form field or a CSV cell.

    Returns:
        datetime | None: Timezone-aware datetime, or None when nothing matched.

    Note on ambiguity:
        '03/04/2026' is deliberately read as 3 April, not 4 March. This business
        operates in the UAE and sources from China; day-first is the convention
        in both. The export writes ISO dates precisely so a round trip is never
        ambiguous.
    """
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed
    return None


def _ledger_csv_rows(entries):
    """
    Yield CSV rows for a queryset of ledger entries, header first.

    Args:
        entries (QuerySet): LedgerEntry rows, already filtered and ordered.

    Yields:
        list: One row of cell values.
    """
    yield LEDGER_CSV_COLUMNS
    for entry in entries:
        yield [
            timezone.localtime(entry.date).strftime('%Y-%m-%d %H:%M'),
            entry.customer.name,
            entry.entry_type,
            f'{entry.amount:.2f}',
            entry.currency,
            (entry.description or '').replace('\r\n', ' ').replace('\n', ' '),
        ]


@module_required('khata')
def export_ledger_csv(request, customer_id=None):
    """
    Download ledger entries as CSV — one customer, or the whole book.

    Args:
        request (HttpRequest): GET, optionally with ?from= and ?to= dates.
        customer_id (int, optional): Restrict to one customer. None exports all.

    Returns:
        HttpResponse: A text/csv attachment.

    Why UTF-8 BOM:
        Customer names and descriptions contain Arabic and Chinese. Excel on
        Windows assumes the system codepage for a .csv with no BOM and renders
        those as mojibake, which looks like data loss to the person opening it.
        utf-8-sig writes the marker that makes Excel read it as UTF-8.
    """
    entries = LedgerEntry.objects.select_related('customer')

    customer = None
    if customer_id is not None:
        customer = get_object_or_404(Customer, id=customer_id)
        entries = entries.filter(customer=customer)

    date_from, date_to = _parse_date_range(request)
    entries = _filter_by_date(entries, date_from, date_to)
    entries = entries.order_by('date', 'id')

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in _ledger_csv_rows(entries):
        writer.writerow(row)

    stem = slugify(customer.name) if customer else 'all-customers'
    span = ''
    if date_from or date_to:
        span = f"_{date_from or 'start'}_to_{date_to or 'today'}"
    filename = f'ledger_{stem}{span}.csv'

    response = HttpResponse(
        buffer.getvalue().encode('utf-8-sig'),
        content_type='text/csv; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _read_csv_rows(upload):
    """
    Decode an uploaded CSV into dicts keyed by lowercased header.

    Args:
        upload (UploadedFile): The submitted file.

    Returns:
        tuple[list, str]: (rows, error). `error` is non-empty on failure.

    Encoding:
        utf-8-sig first, because a file exported from here or saved by Excel as
        "CSV UTF-8" carries a BOM that would otherwise appear inside the first
        header name and break the column match. cp1252 is the fallback for a
        plain Excel "CSV" save on a Western Windows machine.
    """
    raw = upload.read()
    text = None
    for encoding in ('utf-8-sig', 'cp1252'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return [], 'Could not read the file. Save it as CSV UTF-8 and try again.'

    try:
        # Sniffing handles the semicolon delimiter Excel writes in several
        # European locales. A short or odd file defeats it, so comma is assumed.
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        return [], 'That file has no header row.'

    normalised = [(name or '').strip().lower() for name in reader.fieldnames]
    missing = [c for c in ('customer', 'entry_type', 'amount') if c not in normalised]
    if missing:
        return [], (
            'Missing required column(s): ' + ', '.join(missing) + '. '
            'Expected headers: ' + ', '.join(LEDGER_CSV_COLUMNS) + '.'
        )

    rows = []
    for record in reader:
        rows.append({
            (key or '').strip().lower(): (value or '').strip()
            for key, value in record.items()
        })
    return rows, ''


@module_required('khata')
@require_POST
def import_ledger_csv(request):
    """
    Import ledger entries from a CSV file.

    Args:
        request (HttpRequest): POST with `csv_file`, optional `dry_run=1`.

    Returns:
        JsonResponse: {'success', 'message', 'created', 'skipped', 'errors', ...}

    Two decisions worth stating plainly, both because this is money:

    ALL OR NOTHING. Every row is validated before anything is written, and the
    write runs inside one transaction. A partly-applied import of an account
    book is worse than a rejected one: the balances are wrong, and nobody knows
    which rows landed. If any row fails, the whole file is rejected and every
    problem is reported at once so it can be fixed in a single pass.

    DUPLICATES ARE SKIPPED, NOT INSERTED. Uploading the same file twice would
    otherwise silently double every balance in it. A row matching an existing
    entry on customer, date, type, amount, currency and description is treated
    as already imported. That makes a re-run safe and makes "did that upload
    work?" a question you can answer by simply doing it again.
    """
    upload = request.FILES.get('csv_file')
    if not upload:
        return JsonResponse({'success': False, 'message': 'Choose a CSV file first.'})
    if upload.size > 5 * 1024 * 1024:
        return JsonResponse({'success': False, 'message': 'That file is larger than 5 MB.'})

    rows, read_error = _read_csv_rows(upload)
    if read_error:
        return JsonResponse({'success': False, 'message': read_error})
    if not rows:
        return JsonResponse({'success': False, 'message': 'That file has no data rows.'})
    if len(rows) > 5000:
        return JsonResponse({
            'success': False,
            'message': f'{len(rows)} rows is more than one import can take. Split the file into blocks of 5,000.',
        })

    # Customers are matched by name, case-insensitively. Built once up front
    # rather than a query per row: a 5,000-row file would otherwise be 5,000
    # round trips. A name used by two customers is ambiguous and is reported
    # rather than guessed at.
    by_name = defaultdict(list)
    for customer in Customer.objects.all():
        by_name[customer.name.strip().lower()].append(customer)

    errors = []
    staged = []

    for index, row in enumerate(rows, start=2):    # start=2: row 1 is the header
        def fail(message):
            errors.append(f'Row {index}: {message}')

        name = row.get('customer', '')
        if not name:
            fail('customer is blank.')
            continue
        matches = by_name.get(name.lower(), [])
        if not matches:
            fail(f'no customer named "{name}".')
            continue
        if len(matches) > 1:
            fail(f'"{name}" matches {len(matches)} customers. Rename them so they are distinct.')
            continue
        customer = matches[0]

        entry_type = ENTRY_TYPE_SYNONYMS.get(row.get('entry_type', '').lower())
        if not entry_type:
            fail(f'entry_type "{row.get("entry_type", "")}" is not credit or debit.')
            continue

        # Strip thousands separators and currency symbols that survive a
        # spreadsheet export: "1,250.00" and "AED 1250" are both meant as 1250.
        raw_amount = re.sub(r'[^\d.\-]', '', row.get('amount', ''))
        try:
            amount = Decimal(raw_amount)
        except (InvalidOperation, ValueError):
            fail(f'amount "{row.get("amount", "")}" is not a number.')
            continue
        if amount <= 0:
            fail('amount must be greater than zero.')
            continue
        if amount >= Decimal('100000000'):
            fail('amount is too large.')
            continue

        currency = (row.get('currency') or 'AED').upper()
        if currency not in VALID_CURRENCIES:
            fail(f'currency "{currency}" is not one of {", ".join(sorted(VALID_CURRENCIES))}.')
            continue

        raw_date = row.get('date', '')
        if raw_date:
            entry_date = _parse_entry_datetime(raw_date)
            if entry_date is None:
                fail(f'date "{raw_date}" is not a date. Use YYYY-MM-DD.')
                continue
        else:
            # No date column, or a blank cell. Defaulting to now is right for a
            # file of today's transactions and wrong for historical data, so the
            # count is reported back rather than passing silently.
            entry_date = timezone.now()

        staged.append({
            'customer': customer,
            'entry_type': entry_type,
            'amount': amount.quantize(Decimal('0.01')),
            'currency': currency,
            'description': row.get('description', '')[:2000],
            'date': entry_date,
            'dated': bool(raw_date),
        })

    if errors:
        return JsonResponse({
            'success': False,
            'message': f'{len(errors)} row(s) have problems. Nothing was imported.',
            # Capped so one badly-formed file cannot return a megabyte of text.
            'errors': errors[:50],
            'error_count': len(errors),
        })

    # Duplicate detection. One query covering the customers and date span in the
    # file, rather than a lookup per row.
    dates = [item['date'] for item in staged]
    existing = LedgerEntry.objects.filter(
        customer__in={item['customer'].id for item in staged},
        date__gte=min(dates),
        date__lte=max(dates),
    ).values_list('customer_id', 'date', 'entry_type', 'amount', 'currency', 'description')
    seen = {
        (cid, d.replace(microsecond=0), etype, amt, cur, (desc or '').strip())
        for cid, d, etype, amt, cur, desc in existing
    }

    fresh, duplicates = [], 0
    for item in staged:
        key = (
            item['customer'].id, item['date'].replace(microsecond=0), item['entry_type'],
            item['amount'], item['currency'], item['description'].strip(),
        )
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)          # also catches rows duplicated within the file itself
        fresh.append(item)

    undated = sum(1 for item in fresh if not item['dated'])

    if request.POST.get('dry_run') == '1':
        return JsonResponse({
            'success': True,
            'dry_run': True,
            'created': len(fresh),
            'skipped': duplicates,
            'undated': undated,
            'message': _describe_import(len(fresh), duplicates, undated, applied=False),
        })

    with transaction.atomic():
        LedgerEntry.objects.bulk_create([
            LedgerEntry(
                customer=item['customer'],
                entry_type=item['entry_type'],
                amount=item['amount'],
                currency=item['currency'],
                description=item['description'],
                date=item['date'],
            )
            for item in fresh
        ])

    return JsonResponse({
        'success': True,
        'created': len(fresh),
        'skipped': duplicates,
        'undated': undated,
        'message': _describe_import(len(fresh), duplicates, undated, applied=True),
    })


def _describe_import(created, duplicates, undated, applied):
    """Build the sentence shown after an import or its preview."""
    verb = 'Imported' if applied else 'Ready to import'
    parts = [f'{verb} {created} entr' + ('y' if created == 1 else 'ies') + '.']
    if duplicates:
        parts.append(
            f'{duplicates} skipped as already in the ledger.'
        )
    if undated:
        parts.append(
            f'{undated} had no date and will be filed under today.'
        )
    return ' '.join(parts)


@module_required('khata')
@require_POST
def add_entry(request):
    """
    AJAX endpoint to add a new credit or debit entry to a customer's ledger.

    Validates every field before touching the database:
    - customer must exist
    - entry_type must be 'credit' or 'debit'
    - amount must be a positive number
    - currency must be one of the supported currencies
    """
    customer_id = request.POST.get('customer_id')
    entry_type = request.POST.get('entry_type', '').strip()
    currency = request.POST.get('currency', 'AED').strip()
    description = request.POST.get('description', '').strip()

    try:
        customer = Customer.objects.get(id=customer_id)
    except (Customer.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Customer not found'})

    if entry_type not in {LedgerEntry.CREDIT, LedgerEntry.DEBIT}:
        return JsonResponse({'success': False, 'message': 'Invalid entry type'})

    if currency not in VALID_CURRENCIES:
        return JsonResponse({'success': False, 'message': 'Invalid currency'})

    try:
        amount = Decimal(str(request.POST.get('amount', '')).strip())
    except InvalidOperation:
        return JsonResponse({'success': False, 'message': 'Invalid amount'})
    if amount <= 0:
        return JsonResponse({'success': False, 'message': 'Amount must be greater than zero'})
    if amount >= Decimal('100000000'):
        return JsonResponse({'success': False, 'message': 'Amount is too large'})

    # Optional: the date the transaction actually happened. Money received on
    # Tuesday and entered on Friday belongs on Tuesday, or every date-filtered
    # statement reports the wrong figures.
    entry_date = timezone.now()
    raw_date = (request.POST.get('date') or '').strip()
    if raw_date:
        parsed = _parse_entry_datetime(raw_date)
        if parsed is None:
            return JsonResponse({
                'success': False,
                'message': 'Invalid date. Use YYYY-MM-DD or YYYY-MM-DD HH:MM.',
            })
        entry_date = parsed

    LedgerEntry.objects.create(
        customer=customer,
        entry_type=entry_type,
        amount=amount.quantize(Decimal('0.01')),
        currency=currency,
        description=description,
        date=entry_date,
    )
    return JsonResponse({'success': True, 'message': f'{entry_type.capitalize()} entry added!'})


@module_required('khata')
@require_POST
def delete_entry(request, entry_id):
    """
    AJAX endpoint to delete a ledger entry (e.g., recorded by mistake).
    """
    try:
        entry = LedgerEntry.objects.get(id=entry_id)
    except LedgerEntry.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Entry not found'})
    entry.delete()
    return JsonResponse({'success': True, 'message': 'Entry deleted!'})
