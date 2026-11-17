"""
Rate request sheets: the Excel document a freight forwarder fills in.

WHAT THIS IS FOR

Getting rates out of a forwarder is a back-and-forth over WhatsApp that arrives
as a photo of a printout, a PDF, or a message saying "22 for general, 45 with
battery" with no mention of the divisor, the minimum, or which country. Then it
has to be typed in by hand, and the parts nobody quoted get guessed at.

This sends them a document with every question already asked: one row per cargo
type, one sheet per country, and columns for the things that decide the price
but never get volunteered. They fill it in, send it back, and it is read
straight into the rate table.

AIR AND SEA ARE SEPARATE DOCUMENTS

Not two tabs of one file. They are usually quoted by different desks at the
forwarder, they arrive weeks apart, and air needs a volumetric divisor and a
minimum weight while sea needs a minimum CBM. One combined sheet would ask
every recipient to ignore half the columns, which is how columns get filled in
wrong.

ROUND-TRIPPING

A returned sheet is matched on the country code and the cargo type SLUG, both
written into the file when it is generated, not on the sheet name or the
printed label. A forwarder who renames a tab, reorders the rows, or corrects
your spelling of their country still imports cleanly. Anything unrecognised is
reported rather than silently dropped - a rate that did not import is worse
than one that failed loudly, because it looks like a rate you were never given.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .models import CargoType, ShippingDestination, ShippingRate

# Where the fixed parts of a sheet live. Import reads these positions, so
# changing one means changing both ends.
ROW_TITLE = 1
ROW_COMPANY = 2
ROW_DESTINATION = 3
ROW_CURRENCY = 4
ROW_VALIDITY = 5
ROW_HEADER = 7
ROW_FIRST_RATE = 8

# Column layouts. The slug is written in the last column and kept narrow rather
# than hidden: a hidden column gets deleted by someone tidying the file up,
# whereas a visible one labelled "do not edit" tends to survive.
AIR_COLUMNS = [
    ('Cargo Type', 30),
    ('Rate per KG', 16),
    ('Minimum Chargeable KG', 22),
    ('Volumetric Divisor', 18),
    ('Transit Days', 14),
    ('Notes', 34),
    ('ref', 22),
]
SEA_COLUMNS = [
    ('Cargo Type', 30),
    ('Rate per CBM', 16),
    ('Minimum CBM', 16),
    ('Transit Days', 14),
    ('Notes', 34),
    ('ref', 22),
]

INK = '1F2933'
GOLD = 'B8860B'
HEADER_FILL = PatternFill('solid', fgColor='1F2933')
ENTRY_FILL = PatternFill('solid', fgColor='FFF8E1')
BAND_FILL = PatternFill('solid', fgColor='F5F7FA')
THIN = Side(style='thin', color='C9D2DD')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def columns_for(method):
    """The column layout for a method. Air carries the divisor, sea does not."""
    return AIR_COLUMNS if method == ShippingRate.METHOD_AIR else SEA_COLUMNS


def _ref(destination, cargo_type):
    """
    The machine-readable key written into each row.

    Format: ``AE|non-branded-battery``. This is what import matches on, so a
    forwarder can rewrite every visible label and the file still lands in the
    right rows.
    """
    return f'{destination.code}|{cargo_type.slug}'


def _parse_ref(value):
    """Split a ref back into (country code, cargo slug), or (None, None)."""
    if not value or '|' not in str(value):
        return None, None
    code, _, slug = str(value).strip().partition('|')
    return code.strip().upper(), slug.strip().lower()


def _decimal_or_none(value):
    """
    A cell into a Decimal, or None when it holds nothing usable.

    None and 0 mean different things here. An empty cell is "not quoted" and
    must leave any existing rate alone; a typed 0 is also "not quoted" but is a
    deliberate statement. Text like 'n/a' or '-' is what forwarders actually
    write for a lane they will not carry, so it reads as None rather than
    failing the import.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Strip anything that is obviously a unit or a currency the forwarder added.
    cleaned = text.replace(',', '')
    for junk in ('AED', 'USD', 'RMB', 'SAR', '$', '/kg', '/KG', '/cbm', '/CBM', 'kg', 'KG'):
        cleaned = cleaned.replace(junk, '')
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    try:
        parsed = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed >= 0 else None


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def build_rate_request(company, method, destinations=None, cargo_types=None,
                       currency='AED'):
    """
    Build the rate request workbook for one company and one method.

    Args:
        company (ShippingCompany): who it is for.
        method (str): ShippingRate.METHOD_AIR or METHOD_SEA.
        destinations (iterable | None): defaults to every active destination.
        cargo_types (iterable | None): defaults to every active cargo type.
        currency (str): printed on the sheet so the forwarder quotes in it.

    Returns:
        Workbook: one sheet per destination, plus instructions.

    Any rate already on file is pre-filled. A forwarder reviewing last quarter's
    numbers only has to change what moved, and you can see at a glance what they
    changed - which a blank form makes impossible.
    """
    if destinations is None:
        destinations = list(ShippingDestination.objects.filter(is_active=True))
    if cargo_types is None:
        cargo_types = list(CargoType.objects.filter(is_active=True))

    existing = {
        (r.destination_id, r.cargo_type_id): r
        for r in ShippingRate.objects.filter(company=company, method=method)
    }

    workbook = Workbook()
    workbook.remove(workbook.active)  # drop the default sheet; we name our own

    _add_instructions(workbook, company, method, currency)

    for destination in destinations:
        _add_destination_sheet(
            workbook, company, method, destination, cargo_types, existing, currency)

    return workbook


def _add_instructions(workbook, company, method, currency):
    """A short cover sheet. Unread by some, but it costs one tab."""
    sheet = workbook.create_sheet('Instructions')
    label = 'AIR' if method == ShippingRate.METHOD_AIR else 'SEA'

    lines = [
        (f'{label} FREIGHT RATE REQUEST', True),
        ('', False),
        (f'For: {company.name}', False),
        (f'Issued: {date.today():%d %B %Y}', False),
        ('', False),
        ('How to complete this form', True),
        ('', False),
        ('1. There is one tab per destination country. Please complete every tab', False),
        ('   you can serve, and leave a tab blank if you do not serve it.', False),
        ('2. Quote every rate in ' + currency + '.', False),
        ('3. Leave a row blank if you do not carry that category. A blank row is', False),
        ('   understood as "not offered" - it will not be treated as free.', False),
    ]
    if method == ShippingRate.METHOD_AIR:
        lines += [
            ('4. The volumetric divisor matters as much as the rate. 6000 is the', False),
            ('   IATA standard; 5000 is common for express and prices the same', False),
            ('   carton about 20% higher. Please state the one you apply.', False),
            ('5. State your minimum chargeable weight if you have one.', False),
        ]
    else:
        lines += [
            ('4. Sea rates are per CBM. Please state your minimum CBM if you', False),
            ('   have one - most consolidators charge a 1 CBM minimum.', False),
        ]
    lines += [
        ('', False),
        ('Please do not delete or edit the "ref" column. It is how your rates are', False),
        ('read back into our system, and rows without it have to be typed in by hand.', False),
    ]

    for index, (text, bold) in enumerate(lines, start=1):
        cell = sheet.cell(row=index, column=1, value=text)
        cell.font = Font(bold=bold, size=13 if index == 1 else 11,
                         color=INK if not bold else GOLD)
    sheet.column_dimensions['A'].width = 90
    return sheet


def _add_destination_sheet(workbook, company, method, destination, cargo_types,
                           existing, currency):
    """One country's rate table."""
    # Excel forbids []:*?/\ in tab names and caps them at 31 characters.
    safe = ''.join(c for c in destination.name if c not in '[]:*?/\\')[:31]
    sheet = workbook.create_sheet(safe or destination.code)

    columns = columns_for(method)
    label = 'AIR' if method == ShippingRate.METHOD_AIR else 'SEA'

    title = sheet.cell(row=ROW_TITLE, column=1,
                       value=f'{label} FREIGHT RATE REQUEST')
    title.font = Font(bold=True, size=14, color=GOLD)

    for row_number, (heading, value) in [
        (ROW_COMPANY, ('Company', company.name)),
        # The code in brackets is a fallback for import when the ref column has
        # been deleted - it lets a whole sheet still be matched to a country.
        (ROW_DESTINATION, ('Destination', f'{destination.name} ({destination.code})')),
        (ROW_CURRENCY, ('Currency', currency)),
        (ROW_VALIDITY, ('Rates valid until', '')),
    ]:
        sheet.cell(row=row_number, column=1, value=heading).font = Font(bold=True)
        cell = sheet.cell(row=row_number, column=2, value=value)
        if row_number == ROW_VALIDITY:
            # The one header field the forwarder fills in.
            cell.fill = ENTRY_FILL
            cell.border = BORDER

    for index, (heading, width) in enumerate(columns, start=1):
        cell = sheet.cell(row=ROW_HEADER, column=index, value=heading)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center',
                                   wrap_text=True)
        cell.border = BORDER
        sheet.column_dimensions[get_column_letter(index)].width = width

    for offset, cargo_type in enumerate(cargo_types):
        row = ROW_FIRST_RATE + offset
        rate = existing.get((destination.id, cargo_type.id))
        _write_rate_row(sheet, row, method, cargo_type, destination, rate,
                        banded=offset % 2 == 1)

    _finish_sheet(sheet, len(columns), ROW_FIRST_RATE + len(cargo_types) - 1)
    return sheet


def _write_rate_row(sheet, row, method, cargo_type, destination, rate, banded):
    """One cargo type's row, pre-filled from `rate` when there is one."""
    air = method == ShippingRate.METHOD_AIR

    name = sheet.cell(row=row, column=1, value=cargo_type.name)
    name.font = Font(bold=True)
    if cargo_type.description:
        # A comment rather than a column: it is guidance for whoever fills the
        # form in, and it should not take horizontal space away from the numbers
        # or end up printed on every page.
        name.alignment = Alignment(vertical='center', wrap_text=True)

    values = [
        rate.rate if rate and rate.rate > 0 else None,
        rate.minimum if rate and rate.minimum > 0 else None,
    ]
    if air:
        values.append(rate.volumetric_divisor if rate and rate.volumetric_divisor > 0 else None)
    values += [
        rate.transit_days if rate else '',
        rate.notes if rate else '',
    ]

    for offset, value in enumerate(values, start=2):
        cell = sheet.cell(row=row, column=offset,
                          value=float(value) if isinstance(value, Decimal) else value)
        cell.fill = ENTRY_FILL
        cell.border = BORDER
        if isinstance(value, (int, float, Decimal)) or value is None:
            cell.alignment = Alignment(horizontal='right')
            if offset in (2, 3):
                cell.number_format = '#,##0.00'

    ref_column = len(columns_for(method))
    ref = sheet.cell(row=row, column=ref_column, value=_ref(destination, cargo_type))
    ref.font = Font(size=8, color='9AA5B1')
    ref.alignment = Alignment(horizontal='center')

    if banded:
        sheet.cell(row=row, column=1).fill = BAND_FILL


def _finish_sheet(sheet, column_count, last_row):
    """Freeze the header, and set the page up so it actually prints."""
    sheet.freeze_panes = sheet.cell(row=ROW_FIRST_RATE, column=1)

    for row in sheet.iter_rows(min_row=ROW_HEADER, max_row=last_row,
                               max_col=column_count):
        for cell in row:
            cell.border = BORDER

    # These four lines are the difference between a document a forwarder prints,
    # signs and scans back, and one that comes out across three pages with the
    # cargo type column orphaned on the last one.
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = f'{ROW_HEADER}:{ROW_HEADER}'
    sheet.print_area = f'A1:{get_column_letter(column_count)}{last_row}'


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------

class ImportReport:
    """
    What a returned sheet actually changed.

    An import that says "done" tells you nothing. This distinguishes rates that
    were created, rates that changed value, rows deliberately left blank, and
    rows that could not be matched at all - because only the last of those is a
    problem, and it is invisible in a total.
    """

    def __init__(self):
        self.created = []
        self.updated = []
        self.unchanged = 0
        self.skipped_blank = 0
        self.unmatched = []
        self.sheets_read = []

    @property
    def changed(self):
        return len(self.created) + len(self.updated)

    def summary(self):
        """One line for a toast message."""
        if not self.sheets_read:
            return 'No rate sheets were found in that file.'
        parts = []
        if self.created:
            parts.append(f'{len(self.created)} added')
        if self.updated:
            parts.append(f'{len(self.updated)} updated')
        if self.unchanged:
            parts.append(f'{self.unchanged} unchanged')
        if self.skipped_blank:
            parts.append(f'{self.skipped_blank} left blank')
        if not parts:
            parts.append('nothing to change')
        text = ', '.join(parts)
        if self.unmatched:
            text += f'. {len(self.unmatched)} row(s) could not be matched'
        return text


def apply_rate_request(company, method, uploaded_file):
    """
    Read a filled rate request back into ShippingRate rows.

    Args:
        company (ShippingCompany): whose rates these are.
        method (str): the method the sheet was issued for.
        uploaded_file: the .xlsx the forwarder returned.

    Returns:
        ImportReport: what changed.

    Rows are matched on the ref column, falling back to the destination in the
    sheet header plus the cargo type NAME. A blank rate leaves any existing rate
    untouched rather than deleting it: a forwarder who fills in one row of a
    sheet has quoted one lane, not withdrawn the rest.
    """
    workbook = load_workbook(uploaded_file, data_only=True)
    report = ImportReport()

    destinations = {d.code: d for d in ShippingDestination.objects.all()}
    cargo_by_slug = {c.slug: c for c in CargoType.objects.all()}
    cargo_by_name = {c.name.strip().lower(): c for c in CargoType.objects.all()}

    air = method == ShippingRate.METHOD_AIR
    column_count = len(columns_for(method))

    for sheet in workbook.worksheets:
        if sheet.title.strip().lower() == 'instructions':
            continue

        sheet_destination = _destination_from_header(sheet, destinations)
        read_any = False

        for row in sheet.iter_rows(min_row=ROW_FIRST_RATE, max_col=column_count,
                                   values_only=True):
            if row is None or not any(cell not in (None, '') for cell in row):
                continue

            destination, cargo_type = _match_row(
                row, column_count, sheet_destination, destinations,
                cargo_by_slug, cargo_by_name)

            if destination is None or cargo_type is None:
                label = str(row[0]).strip() if row and row[0] else '(blank)'
                report.unmatched.append(f'{sheet.title}: {label}')
                continue

            read_any = True
            rate_value = _decimal_or_none(row[1] if len(row) > 1 else None)

            if rate_value is None or rate_value <= 0:
                # Not quoted. Leaving the existing row alone is deliberate - see
                # the docstring.
                report.skipped_blank += 1
                continue

            minimum = _decimal_or_none(row[2] if len(row) > 2 else None) or Decimal('0')
            divisor = Decimal('0')
            next_index = 3
            if air:
                divisor = _decimal_or_none(row[3] if len(row) > 3 else None) or Decimal('0')
                next_index = 4
            transit = str(row[next_index] or '').strip()[:30] if len(row) > next_index else ''
            notes = str(row[next_index + 1] or '').strip()[:250] if len(row) > next_index + 1 else ''

            existing = ShippingRate.objects.filter(
                company=company, destination=destination,
                cargo_type=cargo_type, method=method).first()

            label = f'{destination.code} {cargo_type.name}'
            if existing is None:
                ShippingRate.objects.create(
                    company=company, destination=destination, cargo_type=cargo_type,
                    method=method, rate=rate_value, minimum=minimum,
                    volumetric_divisor=divisor, transit_days=transit, notes=notes)
                report.created.append(label)
            elif (existing.rate != rate_value or existing.minimum != minimum
                    or existing.volumetric_divisor != divisor
                    or existing.transit_days != transit or existing.notes != notes):
                was = existing.rate
                existing.rate = rate_value
                existing.minimum = minimum
                existing.volumetric_divisor = divisor
                existing.transit_days = transit
                existing.notes = notes
                existing.save()
                report.updated.append(f'{label}: {was} -> {rate_value}')
            else:
                report.unchanged += 1

        if read_any:
            report.sheets_read.append(sheet.title)

    return report


def _destination_from_header(sheet, destinations):
    """
    The country a sheet is for, read from 'Name (CODE)' in the header.

    Used when the ref column has been deleted, which happens.
    """
    value = sheet.cell(row=ROW_DESTINATION, column=2).value
    if not value:
        return None
    text = str(value)
    if '(' in text and ')' in text:
        code = text[text.rfind('(') + 1:text.rfind(')')].strip().upper()
        if code in destinations:
            return destinations[code]
    for destination in destinations.values():
        if destination.name.strip().lower() == text.strip().lower():
            return destination
    return None


def _match_row(row, column_count, sheet_destination, destinations,
               cargo_by_slug, cargo_by_name):
    """
    Work out which lane a row is, by ref first and printed name second.

    Returns:
        tuple: (ShippingDestination | None, CargoType | None)
    """
    ref_value = row[column_count - 1] if len(row) >= column_count else None
    code, slug = _parse_ref(ref_value)
    if code and slug and code in destinations and slug in cargo_by_slug:
        return destinations[code], cargo_by_slug[slug]

    # The ref was removed or overwritten. Fall back to the sheet's country and
    # the cargo type as printed.
    name = str(row[0]).strip().lower() if row and row[0] else ''
    return sheet_destination, cargo_by_name.get(name)
