"""
Freight quoting: what a shipment costs, and which company is cheapest.

WHY THIS IS A MODULE AND NOT A VIEW

The same arithmetic has to serve the customer calculator, the staff calculator
and (eventually) the order flow. Written inside a view it would be copied, and
copies of pricing drift — a quote that disagrees with the invoice is worse than
no quote at all.

Every function here is pure: values in, values out, no database writes and no
request object. That is what makes the freight rules testable without a server.

THE TWO RULES THAT DECIDE THE PRICE

AIR is charged on CHARGEABLE WEIGHT, which is the greater of what the shipment
actually weighs and what it "weighs" for the space it occupies:

    volumetric kg = (L × W × H in cm) ÷ divisor

The divisor is a carrier convention — 6000 is the IATA figure, and express
couriers commonly use 5000, which makes the same box more expensive. A pallet of
cushions is charged on volume; a pallet of tiles is charged on weight. Quoting
only actual weight is how a bulky-but-light shipment gets quoted at half its real
cost, and the difference is found at the airport.

SEA is charged on volume in cubic metres (CBM), with a minimum, because a
consolidator cannot sell a 0.2 CBM slot for a fifth of the price of a full one.

WHAT THE CUSTOMER IS TOLD

The customer sees ONE price: the cheapest. Which forwarder supplies it is not
shown to them — it is a supplier relationship, the same reasoning that keeps
1688 links off customer-facing pages. Staff see the full comparison.

WHERE THE RATES COME FROM

One ShippingRate row per lane — company, country, cargo type, method. Rates used
to be columns on ShippingCompany (air_rate, ksa_air_rate, nbb_ksa_air_rate…),
which cost a migration every time either list grew and could not express a third
country or a fifth cargo type at all. The eight original columns are still
mirrored for the order flow; see sync_legacy_rate_columns.
"""

from decimal import Decimal, ROUND_HALF_UP

CM3_PER_CBM = Decimal('1000000')
TWO_DP = Decimal('0.01')
THREE_DP = Decimal('0.001')


# The CompanySettings field holding the GLOBAL house rate for each of the eight
# lanes that predate the rate table.
#
# Spelled out rather than assembled from prefixes, because these names follow no
# pattern: the UAE rates are air_shipping_rate / sea_shipping_rate, the Saudi
# ones take a ksa_ prefix, and the battery ones are spelled out in full as
# no_brand_battery_*. Deriving them would mean encoding four exceptions, which
# is not a rule.
#
# Keyed by (country code, cargo slug, method). Only these eight exist - a new
# country or cargo type has no global fallback and never will, because the rate
# table is where rates belong now.
SETTINGS_RATE_FIELDS = {
    ('AE', 'general', 'air'): 'air_shipping_rate',
    ('AE', 'general', 'sea'): 'sea_shipping_rate',
    ('AE', 'non-branded-battery', 'air'): 'no_brand_battery_air_shipping_rate',
    ('AE', 'non-branded-battery', 'sea'): 'no_brand_battery_sea_shipping_rate',
    ('SA', 'general', 'air'): 'ksa_air_shipping_rate',
    ('SA', 'general', 'sea'): 'ksa_sea_shipping_rate',
    ('SA', 'non-branded-battery', 'air'): 'no_brand_battery_ksa_air_shipping_rate',
    ('SA', 'non-branded-battery', 'sea'): 'no_brand_battery_ksa_sea_shipping_rate',
}


def settings_rate_field(destination_code, cargo_slug, method):
    """
    The CompanySettings field holding the house rate for a lane, if any.

    Args:
        destination_code (str): e.g. 'AE'.
        cargo_slug (str): e.g. 'non-branded-battery'.
        method (str): 'air' or 'sea'.

    Returns:
        str: the field name, or '' when the lane has no global fallback.

    Getting this wrong is expensive and silent. An earlier version fell back to
    the standard air rate for EVERY cargo type, so a lane with no battery rate
    quoted dangerous goods at the general-cargo price - roughly half - and
    nothing anywhere reported a problem. The quote simply came out cheap, and
    stayed cheap until an airline invoice disagreed.
    """
    return SETTINGS_RATE_FIELDS.get((destination_code, cargo_slug, method), '')


def _dec(value, default='0'):
    """Anything into a Decimal, tolerating None and empty strings."""
    if value in (None, ''):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return Decimal(default)


def line_metrics(length_cm, width_cm, height_cm, weight_kg, quantity, divisor):
    """
    Weight and volume for one line of a shipment.

    Args:
        length_cm, width_cm, height_cm: carton dimensions in centimetres.
        weight_kg: weight of ONE carton.
        quantity: how many cartons.
        divisor (Decimal): volumetric divisor, e.g. 6000.

    Returns:
        dict: actual_kg, volumetric_kg, chargeable_kg, cbm.

    Chargeable weight is per LINE, not per carton, and the two are not the same
    once a line holds several cartons — rounding each carton up and then adding
    would overcharge on every line.
    """
    length = _dec(length_cm)
    width = _dec(width_cm)
    height = _dec(height_cm)
    weight = _dec(weight_kg)
    count = _dec(quantity, '1')
    if count <= 0:
        count = Decimal('1')

    per_carton_cm3 = length * width * height
    total_cm3 = per_carton_cm3 * count

    actual = (weight * count).quantize(THREE_DP, rounding=ROUND_HALF_UP)
    cbm = (total_cm3 / CM3_PER_CBM).quantize(THREE_DP, rounding=ROUND_HALF_UP)

    divisor = _dec(divisor, '6000')
    volumetric = Decimal('0')
    if divisor > 0:
        volumetric = (total_cm3 / divisor).quantize(THREE_DP, rounding=ROUND_HALF_UP)

    return {
        'actual_kg': actual,
        'volumetric_kg': volumetric,
        # The greater of the two. This IS the air freight rule.
        'chargeable_kg': max(actual, volumetric),
        'cbm': cbm,
    }


def shipment_totals(lines, divisor):
    """
    Add up every line of a shipment.

    Args:
        lines (iterable): dicts with length_cm, width_cm, height_cm, weight_kg,
            quantity.
        divisor (Decimal): volumetric divisor.

    Returns:
        dict: totals plus the per-line breakdown.

    Chargeable weight is summed per line rather than recomputed from shipment
    totals: a shipment of one dense carton and one bulky one is charged on the
    dense one's weight and the bulky one's volume, which averaging away would
    understate.
    """
    totals = {
        'actual_kg': Decimal('0'),
        'volumetric_kg': Decimal('0'),
        'chargeable_kg': Decimal('0'),
        'cbm': Decimal('0'),
        'cartons': 0,
        'lines': [],
    }
    for line in lines:
        metrics = line_metrics(
            line.get('length_cm'), line.get('width_cm'), line.get('height_cm'),
            line.get('weight_kg'), line.get('quantity'), divisor,
        )
        metrics['description'] = (line.get('description') or '').strip()[:120]
        metrics['quantity'] = int(_dec(line.get('quantity'), '1'))
        totals['lines'].append(metrics)
        for key in ('actual_kg', 'volumetric_kg', 'chargeable_kg', 'cbm'):
            totals[key] += metrics[key]
        totals['cartons'] += metrics['quantity']
    return totals


def divisor_for(rate_row=None, company=None, settings=None):
    """
    The volumetric divisor to price a lane by.

    Args:
        rate_row (ShippingRate | None): the lane's own value, if it has one.
        company (ShippingCompany | None): the forwarder's default.
        settings (CompanySettings | None): the global default.

    Returns:
        Decimal: e.g. 5000 or 6000, never zero.

    Falls back lane -> company -> global -> 6000, each level meaning "0 = ask the
    level above". Per-lane matters because a forwarder can price express air on
    5000 and consolidated air on 6000. The final 6000 is the IATA figure, there
    so that nothing ever divides by zero.
    """
    value = _dec(getattr(rate_row, 'volumetric_divisor', 0)) if rate_row is not None else Decimal('0')
    if value <= 0 and company is not None:
        value = _dec(getattr(company, 'volumetric_divisor', 0))
    if value <= 0 and settings is not None:
        value = _dec(getattr(settings, 'volumetric_divisor', 0))
    if value <= 0:
        value = Decimal('6000')
    return value


def quote_for_rate(rate_row, lines, settings=None):
    """
    What one forwarder would charge for this shipment on one lane.

    Args:
        rate_row (ShippingRate): the forwarder's rate for this exact lane -
            country, cargo type and method are all already decided by which row
            this is.
        lines (iterable): the shipment lines, as taken by shipment_totals.
        settings (CompanySettings | None): supplies the global fallbacks.

    Returns:
        dict | None: the quote, or None when the row carries no usable rate.

    Takes LINES rather than pre-computed totals because the divisor varies by
    lane: a forwarder on 5000 and one on 6000 bill different chargeable weights
    for the identical carton, so computing the weight once outside this function
    would price every company on whichever divisor happened to be passed in.
    """
    if rate_row is None:
        return None

    rate = _dec(getattr(rate_row, 'rate', 0))
    if rate <= 0:
        # A row with no rate is not a free shipment, it is an absent quote.
        return None

    company = getattr(rate_row, 'company', None)
    method = getattr(rate_row, 'method', 'air')

    divisor = divisor_for(rate_row, company, settings)
    totals = shipment_totals(lines, divisor)

    # The lane's own minimum first, then the company's, then the global. The
    # company and global fields are still named per method, which is why this
    # picks a different attribute name at each level rather than one.
    lane_minimum = _dec(getattr(rate_row, 'minimum', 0))

    if method == 'air':
        billable = totals['chargeable_kg']
        minimum = lane_minimum
        if minimum <= 0 and company is not None:
            minimum = _dec(getattr(company, 'min_chargeable_kg', 0))
        if minimum <= 0 and settings is not None:
            minimum = _dec(getattr(settings, 'min_chargeable_kg', 0))
        billed = max(billable, minimum)
        unit = 'kg'
    else:
        billable = totals['cbm']
        minimum = lane_minimum
        if minimum <= 0 and company is not None:
            minimum = _dec(getattr(company, 'min_cbm', 0))
        if minimum <= 0 and settings is not None:
            minimum = _dec(getattr(settings, 'min_cbm', 0))
        billed = max(billable, minimum)
        unit = 'CBM'

    cost = (billed * rate).quantize(TWO_DP, rounding=ROUND_HALF_UP)

    return {
        'company': company,
        'company_name': getattr(company, 'name', 'House rate'),
        'transit_days': getattr(rate_row, 'transit_days', ''),
        'rate': rate.quantize(TWO_DP),
        'unit': unit,
        'method': method,
        'divisor': divisor,
        'totals': totals,
        'actual_kg': totals['actual_kg'],
        'volumetric_kg': totals['volumetric_kg'],
        'cbm': totals['cbm'],
        'billable': billable,
        'billed': billed,
        # True when the shipment is under the minimum and is being charged up to
        # it. Saying so turns a surprising price into an explicable one.
        'minimum_applied': billed > billable,
        'minimum': minimum,
        # True when volume, not weight, is what the customer is paying for. It is
        # the single most useful thing to tell them: it means repacking into a
        # smaller carton reduces the bill, which weight-based pricing would not.
        'volumetric_applied': method == 'air' and totals['volumetric_kg'] > totals['actual_kg'],
        'cost': cost,
    }


def best_quote(rate_rows, lines, settings=None):
    """
    Every rate that prices this lane, cheapest first.

    Args:
        rate_rows (iterable): ShippingRate rows for ONE lane. Selecting the lane
            is the caller's job - see lane_rates below.
        lines (iterable): the shipment lines.
        settings (CompanySettings | None).

    Returns:
        list[dict]: quotes sorted by cost. Empty when nobody prices the lane.

    Sorted rather than reduced to a single winner so the caller can decide how
    much to reveal: the customer is shown the cheapest, staff see the whole
    comparison.
    """
    quotes = []
    for rate_row in rate_rows:
        quote = quote_for_rate(rate_row, lines, settings)
        if quote is not None:
            quotes.append(quote)
    quotes.sort(key=lambda q: q['cost'])
    return quotes


def lane_rates(destination_code, cargo_slug, method):
    """
    Every forwarder's rate for one lane.

    Args:
        destination_code (str): e.g. 'AE'.
        cargo_slug (str): e.g. 'non-branded-battery'.
        method (str): 'air' or 'sea'.

    Returns:
        QuerySet: ShippingRate rows with company loaded.

    The one database query the calculator makes. select_related('company') is
    not an optimisation here but a correctness requirement of quote_for_rate,
    which reads the company's divisor and minimums as the middle fallback.
    """
    from .models import ShippingRate

    return (ShippingRate.objects
            .filter(destination__code=destination_code,
                    destination__is_active=True,
                    cargo_type__slug=cargo_slug,
                    method=method,
                    rate__gt=0)
            .select_related('company', 'destination', 'cargo_type'))


def house_rate_row(settings, destination_code, cargo_slug, method):
    """
    The global CompanySettings rate for a lane, as a stand-in ShippingRate.

    Args:
        settings (CompanySettings): holds the eight global rates.
        destination_code (str), cargo_slug (str), method (str).

    Returns:
        SimpleNamespace | None: something quote_for_rate can price, or None.

    Before the rate table existed, a company with a rate of 0 fell through to a
    global default, so a site with no per-company rates entered still quoted.
    Dropping that would have turned the calculator silent for anyone who had
    never filled in a forwarder. This keeps the safety net without putting a
    fake company in the comparison - and since customers are never shown which
    forwarder won, a house rate is indistinguishable to them anyway.

    Only the original eight lanes have a global. A new country or cargo type
    returns None, which is correct: nobody has ever quoted it.
    """
    from types import SimpleNamespace

    if settings is None:
        return None
    field = settings_rate_field(destination_code, cargo_slug, method)
    if not field:
        return None
    rate = _dec(getattr(settings, field, 0))
    if rate <= 0:
        return None
    return SimpleNamespace(
        rate=rate, method=method, minimum=Decimal('0'),
        volumetric_divisor=Decimal('0'), transit_days='', company=None,
    )
