"""
Product feeds for Meta (Facebook/Instagram) and TikTok catalogue ads.

WHAT THIS IS FOR

A pixel tells Meta what a visitor DID. A feed tells Meta what you SELL. You need
both before you can run the ads that actually pay: dynamic product ads, which
show a person the specific item they looked at and did not buy, and catalogue
ads, which let Meta pick which of your products to show which audience. Without
a feed those campaign types simply cannot be created — the ad manager asks for a
catalogue and there is nothing to point it at.

Meta and TikTok both poll a URL on a schedule (hourly to daily) and rebuild the
catalogue from whatever it returns. So this is a live view over the catalogue,
not an export somebody has to remember to re-upload.

TWO FORMATS, SAME DATA
  CSV  - what Meta Commerce Manager expects by default, and the easier one to
         eyeball when a product is rejected.
  XML  - RSS 2.0 with Google's namespace. TikTok and Google Merchant Center both
         read it, and Meta accepts it too.

WHAT IS DELIBERATELY NOT IN HERE

`source_url` — the supplier's 1688/Alibaba listing. That field is the agency's
entire margin: anyone who has it can go straight to the factory. It appears on
staff screens only, and a feed is a public URL that Meta, TikTok and anyone who
guesses the address can read. It must never be emitted here, and there is a test
that fails if it ever is.

Private products are excluded for the same reason they are excluded from the
storefront: they are negotiated or customer-exclusive, and a competitor holding
the feed URL should not learn they exist.
"""

import csv
from decimal import Decimal
from xml.sax.saxutils import escape as xml_escape

from django.http import HttpResponse
from django.utils.text import Truncator

from settings_manager.models import CompanySettings

from .models import Product

# Meta rejects a title over 200 characters and truncates descriptions well
# before their documented 9,999, so both are cut here rather than server-side by
# Meta, where the cut lands mid-word.
MAX_TITLE = 200
MAX_DESCRIPTION = 5000

# Meta's vocabulary, not ours. These are the literal strings the spec accepts.
CONDITION_NEW = 'new'
IN_STOCK = 'in stock'
OUT_OF_STOCK = 'out of stock'

FEED_COLUMNS = [
    # --- required by Meta ---
    'id',
    'title',
    'description',
    'availability',
    'condition',
    'price',
    'link',
    'image_link',
    'brand',
    # --- strongly recommended: these are what let Meta target well ---
    'additional_image_link',
    'item_group_id',
    'product_type',
    'quantity_to_sell_on_facebook',
    'custom_label_0',
    'custom_label_1',
]


def _site_url(settings):
    """
    The public origin, with no trailing slash.

    Read from CompanySettings rather than the request, because a feed is fetched
    by Meta's crawler and whatever Host header that arrives with should not
    decide the links in the catalogue. If it is misconfigured the links are
    wrong everywhere at once, which is noticed; if it followed the request, one
    crawler hitting an unexpected hostname would silently poison a subset.
    """
    return (settings.site_url or 'https://mudassirllc.com').rstrip('/')


def _absolute(site, path):
    """Join the origin to a path that may already be absolute."""
    if not path:
        return ''
    if path.startswith('http://') or path.startswith('https://'):
        return path
    return f'{site}{path if path.startswith("/") else "/" + path}'


def _money(amount, currency):
    """
    Meta's price format: the number, a space, then the ISO currency code.

    '25.00 AED'. Not a symbol, not a comma separator — the spec is strict and a
    malformed price is the single most common reason a whole feed is rejected.
    """
    try:
        value = Decimal(str(amount or 0)).quantize(Decimal('0.01'))
    except (TypeError, ValueError):
        value = Decimal('0.00')
    return f'{value} {currency}'


def _describe(product, settings):
    """
    Build a description, because Product has no description field.

    Meta requires a non-empty description and penalises one that merely repeats
    the title, so this assembles the facts the catalogue actually holds: what it
    is, the category it sits in, the minimum order, and any specifications the
    importer captured. That is genuinely more useful to a buyer than a sentence
    of marketing copy would be, and it stays true as the product data changes.
    """
    parts = []

    where = product.subcategory.name if product.subcategory_id else (
        product.category.name if product.category_id else '')
    if where:
        parts.append(f'{product.name} — {where}.')
    else:
        parts.append(f'{product.name}.')

    # Specifications, when the importer captured any. Capped because a 1688
    # listing can carry forty rows and the first few are the informative ones.
    specs = [f'{a.name}: {a.value}' for a in list(product.attributes.all())[:8]
             if a.name and a.value]
    if specs:
        parts.append(' '.join(specs) + '.')

    if product.moq:
        parts.append(f'Minimum order {product.moq} pieces.')
    if product.ready_to_ship:
        parts.append('Ready to ship.')

    parts.append(
        f'Sourced and shipped from China by {settings.company_name}. '
        f'Factory-direct pricing with supplier verification and quality inspection.'
    )

    return Truncator(' '.join(parts)).chars(MAX_DESCRIPTION)


def _rows_for(product, site, settings, currency):
    """
    One feed row per purchasable thing.

    A product WITH variations yields one row per variation, all sharing an
    `item_group_id`. That is what the spec is for: the customer buys a specific
    colour at a specific price, so that is what the ad must show and link to.
    Collapsing them to a single parent row is why dynamic ads so often show a
    price the visitor never saw.

    A product with no variations yields one row.
    """
    images = product.displayable_images
    if not images:
        # Meta rejects any item without an image, so emitting one costs a
        # rejection in Commerce Manager and teaches nobody anything. Skipped
        # here, and counted by the diagnostics view so the gap is visible.
        return []

    link = _absolute(site, product.get_absolute_url())
    primary = _absolute(site, images[0].src)
    extra = ','.join(_absolute(site, img.src) for img in images[1:4])

    product_type = ' > '.join(filter(None, [
        product.category.name if product.category_id else '',
        product.subcategory.name if product.subcategory_id else '',
    ]))

    base = {
        'description': _describe(product, settings),
        'condition': CONDITION_NEW,
        'link': link,
        'brand': settings.company_name,
        'additional_image_link': extra,
        'product_type': product_type,
        # Marketplace and readiness, exposed as custom labels so campaigns can
        # be split on them — "only advertise what we can ship today" is a rule
        # you can only write if the feed carries it.
        'custom_label_0': product.get_source_display() if product.source else '',
        'custom_label_1': 'ready-to-ship' if product.ready_to_ship else 'made-to-order',
    }

    variants = product.active_variants
    if not variants:
        return [dict(base, **{
            'id': product.sku or f'MLK-{product.pk}',
            'title': Truncator(product.name).chars(MAX_TITLE),
            'availability': IN_STOCK,
            'price': _money(product.price, currency),
            'image_link': primary,
            'item_group_id': '',
            'quantity_to_sell_on_facebook': '',
        })]

    rows = []
    group = product.sku or f'MLK-{product.pk}'
    for variant in variants:
        # The variation's own photo when it has one. A blue-bottle ad that
        # links to a blue bottle and shows a red one is worse than no ad.
        image = _absolute(site, variant.src) or primary
        rows.append(dict(base, **{
            'id': variant.sku or f'{group}-V{variant.pk}',
            'title': Truncator(f'{product.name} — {variant.name}').chars(MAX_TITLE),
            # stock is nullable and means "not tracked", which is not the same
            # as zero. Only an explicit 0 marks something out of stock.
            'availability': OUT_OF_STOCK if variant.stock == 0 else IN_STOCK,
            'price': _money(variant.price, currency),
            'image_link': image,
            'item_group_id': group,
            'quantity_to_sell_on_facebook': '' if variant.stock is None else variant.stock,
        }))
    return rows


def feed_queryset():
    """
    Exactly what may appear in a public catalogue.

    Public, published, and priced. Shared by both formats and by the
    diagnostics view so all three can never disagree about what is being
    advertised.
    """
    return (
        Product.objects
        .filter(is_private=False, is_draft=False)
        .exclude(price__isnull=True)
        .prefetch_related('images', 'variants', 'attributes')
        .select_related('category', 'subcategory')
        .order_by('id')
    )


def build_rows():
    """Every feed row for the current catalogue, plus what was skipped."""
    settings = CompanySettings.get_settings()
    site = _site_url(settings)
    currency = settings.currency or 'AED'

    rows = []
    skipped_no_image = 0
    for product in feed_queryset():
        product_rows = _rows_for(product, site, settings, currency)
        if not product_rows:
            skipped_no_image += 1
        rows.extend(product_rows)
    return rows, skipped_no_image


def product_feed_csv(request):
    """
    The catalogue as CSV, in Meta's column vocabulary.

    Args:
        request (HttpRequest): Unauthenticated — Meta's crawler holds no session.

    Returns:
        HttpResponse: text/csv.

    Public on purpose. Meta and TikTok fetch this from their own infrastructure
    with no credentials, so a login wall means an empty catalogue. Everything in
    it is already on the public storefront; the private and draft products, and
    the supplier links, are filtered out in feed_queryset and _rows_for.
    """
    rows, _skipped = build_rows()

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'inline; filename="products.csv"'
    # Meta re-fetches on its own schedule; a short cache stops a burst of
    # crawler requests rebuilding the whole catalogue each time.
    response['Cache-Control'] = 'public, max-age=1800'

    writer = csv.DictWriter(response, fieldnames=FEED_COLUMNS,
                            extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return response


def product_feed_xml(request):
    """
    The catalogue as RSS 2.0 with Google's namespace.

    Args:
        request (HttpRequest): Unauthenticated, as above.

    Returns:
        HttpResponse: application/xml.

    TikTok and Google Merchant Center both read this shape, and Meta accepts it,
    so one URL covers every network you are likely to add next.
    """
    settings = CompanySettings.get_settings()
    site = _site_url(settings)
    rows, _skipped = build_rows()

    # Built as strings rather than through a DOM: the document is flat, and
    # every value goes through xml_escape on the way in.
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">',
        '<channel>',
        f'<title>{xml_escape(settings.company_name)}</title>',
        f'<link>{xml_escape(site)}</link>',
        '<description>Factory-direct products sourced from China.</description>',
    ]

    # These carry the g: prefix in RSS; the rest are emitted as-is.
    for row in rows:
        out.append('<item>')
        for column in FEED_COLUMNS:
            value = row.get(column, '')
            if value == '' or value is None:
                continue
            tag = f'g:{column}'
            out.append(f'<{tag}>{xml_escape(str(value))}</{tag}>')
        out.append('</item>')

    out.extend(['</channel>', '</rss>'])

    response = HttpResponse('\n'.join(out), content_type='application/xml; charset=utf-8')
    response['Cache-Control'] = 'public, max-age=1800'
    return response
