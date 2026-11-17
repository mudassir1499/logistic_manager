"""
products/api.py

JSON endpoints for the 1688 product-sourcing browser extension.

The extension runs on 1688.com pages, so every request here is cross-origin and
cookie-less. Three things follow from that and shape this whole module:

  1. **Bearer-token auth, not sessions.** See ``accounts.decorators``.
  2. **CSRF exempt.** CSRF protection defends cookie-authenticated requests; a
     bearer token is never attached automatically by the browser, so there is
     nothing for a hostile page to forge. Leaving CSRF on would simply break
     every call.
  3. **CORS preflight handling.** Sending ``Authorization`` and a JSON content
     type makes the request non-simple, so the browser sends an OPTIONS
     preflight first.

Endpoints:
    POST /products/api/extension/ping/     — validate a token, return the taxonomy
    POST /products/api/extension/extract/  — server-side Claude extraction
    POST /products/api/extension/import/   — create products from the collected list
"""

import base64
import binascii
import io
import ipaddress
import json
import logging
import re
import socket
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from accounts.decorators import api_token_required
from settings_manager.models import CompanySettings

from .categorization import classify
from .models import (Category, Product, ProductAttribute, ProductImage,
                     ProductVariant, SubCategory)
from .source_url import canonical_source_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IMAGE DOWNLOAD SAFETY
# ---------------------------------------------------------------------------
# The import endpoint fetches product images from URLs supplied by the client.
# That is a server-side request forgery primitive if left unguarded: a holder of
# a valid token could point it at http://169.254.169.254/ (cloud metadata) or at
# an internal admin service and use this server as a proxy into the private
# network.
#
# Two independent guards, because either alone is defeatable:
#   - a host allowlist, so only marketplace CDNs are reachable at all; and
#   - a resolved-IP check, so a permitted-looking hostname that resolves to a
#     private address (DNS rebinding) is still refused.

ALLOWED_IMAGE_HOST_SUFFIXES = (
    'alicdn.com',       # 1688 / Taobao / Alibaba image CDN
    'aliimg.com',
    'alibaba.com',
    'taobaocdn.com',
    'tbcdn.cn',
    'mmstatic.com',
)

# 1688 product photos are well under this. The cap stops a malicious or
# mistaken URL from streaming gigabytes into memory.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

MAX_IMAGES_PER_PRODUCT = 3          # matches the limit the manual product form enforces
MAX_PRODUCTS_PER_IMPORT = 200       # one extension session's list; keeps the request bounded


def _host_is_allowed(hostname):
    """True when ``hostname`` is, or is a subdomain of, an allowlisted CDN."""
    host = (hostname or '').lower().rstrip('.')
    return any(
        host == suffix or host.endswith('.' + suffix)
        for suffix in ALLOWED_IMAGE_HOST_SUFFIXES
    )


def _resolves_to_public_ip(hostname):
    """
    True when every address ``hostname`` resolves to is publicly routable.

    Checks *all* returned addresses, not just the first: a host that resolves to
    both a public and a private address would otherwise slip through depending
    on resolver ordering.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _decode_image_payload(entry, label):
    """
    Decode and validate one image the client sent as bytes.

    Args:
        entry (dict): ``{'filename': str, 'content_base64': str, ...}``
        label (str): Product name, used only to make a rejection log line
            traceable to the product it came from.

    Returns:
        tuple[bytes, str] | None: (image bytes, file extension), or None when the
        entry is not a usable image.

    VALIDATION, AND WHY IT IS NOT OPTIONAL

    The URL path is protected by a host allowlist and a resolved-IP check
    because the SERVER does the fetching. Here the client supplies the bytes, so
    that whole defence is irrelevant and a different one is needed: nothing
    stops a token holder posting a 300 MB blob, or an HTML file named .jpg that
    a browser would later render as a page on this domain.

    So each image must decode as base64, be within the size cap, and be
    something Pillow recognises as an actual image - the last of which is what
    stops a script being stored with an image extension.

    This lives on its own because BOTH the product gallery and the variation
    photos now arrive as bytes, and they must be judged by identical rules. A
    variation image is rendered in an <img src> on customer pages exactly like a
    gallery one, so a second, drifting copy of this check would be a hole.
    """
    if not isinstance(entry, dict):
        return None

    raw = entry.get('content_base64') or ''
    # A data: URL prefix is easy to send by accident; strip it rather than
    # failing on it.
    if ',' in raw[:64] and raw.lstrip().startswith('data:'):
        raw = raw.split(',', 1)[1]

    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None

    if not data or len(data) > MAX_IMAGE_BYTES:
        return None

    # Confirm the bytes really are an image, and one of the formats this
    # catalogue serves.
    #
    # Image.open() parses the header and raises for anything no decoder
    # recognises, which is what stops an HTML file arriving named .jpg and
    # later being served from this domain. verify() is deliberately NOT used
    # instead: it validates chunk checksums, making it stricter than both
    # Django's own ImageField and every browser, so a real supplier photo
    # with one imperfect chunk would be refused here and accepted everywhere
    # else. The goal is to exclude non-images, not to grade image quality.
    try:
        from PIL import Image
        probe = Image.open(io.BytesIO(data))
        image_format = (probe.format or '').upper()
    except Exception:
        logger.info('Rejected an uploaded image for %r: not a decodable image', label)
        return None

    if image_format not in ('JPEG', 'PNG', 'WEBP', 'GIF'):
        logger.info('Rejected an uploaded image for %r: format %s', label, image_format)
        return None

    extension = (entry.get('filename') or '').rsplit('.', 1)[-1].lower()
    if extension not in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
        extension = 'jpg'

    return data, extension


def _save_uploaded_images(product, name, images):
    """
    Save gallery images the client sent as bytes, rather than as URLs to fetch.

    Args:
        product (Product): The product to attach them to.
        name (str): The product name, used to build a readable filename.
        images (list): [{'filename': str, 'content_base64': str}, ...]

    Returns:
        tuple[int, int]: (saved, rejected).
    """
    saved = 0
    rejected = 0

    for entry in images[:MAX_IMAGES_PER_PRODUCT]:
        decoded = _decode_image_payload(entry, name)
        if decoded is None:
            rejected += 1
            continue
        data, extension = decoded

        safe_name = re.sub(r'[^\w\-]', '_', name)[:50] or 'product'
        ProductImage.objects.create(
            product=product,
            image=ContentFile(data, name=f'{safe_name}_{saved + 1}.{extension}'),
            # The CDN address is recorded even though the bytes are already
            # stored locally. It is never SERVED while `image` is set - src
            # prefers the local file - it is kept so the original can be
            # re-fetched if this file is ever lost, and so a product's photos
            # can be traced back to the listing they came from.
            source_url=(entry.get('source_url') or '')[:500],
        )
        saved += 1

    return saved, rejected


def _fetch_image(url):
    """
    Download a product image, or return None if it is not safe or not reachable.

    Returns:
        tuple[bytes, str] | None: (image bytes, file extension) on success.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None

    if parsed.scheme not in ('http', 'https'):
        return None
    if not _host_is_allowed(parsed.hostname):
        logger.info('Refusing image from non-allowlisted host: %s', parsed.hostname)
        return None
    if not _resolves_to_public_ip(parsed.hostname):
        logger.warning('Refusing image from host resolving to a private address: %s',
                       parsed.hostname)
        return None

    try:
        request = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; logistic-manager/1.0)'},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            # Read one byte past the cap so an oversized body is detected rather
            # than silently truncated into a corrupt image.
            data = response.read(MAX_IMAGE_BYTES + 1)
    except Exception as exc:
        logger.info('Image download failed for %s: %s', url, exc)
        return None

    if not data or len(data) > MAX_IMAGE_BYTES:
        return None

    extension = urllib.parse.urlparse(url).path.rsplit('.', 1)[-1].lower()
    if extension not in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
        extension = 'jpg'
    return data, extension


# ---------------------------------------------------------------------------
# REQUEST PLUMBING
# ---------------------------------------------------------------------------

def _cors(view_func):
    """
    Answer CORS preflights and tag responses so the extension can read them.

    ``Access-Control-Allow-Origin: *`` is safe here precisely because these
    endpoints do not use cookies: a hostile page that copied a request would
    still need the bearer token, which the browser never attaches on its own.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method == 'OPTIONS':
            response = JsonResponse({})
        else:
            response = view_func(request, *args, **kwargs)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response['Access-Control-Max-Age'] = '86400'
        return response
    return wrapper


def _json_body(request):
    """Parse a JSON request body, returning {} rather than raising on garbage."""
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return {}


def _taxonomy():
    """
    The catalogue's categories and subcategories, shaped for the extension.

    Used twice: the extension renders it as dropdowns, and the AI prompt lists
    it so the model can only pick a slug that actually exists.
    """
    return [
        {
            'slug': category.slug,
            'name': category.name,
            'subcategories': [
                {'slug': sub.slug, 'name': sub.name}
                for sub in category.subcategories.filter(is_active=True)
            ],
        }
        for category in Category.objects.filter(is_active=True).prefetch_related('subcategories')
    ]


# ---------------------------------------------------------------------------
# ENDPOINTS
# ---------------------------------------------------------------------------

@csrf_exempt
@_cors
@api_token_required('products')
def extension_ping(request):
    """
    Confirm a token works and hand the extension everything it needs to render.

    The extension calls this when the user saves their settings, so a wrong URL
    or a revoked token is reported at configuration time rather than silently
    failing later on a product page.
    """
    settings = CompanySettings.get_settings()
    return JsonResponse({
        'success': True,
        'user': request.user.get_username(),
        'site_currency': settings.currency,
        'taxonomy': _taxonomy(),
        'product_count': Product.objects.count(),
    })


@csrf_exempt
@_cors
@api_token_required('products')
def extension_extract(request):
    """
    Run server-side Claude extraction on a scraped page.

    This is the extension's 'server' AI mode. It exists so the Anthropic API key
    stays in the server's .env instead of being shipped inside an extension that
    anyone can unpack.

    Body: ``{"page": {"url", "title", "text", "price_text", "spec_text"}}``
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST required'}, status=405)

    page = _json_body(request).get('page') or {}
    if not page.get('text') and not page.get('title'):
        return JsonResponse(
            {'success': False, 'message': 'No page content supplied.'}, status=400
        )

    # Imported lazily so that a deployment which never uses the server AI mode
    # does not need the anthropic package installed at all.
    from utils.llm import LLMExtractionError, LLMNotConfigured, extract_product

    try:
        data = extract_product(page, _taxonomy())
    except LLMNotConfigured as exc:
        # 503, not 500: the server is working, the feature just is not set up.
        return JsonResponse({'success': False, 'error': 'not_configured',
                             'message': str(exc)}, status=503)
    except LLMExtractionError as exc:
        return JsonResponse({'success': False, 'error': 'extraction_failed',
                             'message': str(exc)}, status=502)

    return JsonResponse({'success': True, 'result': data})


def _resolve_category(category_slug, subcategory_slug, product_name):
    """
    Turn the slugs the extension sent into Category/SubCategory rows.

    Falls back to the keyword rules in ``products.categorization`` when the
    extension supplied nothing usable, so an imported product is never left
    uncategorised and invisible to the portal's category filters.
    """
    category = None
    subcategory = None

    if subcategory_slug:
        subcategory = (
            SubCategory.objects.select_related('category')
            .filter(slug=subcategory_slug, is_active=True)
            .first()
        )
        if subcategory:
            return subcategory.category, subcategory

    if category_slug:
        category = Category.objects.filter(slug=category_slug, is_active=True).first()
        if category:
            return category, None

    match = classify(product_name or '')
    if match is None:
        return None, None

    cat_slug, sub_slug = match
    category = Category.objects.filter(slug=cat_slug).first()
    if category is None:
        return None, None
    if sub_slug:
        subcategory = SubCategory.objects.filter(category=category, slug=sub_slug).first()
    return category, subcategory


@csrf_exempt
@_cors
@api_token_required('products')
def extension_create_category(request):
    """
    Create a category, or a subcategory under an existing one.

    Sourcing runs into products the catalogue has no home for, and the only fix
    used to be: leave the 1688 page, open the site, add the category, come back,
    re-scan. In practice that meant products were filed under a near-enough
    category or left uncategorised, because nobody does that mid-flow.

    Body::

        {"name": "Garden Tools"}                        -> a top-level category
        {"name": "Pruners", "parent": "garden-tools"}   -> a subcategory of it

    Returns the full refreshed taxonomy so the panel can repopulate both dropdowns
    from one response, and the slug of whatever was created so it can be selected.

    Creating taxonomy is a heavier action than importing a product, so it is
    guarded the same way everything else here is — the token must belong to
    someone with the products module — and an existing name is returned rather
    than duplicated, which makes the call idempotent and stops a double-click
    producing "Garden Tools" twice.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST required'}, status=405)

    body = _json_body(request)
    name = (body.get('name') or '').strip()[:120]
    parent_slug = (body.get('parent') or '').strip()

    if not name:
        return JsonResponse({'success': False, 'message': 'A name is required.'}, status=400)

    if parent_slug:
        parent = Category.objects.filter(slug=parent_slug).first()
        if parent is None:
            return JsonResponse(
                {'success': False, 'message': f'No category with slug "{parent_slug}".'},
                status=400,
            )
        existing = parent.subcategories.filter(name__iexact=name).first()
        obj = existing or SubCategory.objects.create(
            category=parent, name=name, ordering=parent.subcategories.count()
        )
        created_kind = 'subcategory'
    else:
        existing = Category.objects.filter(name__iexact=name).first()
        obj = existing or Category.objects.create(
            name=name, ordering=Category.objects.count()
        )
        created_kind = 'category'

    return JsonResponse({
        'success': True,
        'kind': created_kind,
        'slug': obj.slug,
        'name': obj.name,
        # True when it already existed — the panel says "already there" rather
        # than implying it just made something.
        'existed': bool(existing),
        'parent': parent_slug or None,
        'taxonomy': _taxonomy(),
    })


MAX_VARIANTS_PER_PRODUCT = 100      # a 1688 listing with more than this is a catalogue, not a product
MAX_ATTRIBUTES_PER_PRODUCT = 60     # the sample listing has 20; 60 is a typo guard, not a limit anyone meets


def _create_attributes(product, raw_attributes):
    """
    Store the listing's specification table against ``product``.

    1688 pages carry a spec table (货号, 材质, 功率 …) that the extension already
    read in order to find the weight and MOQ, but then discarded. Those lines are
    the difference between a catalogue entry that is a name and a price and one
    that describes the thing — and they are what the public product page renders
    as Specifications and emits as schema.org ``additionalProperty``.

    Args:
        product (Product): The freshly created product.
        raw_attributes (list[dict]): ``{name, value}`` pairs, already translated
            by the extension where translation is switched on.

    Returns:
        int: How many attributes were stored.

    Order is preserved from the page, because a spec sheet is written in a
    deliberate order and alphabetising it would put "Warranty" above "Model".
    """
    rows = []
    seen = set()
    for raw in raw_attributes[:MAX_ATTRIBUTES_PER_PRODUCT]:
        if not isinstance(raw, dict):
            continue
        name = (raw.get('name') or '').strip()[:100]
        value = (raw.get('value') or '').strip()[:500]
        if not name or not value:
            continue
        # 1688 tables occasionally repeat a label. Keeping the first occurrence
        # avoids a product showing "Material" twice with different values.
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append(ProductAttribute(
            product=product, name=name, value=value, sort_order=len(rows)
        ))

    if rows:
        ProductAttribute.objects.bulk_create(rows)
    return len(rows)


def _create_variants(product, raw_variants):
    """
    Attach the listing's variations to ``product``.

    A 1688 listing usually sells many SKUs under one page — colours, kit sizes,
    section counts — each with its own price, stock and photo. These used to be
    imported as separate top-level products, which turned one listing into
    seventeen catalogue cards for the same item. They are now rows under the one
    product.

    Args:
        product (Product): The freshly created parent.
        raw_variants (list[dict]): ``{name, price, stock, sku, image_url, image}``
            each, where ``image`` is an optional ``{filename, content_base64}``
            the extension already downloaded.

    Returns:
        tuple[int, int]: (variants created, variation photos stored locally).

    Rows with no usable name or no positive price are skipped rather than failing
    the product: a listing where two of fifteen variations scraped badly should
    still import the other thirteen.

    WHY VARIATION PHOTOS ARE STORED, NOT LINKED

    These used to be kept as ``image_url`` only - a hotlink to alicdn - while the
    gallery photos were downloaded. That was backwards for the listings it
    mattered on: a page with seventeen SKUs contributes three gallery photos and
    seventeen variation photos, so on a variation-heavy product almost every
    picture in the catalogue was a link to someone else's CDN. Selecting a
    variation swaps it into the main image slot on the product page, so those are
    not thumbnails that degrade quietly either - they are the product shot.

    Hotlinks rot in ways a local file cannot: the supplier delists the offer, or
    the CDN turns on referer checking, and the catalogue fills with broken frames
    months after the import looked like it worked.

    ``image_url`` is still stored alongside, exactly as the gallery path keeps
    its ``source_url``: it is what ``fetch_remote_images`` retries from when the
    bytes did not arrive.
    """
    variants = []
    images_saved = 0

    for position, raw in enumerate(raw_variants[:MAX_VARIANTS_PER_PRODUCT]):
        if not isinstance(raw, dict):
            continue

        variant_name = (raw.get('name') or '').strip()[:255]
        if not variant_name:
            continue

        try:
            variant_price = Decimal(str(raw.get('price')))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if variant_price <= 0:
            continue

        try:
            stock = int(raw.get('stock'))
            if stock < 0:
                stock = None
        except (TypeError, ValueError):
            stock = None

        # Only allowlisted CDN links are stored: this is rendered as an <img src>
        # on customer-facing pages. Same rule as ProductImage.source_url.
        image_url = (raw.get('image_url') or '').strip()
        if image_url and not _host_is_allowed(urllib.parse.urlparse(image_url).hostname):
            image_url = ''

        variant = ProductVariant(
            product=product,
            name=variant_name,
            price=variant_price,
            stock=stock,
            sku=(raw.get('sku') or '').strip()[:100],
            image_url=image_url[:500],
            sort_order=position,
        )

        # The photo, when the extension managed to fetch it. Judged by exactly
        # the same rules as a gallery image - see _decode_image_payload.
        decoded = _decode_image_payload(raw.get('image'), product.name)
        if decoded is not None:
            data, extension = decoded
            safe_name = re.sub(r'[^\w\-]', '_', product.name)[:40] or 'product'
            # Assigned, not saved: bulk_create below runs FileField.pre_save on
            # every row, which commits an uncommitted file to storage. Verified
            # against Django 4.2. Doing it the other way round is not an option -
            # bulk_create does not populate primary keys on MySQL, so there is no
            # saved row to attach a file to afterwards.
            variant.image = ContentFile(
                data, name=f'{safe_name}_v{position + 1}.{extension}'
            )
            images_saved += 1

        variants.append(variant)

    if variants:
        ProductVariant.objects.bulk_create(variants)
    return len(variants), images_saved


@csrf_exempt
@_cors
@api_token_required('products')
def extension_import(request):
    """
    Create products from the list the extension collected.

    Body::

        {"products": [
            {"name", "price", "moq", "weight", "carton_qty", "sku", "source",
             "category_slug", "subcategory_slug", "image_urls": [...],
             "is_draft": bool,
             # Gallery photos the extension already downloaded. Preferred over
             # image_urls, which stays as the fallback for anything it could not
             # fetch itself.
             "images": [{"filename", "content_base64", "source_url"}],
             "attributes": [{"name", "value"}],
             # Each variation may carry its own photo the same way, as `image`,
             # with `image_url` kept alongside as the retry address.
             "variants": [{"name", "price", "stock", "image_url",
                           "image": {"filename", "content_base64"}}]}
        ]}

    Returns a per-item outcome rather than failing the whole batch on one bad
    row — a 40-product list where two names already exist should import the
    other 38 and say which two it skipped.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST required'}, status=405)

    payload = _json_body(request)
    items = payload.get('products')
    if not isinstance(items, list) or not items:
        return JsonResponse(
            {'success': False, 'message': 'No products supplied.'}, status=400
        )
    if len(items) > MAX_PRODUCTS_PER_IMPORT:
        return JsonResponse(
            {'success': False,
             'message': f'Too many products in one request (max {MAX_PRODUCTS_PER_IMPORT}).'},
            status=400,
        )

    created, skipped, results = 0, 0, []

    for index, item in enumerate(items):
        name = (item.get('name') or '').strip()
        if not name:
            results.append({'index': index, 'status': 'error',
                            'message': 'Missing product name'})
            continue

        try:
            price = Decimal(str(item.get('price')))
        except (InvalidOperation, TypeError, ValueError):
            results.append({'index': index, 'name': name, 'status': 'error',
                            'message': 'Invalid price'})
            continue
        if price <= 0:
            results.append({'index': index, 'name': name, 'status': 'error',
                            'message': 'Price must be greater than zero'})
            continue

        # --- Duplicate detection ---------------------------------------------
        # The listing URL is checked FIRST and the name only as a fallback.
        #
        # Name matching alone was wrong both ways. It missed real duplicates,
        # because the extension can translate titles - the same offer scraped
        # with translation off and then on produces two different names and
        # imported twice, which is where the duplicate product cards came from.
        # And it invented duplicates, because 1688 titles are long keyword
        # strings that different listings from one factory often share
        # byte-for-byte, so a genuinely new product was silently dropped.
        #
        # canonical_source_url collapses the tracking parameters and host
        # variants (detail. / m. / www.) that make one offer arrive as several
        # different strings.
        raw_source_url = (item.get('source_url') or '').strip()
        canonical_url = canonical_source_url(raw_source_url)[:500]

        existing = None
        matched_on = ''
        if canonical_url:
            existing = Product.objects.filter(source_url=canonical_url).first()
            matched_on = 'listing'
        if existing is None:
            existing = Product.objects.filter(name__iexact=name).first()
            matched_on = 'name'

        if existing is not None:
            skipped += 1
            # Naming the product that was matched, and how, is the difference
            # between "1 duplicate skipped" and being able to act on it. A name
            # match on a different listing is worth a second look; a listing
            # match is certain.
            if matched_on == 'listing':
                detail = f'Already imported as "{existing.name}" (#{existing.id}).'
            else:
                detail = (
                    f'A product named "{existing.name}" (#{existing.id}) already exists. '
                    f'If this is a different listing, rename one of them and re-import.'
                )
            results.append({
                'index': index, 'name': name, 'status': 'skipped',
                'message': detail,
                'existing_id': existing.id,
                'existing_name': existing.name,
                'matched_on': matched_on,
            })
            continue

        try:
            moq = max(1, int(item.get('moq') or 1))
        except (TypeError, ValueError):
            moq = 1

        def _optional_number(key):
            """Blank/absent optional numerics become NULL rather than 0."""
            raw = item.get(key)
            if raw in (None, '', 'null'):
                return None
            try:
                return Decimal(str(raw))
            except (InvalidOperation, TypeError, ValueError):
                return None

        source = (item.get('source') or 'general').strip().lower()
        if source not in {'general', 'amazon', 'noon'}:
            source = 'general'

        category, subcategory = _resolve_category(
            item.get('category_slug'), item.get('subcategory_slug'), name
        )

        product = Product.objects.create(
            name=name,
            price=price,
            moq=moq,
            weight=_optional_number('weight'),
            carton_qty=int(item['carton_qty']) if str(item.get('carton_qty') or '').isdigit() else None,
            # Carton dimensions in CM, read from the listing's own data model.
            # Without these the site cannot compute CBM, and CBM is what sea
            # freight is priced on — so a product missing them cannot be quoted.
            carton_length=_optional_number('carton_length'),
            carton_width=_optional_number('carton_width'),
            carton_height=_optional_number('carton_height'),
            sku=(item.get('sku') or '').strip()[:100],
            source=source,
            # Where this came from, so the buyer can message the supplier later.
            # Stored canonical so the NEXT import can match it. Storing the
            # raw URL would mean the same offer arriving with different
            # tracking parameters never compares equal to this row.
            source_url=canonical_url,
            is_draft=bool(item.get('is_draft')),
            category=category,
            subcategory=subcategory,
        )

        # --- Images the extension already downloaded -------------------------
        # The browser is sitting on the 1688 page with the CDN happily serving
        # it, so it can fetch a photo that this server often cannot: the SSRF
        # guard refuses hosts it does not recognise, a VPN can resolve every
        # host into a private range, and shared hosting frequently has no
        # outbound access at all. Those failures are exactly why
        # fetch_remote_images exists as a retry command.
        #
        # When the extension sends the bytes, none of that applies - the image
        # is already here. URLs remain supported and are used for anything the
        # extension could not fetch itself.
        images_saved, images_rejected = _save_uploaded_images(
            product, name, item.get('images') or []
        )
        images_failed = 0

        image_urls = item.get('image_urls') or []
        if images_saved >= MAX_IMAGES_PER_PRODUCT:
            image_urls = []
        for url in image_urls[:MAX_IMAGES_PER_PRODUCT - images_saved]:
            safe_name = re.sub(r'[^\w\-]', '_', name)[:50] or 'product'
            fetched = _fetch_image(url)
            if fetched is None:
                # Could not download it — blocked host, no outbound network, dead
                # link. NOTHING is stored.
                #
                # This used to create a row carrying only the URL, so the product
                # page hotlinked the supplier's CDN. That looked like a save and
                # was not: alicdn is unreachable or throttled from Pakistan and
                # much of the region we sell into, so the customer saw a broken
                # frame while staff on a working connection saw a photo and had no
                # idea. A product with fewer images is honest; one with images
                # that only load for some of the world is not.
                #
                # The URL is not lost - it stays in the payload's image_urls and
                # the extension can re-push, or the photo can be uploaded by hand.
                images_failed += 1
                continue
            data, extension = fetched
            ProductImage.objects.create(
                product=product,
                image=ContentFile(data, name=f'{safe_name}_{images_saved + 1}.{extension}'),
                source_url=url[:500],
            )
            images_saved += 1

        variants_saved, variant_images_saved = _create_variants(
            product, item.get('variants') or []
        )
        attributes_saved = _create_attributes(product, item.get('attributes') or [])

        created += 1
        results.append({
            'index': index,
            'name': name,
            'status': 'created',
            'product_id': product.id,
            'images': images_saved,
            'variants': variants_saved,
            # How many of those variations have their photo stored locally rather
            # than hotlinked. Reported separately because the gap between the two
            # is what `fetch_remote_images` still has to pick up.
            'variant_images': variant_images_saved,
            'attributes': attributes_saved,
            # Photos that could be downloaded by neither the extension nor this
            # server, and are therefore NOT on the product at all. Nothing is
            # hotlinked any more, so this is the number the operator has to act
            # on rather than a category of second-class image.
            'images_failed': images_failed,
            # Bytes the client sent that were not a usable image. Reported so a
            # silent drop cannot be mistaken for a product that simply had no
            # photos.
            'images_rejected': images_rejected,
            'category': category.name if category else None,
        })

    message = f'{created} product(s) imported.'
    if skipped:
        message += f' {skipped} duplicate(s) skipped.'

    return JsonResponse({
        'success': True,
        'created': created,
        'skipped': skipped,
        'message': message,
        'results': results,
    })
