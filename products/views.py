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
import urllib.parse
from decimal import Decimal, InvalidOperation
from django.contrib.auth.decorators import login_required
# Role-aware access guard: only users whose profile grants the 'products' module
# (admins always, or staff with perm_products) may reach these views.
from accounts.decorators import module_required
from accounts.services import log_action
from django.contrib import messages
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Count, Q, Sum
from .api import _host_is_allowed as _api_host_is_allowed
from .models import (Category, PriceAdjustment, Product, ProductAttribute,
                     ProductImage, ProductTag, ProductVariant, SubCategory)
from .categorization import classify

# Paginator for list view pagination — improves performance and UX for large datasets.
from django.core.paginator import Paginator

from django.db import transaction
from django.http import JsonResponse, HttpResponse
# NOTE: @csrf_exempt was removed from the views in this file. The admin UI now
# attaches X-CSRFToken to every same-origin state-changing fetch() automatically
# (see the wrapper at the top of static/main.js), so these endpoints are
# protected again without any call site needing to change.

# ensure_csrf_cookie guarantees the csrftoken cookie is set even on pages that
# render no form. The catalogue is a print/export view with no POSTs today, so it
# was the one admin page that shipped without the cookie — meaning any AJAX added
# to it later would have failed with a 403 that looked like a server fault.
from django.views.decorators.csrf import ensure_csrf_cookie
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from settings_manager.models import CompanySettings
from customers.models import Customer
from utils.email_utils import send_typed_email


# --- Visibility ---------------------------------------------------------------
#
# "Public", "private" and "draft" are three different questions about a product,
# and the list used to answer them with three different mechanisms: private got
# its own grid, draft got a sort key, and public was whatever was left. Making
# them one filter is what allows a single selection to span them.
#
# `public` deliberately means "a customer can actually see this" — not private
# AND not draft. A draft is unfinished, so counting it as public would report
# more visible products than the storefront serves.
VISIBILITY_FILTERS = ('all', 'public', 'private', 'draft')


def _apply_visibility(qs, visibility):
    """
    Narrow a product queryset to one visibility band.

    Args:
        qs (QuerySet): Any Product queryset.
        visibility (str): One of VISIBILITY_FILTERS. Anything else is treated
            as 'all', so a hand-edited URL widens rather than crashing.

    Returns:
        QuerySet: The filtered queryset.

    Shared by product_list and bulk_action on purpose — see the module comment
    above. A bulk action offered as "all N matching the current filter" is only
    honest if the server rebuilds the identical set.
    """
    if visibility == 'public':
        return qs.filter(is_private=False, is_draft=False)
    if visibility == 'private':
        return qs.filter(is_private=True)
    if visibility == 'draft':
        return qs.filter(is_draft=True)
    return qs


@module_required('products')
def feed_health(request):
    """
    Show what the ad feeds currently contain, and what they are dropping.

    Args:
        request (HttpRequest): Staff only.

    Returns:
        HttpResponse: the feed status page.

    WHY THIS EXISTS

    A product feed fails quietly. Meta fetches it on its own schedule, rejects
    whatever does not meet the spec, and records the reason inside Commerce
    Manager — a screen nobody opens between campaigns. The usual result is a
    catalogue that has been half empty for a month.

    The commonest cause by far is a missing photo: Meta will not accept an item
    without an image, and an imported product whose picture download failed
    looks completely fine on the admin list. This page names those products so
    the gap is a task rather than a mystery.
    """
    from .feeds import build_rows, feed_queryset

    rows, skipped_no_image = build_rows()

    # The actual products being dropped, not just the count - the point is to be
    # able to go and fix them.
    missing = [
        p for p in feed_queryset() if not p.displayable_images
    ][:50]

    settings = CompanySettings.get_settings()
    return render(request, 'products/feed_health.html', {
        'row_count': len(rows),
        'product_count': feed_queryset().count(),
        'skipped_no_image': skipped_no_image,
        'missing_image_products': missing,
        'total_catalogue': Product.objects.count(),
        'private_excluded': Product.objects.filter(is_private=True).count(),
        'draft_excluded': Product.objects.filter(is_draft=True, is_private=False).count(),
        'site_url': (settings.site_url or '').rstrip('/'),
        'currency': settings.currency,
    })


@module_required('products')
def tag_save(request):
    """
    Rename or recolour one tag.

    Args:
        request (HttpRequest): POST with JSON {id, name, colour}.

    Returns:
        JsonResponse: {'success': bool, 'message': str}

    The slug is deliberately NOT regenerated on rename. A tag's slug is what the
    ?tag= filter carries, so rewriting it would break every bookmarked or shared
    filtered view the moment somebody fixed a typo in the label. The slug
    identifies the tag; the name is what people read.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})

    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid request data'})

    tag = ProductTag.objects.filter(id=data.get('id')).first()
    if tag is None:
        return JsonResponse({'success': False, 'message': 'Tag not found'})

    name = str(data.get('name') or '').strip()[:60]
    if not name:
        return JsonResponse({'success': False, 'message': 'A tag needs a name.'})
    clash = ProductTag.objects.filter(name__iexact=name).exclude(pk=tag.pk).first()
    if clash is not None:
        return JsonResponse(
            {'success': False, 'message': f'"{clash.name}" already exists.'}
        )

    colour = str(data.get('colour') or '').strip()
    valid_colours = {c for c, _ in ProductTag.COLOUR_CHOICES}

    old_name = tag.name
    tag.name = name
    if colour in valid_colours:
        tag.colour = colour
    tag.save(update_fields=['name', 'colour'])

    log_action(request, 'products.tag_save', target=f'Tag #{tag.id}',
               detail=f'Renamed "{old_name}" to "{name}"' if old_name != name
                      else f'Recoloured "{name}"')
    return JsonResponse({'success': True, 'message': f'Saved "{name}"'})


@module_required('products')
def tag_delete(request):
    """
    Delete one tag.

    Args:
        request (HttpRequest): POST with JSON {id}.

    Returns:
        JsonResponse: {'success': bool, 'message': str}

    Removing a tag detaches it from every product carrying it and changes
    nothing else — no product is deleted, hidden or re-categorised. That is what
    makes tags safe to experiment with, and it is why this is allowed where a
    bulk product delete is not.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'})

    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid request data'})

    tag = ProductTag.objects.filter(id=data.get('id')).first()
    if tag is None:
        return JsonResponse({'success': False, 'message': 'Tag not found'})

    name = tag.name
    attached = tag.products.count()
    tag.delete()
    log_action(request, 'products.tag_delete', target=f'Tag "{name}"',
               detail=f'Removed from {attached} product(s)')
    return JsonResponse({
        'success': True,
        'message': f'Deleted "{name}"' + (f' from {attached} product(s)' if attached else ''),
    })


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
    # cards rendered on the current page.
    query = request.GET.get('q', '').strip()

    # --- One list, not two ---
    #
    # This screen used to render two separate grids: a paginated public one, and
    # a collapsed block holding every private product. That split is precisely
    # why a bulk action could never mean "all products". Selection is a scan of
    # rendered checkboxes, so it stopped at whichever grid you were looking at,
    # and the whole-filter scope on the server excluded private rows outright —
    # which made "select all 30 matching" a promise the page could not keep.
    #
    # Now there is ONE queryset, and visibility is a filter like any other.
    # Private stops being a place products live and becomes a property they
    # have, which is what lets a bulk action reach them.
    #
    # 'variants' and 'tags' are prefetched because every card reads both — the
    # "from" price and the tag chips. Without it that is two extra queries per
    # card rendered.
    base_qs = Product.objects.prefetch_related('images', 'variants', 'tags')

    if query:
        base_qs = base_qs.filter(Q(name__icontains=query) | Q(sku__icontains=query))

    # --- Category filter ---
    # Bulk work is nearly always done a category at a time — freight and margin
    # differ far more between "Power Tools" and "Photo Frames" than within either.
    # A subcategory alone is enough; it already implies its parent.
    category_slug = (request.GET.get('category') or '').strip()
    subcategory_slug = (request.GET.get('subcategory') or '').strip()
    if subcategory_slug:
        base_qs = base_qs.filter(subcategory__slug=subcategory_slug)
    elif category_slug:
        base_qs = base_qs.filter(category__slug=category_slug)

    # --- Tag filter ---
    # Several tags mean "carries ALL of these", not "any", because that is the
    # direction that narrows. Tags exist to isolate a set no category describes
    # — one supplier's goods that still need photographing — and chaining them
    # is the point. `any` would WIDEN the set with each extra chip, which is
    # never what the person clicking a second one wants.
    #
    # Chained .filter() calls rather than one __in: on a many-to-many those mean
    # different things. A single filter(tags__slug__in=[a, b]) matches a product
    # carrying EITHER, and duplicates rows; a separate filter per tag joins the
    # table again each time, which is what "carries all of them" requires.
    tag_slugs = [s.strip() for s in request.GET.getlist('tag') if s.strip()]
    for slug in tag_slugs:
        base_qs = base_qs.filter(tags__slug=slug)

    # --- Visibility ---
    # Counted BEFORE the visibility filter is applied, so each chip can show how
    # many products it would show. Counting after would print "Private (0)"
    # whenever you are looking at the public list — exactly when you need to
    # know there are private ones to switch to.
    visible_counts = {
        'all': base_qs.count(),
        'public': base_qs.filter(is_private=False, is_draft=False).count(),
        'private': base_qs.filter(is_private=True).count(),
        'draft': base_qs.filter(is_draft=True).count(),
    }

    visibility = (request.GET.get('visibility') or 'all').strip().lower()
    if visibility not in VISIBILITY_FILTERS:
        visibility = 'all'
    base_qs = _apply_visibility(base_qs, visibility)

    # --- Page size ---
    # 24 made every bulk action unreachable past the first page: selection is a
    # DOM checkbox scan, so "select all visible" could never mean more than the
    # cards on screen. Raising it — or turning pagination off with ?per_page=all
    # — is what lets one action cover the whole catalogue.
    SHOW_ALL_CEILING = 1000
    per_page_raw = (request.GET.get('per_page') or '24').strip().lower()
    show_all = per_page_raw == 'all'
    try:
        per_page = max(12, min(500, int(per_page_raw)))
    except ValueError:
        per_page = 24

    # Drafts first, then private, then by name: the rows needing attention sit at
    # the top of the list rather than wherever the alphabet puts them.
    ordered_qs = base_qs.order_by('is_draft', 'is_private', 'name')

    if show_all:
        # One page holding everything, up to a ceiling — a browser asked to lay
        # out tens of thousands of cards stops responding. Past the ceiling the
        # page stays paginated and `is_partial_page` turns true, which is what
        # offers the whole-filter scope instead. So a bulk action still reaches
        # every product; it just no longer does it through the checkboxes.
        per_page = max(min(ordered_qs.count(), SHOW_ALL_CEILING), 1)

    # --- Pagination ---
    # The paginator runs over the QUERYSET, so only one page is fetched, and CBM
    # is computed for that page alone. The previous version materialised the
    # whole catalogue on every request to annotate rows it never rendered.
    page_number = request.GET.get('page', 1)
    paginator = Paginator(ordered_qs, per_page)
    page_obj = paginator.get_page(page_number)
    page_obj.object_list = _annotate_cbm(page_obj.object_list)

    return render(request, 'products/product_list.html', {
        'page_obj': page_obj,
        'query': query,
        'total_count': paginator.count,
        # The whole catalogue, ignoring every filter. Only the margin
        # dialog's "all products" scope uses this, and it must not move
        # when somebody narrows the list — that scope really does mean
        # every row, including private and draft ones.
        'catalogue_count': Product.objects.count(),
        'visible_counts': visible_counts,
        'visibility': visibility,
        'air_rate': air_rate,
        'sea_rate': sea_rate,
        'ksa_air_rate': ksa_air_rate,
        'ksa_sea_rate': ksa_sea_rate,
        'currency': settings.currency,
        'fx_enabled': fx_enabled,
        'fx_rate': fx_rate,
        'fx_from': fx_from,
        'fx_to': fx_to,
        # Populates the category/subcategory dropdowns in the add and edit
        # product forms. Subcategories are prefetched because the template
        # renders every category's children up front and filters them in the
        # browser, which avoids a round trip when the admin changes category.
        'categories': Category.objects.filter(is_active=True).prefetch_related('subcategories'),

        # Every tag with how many products carry it, for the filter bar and the
        # bulk-tag dialog. Annotated rather than counted per tag in the template,
        # which would be one query per chip.
        'all_tags': ProductTag.objects.annotate(product_count=Count('products')).order_by('name'),
        'filter_tags': tag_slugs,

        # --- List controls ---
        'per_page': per_page_raw,
        'show_all': show_all,
        'filter_category': category_slug,
        'filter_subcategory': subcategory_slug,
        # True when the page is showing less than the full filtered set, which is
        # what makes "select all visible" a partial selection and therefore worth
        # warning about before a bulk action runs.
        'is_partial_page': paginator.count > len(page_obj.object_list),
        'filters_active': bool(query or category_slug or subcategory_slug
                               or tag_slugs or visibility != 'all'),
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

    first_image = product.primary_image
    # `src` already resolves local file -> remote URL -> '' and swallows the
    # ValueError a fileless row would otherwise raise.
    first_image_url = first_image.src if first_image else ''

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


def _resolve_row_category(category_value, subcategory_value, product_name):
    """
    Resolve the category columns of one bulk-upload row.

    Args:
        category_value (str | None): The row's ``category`` cell.
        subcategory_value (str | None): The row's ``subcategory`` cell.
        product_name (str): Used for the keyword fallback.

    Returns:
        tuple[Category | None, SubCategory | None]

    Cells are matched against the SLUG first and the display name second. The
    extension writes slugs, but a person filling the template by hand will
    naturally type "Home & Kitchen", and rejecting that would be needlessly
    strict — the two namespaces do not collide.

    A subcategory alone is enough: it already knows its parent. When both cells
    are blank the keyword rules in categorization.py classify the product from
    its name, so a hand-filled template still lands in the right place rather
    than becoming invisible to the portal's category filters.
    """
    category_text = (category_value or '').strip()
    subcategory_text = (subcategory_value or '').strip()

    if subcategory_text:
        subcategory = (
            SubCategory.objects.select_related('category')
            .filter(slug__iexact=subcategory_text)
            .first()
            or SubCategory.objects.select_related('category')
            .filter(name__iexact=subcategory_text)
            .first()
        )
        if subcategory:
            return subcategory.category, subcategory

    if category_text:
        category = (
            Category.objects.filter(slug__iexact=category_text).first()
            or Category.objects.filter(name__iexact=category_text).first()
        )
        if category:
            return category, None

    match = classify(product_name or '')
    if match is None:
        return None, None

    cat_slug, sub_slug = match
    category = Category.objects.filter(slug=cat_slug).first()
    if category is None:
        return None, None
    if sub_slug is None:
        return category, None
    return category, SubCategory.objects.filter(category=category, slug=sub_slug).first()


def _catalogue_selection(request, queryset):
    """
    Narrow a catalogue queryset to the categories the operator picked.

    Both catalogue outputs — the printable page and the Excel file — used to
    render the entire catalogue every time. That is the wrong unit of work for
    the way these are actually used: a buyer asks for "your photo frames", and
    sending them 400 products so they can find the eleven they asked about is
    worse than sending nothing.

    Reads two repeatable parameters so a selection can span several categories:

        ?category=photo-frames&category=home-kitchen
        ?subcategory=kitchen

    A subcategory selection is honoured on its own — it already implies its
    parent — and combines with categories as a union, not an intersection: a
    person ticking "Photo Frames" and "Kitchen" wants both sets, not the empty
    overlap between them.

    Args:
        request (HttpRequest): Supplies the query parameters.
        queryset (QuerySet): The Product queryset to narrow.

    Returns:
        tuple[QuerySet, str]: The narrowed queryset, and a human label for the
        selection ('' when nothing was picked) used in headings and filenames.
    """
    category_slugs = [s for s in request.GET.getlist('category') if s.strip()]
    subcategory_slugs = [s for s in request.GET.getlist('subcategory') if s.strip()]

    if not category_slugs and not subcategory_slugs:
        return queryset, ''

    selector = Q()
    if category_slugs:
        selector |= Q(category__slug__in=category_slugs)
    if subcategory_slugs:
        selector |= Q(subcategory__slug__in=subcategory_slugs)
    queryset = queryset.filter(selector)

    names = list(
        Category.objects.filter(slug__in=category_slugs).values_list('name', flat=True)
    ) + list(
        SubCategory.objects.filter(slug__in=subcategory_slugs).values_list('name', flat=True)
    )
    # Three names is as much as fits in a filename or a page heading before it
    # stops being readable; past that the count says more than the list would.
    if len(names) > 3:
        label = f'{len(names)} categories'
    else:
        label = ', '.join(names)
    return queryset, label


def _catalogue_show_prices(request):
    """
    Whether this catalogue should carry prices.

    Args:
        request (HttpRequest): carries ``?prices=0`` to suppress them.

    Returns:
        bool: True unless the caller asked for a price-free catalogue.

    WHY THIS IS A SERVER-SIDE FLAG AND NOT A CSS CLASS

    Hiding the price column with ``display:none`` would produce an identical
    printout and leave every figure sitting in the HTML. A catalogue is a file
    that gets saved, forwarded and opened in a browser by whoever received it -
    and a price-free catalogue is usually price-free for a reason: it is going
    to a distributor who quotes their own margin, or to a buyer before terms are
    agreed. "View source" must not undo that.

    So when this is False the prices are never rendered at all, and the Excel
    export omits the columns rather than blanking them.
    """
    return (request.GET.get('prices') or '').strip().lower() not in ('0', 'no', 'off', 'hide', 'false')


def _catalogue_toggle_url(request, show_prices):
    """
    The current catalogue URL with the prices flag inverted.

    Args:
        request (HttpRequest): the current request, whose query string carries
            the category selection.
        show_prices (bool): what the page is showing now.

    Returns:
        str: e.g. '?category=tools&prices=0'

    Every other parameter is carried through untouched, so switching prices off
    on a three-category catalogue does not silently widen it to the whole range.
    """
    params = request.GET.copy()
    params['prices'] = '1' if not show_prices else '0'
    return '?' + params.urlencode()


def _catalogue_filename_suffix(label):
    """Turn a selection label into something safe to put in a filename."""
    if not label:
        return ''
    return '_' + re.sub(r'[^A-Za-z0-9]+', '_', label).strip('_').lower()[:40]


def _store_product_images(product, files, limit):
    """
    Save uploaded images against a product, reporting a storage failure instead
    of raising.

    Args:
        product (Product): The product the images belong to.
        files (list): UploadedFile objects from request.FILES.getlist().
        limit (int): How many more images this product may have.

    Returns:
        tuple[int, str]: (number saved, error message). The message is empty on
        success.

    Why this catches OSError:
        Writing an upload is the only part of saving a product that touches the
        filesystem, so it is the only part that can fail for reasons that have
        nothing to do with the submitted data — MEDIA_ROOT missing or not
        writable by the web-server user, or the account out of disk quota.

        Uncaught, that raises out of the view and Django returns an HTML 500
        page. The browser is expecting JSON, so the page reported a generic
        failure and the real cause was visible only in the server error log.
        Returning it as a message puts the actual reason in front of the person
        who can fix it.
    """
    if not files or limit <= 0:
        return 0, ''

    saved = 0
    for upload in files[:limit]:
        try:
            ProductImage.objects.create(product=product, image=upload)
            saved += 1
        except OSError as exc:
            return saved, (
                f'Saved the product, but the image could not be stored: {exc}. '
                f'This is a server storage problem, not a problem with the file. '
                f'Check that MEDIA_ROOT exists and is writable.'
            )
    return saved, ''


def _save_attributes(request, product):
    """
    Replace ``product``'s spec lines with whatever the form posted.

    The form sends two parallel arrays, ``attr_name[]`` and ``attr_value[]``, one
    entry per row in the editor. Rows are matched by position, so the order the
    operator arranged them in is the order they are stored and displayed.

    Replace-all rather than diff-and-update: the editor posts the complete set every
    time, there are only ever a handful of rows, and reconciling ids would add a
    failure mode (a stale id deleting someone else's row) for no benefit at this size.

    A row is kept only when it has BOTH a name and a value. Half-filled rows are the
    normal state of an editor someone is still typing in — silently dropping them is
    what the operator expects, and storing "Model: " helps nobody.

    Does nothing at all when the form posted no attribute fields, so saving a product
    from a screen without the attributes editor cannot wipe specs entered elsewhere.
    """
    if 'attr_name[]' not in request.POST:
        return

    names = request.POST.getlist('attr_name[]')
    values = request.POST.getlist('attr_value[]')

    product.attributes.all().delete()

    rows = []
    for index, raw_name in enumerate(names):
        name = (raw_name or '').strip()[:100]
        value = (values[index] if index < len(values) else '').strip()[:500]
        if not name or not value:
            continue
        rows.append(ProductAttribute(
            product=product, name=name, value=value, sort_order=len(rows)
        ))
    if rows:
        ProductAttribute.objects.bulk_create(rows)


def _save_variants(request, product):
    """
    Reconcile ``product``'s variations with what the editor posted.

    The form sends four parallel arrays — ``variant_id[]``, ``variant_name[]``,
    ``variant_price[]``, ``variant_stock[]`` — one entry per row. A blank id means
    a new row.

    UNLIKE the attributes editor this does NOT delete and recreate, for two
    reasons. Order lines point at variants with ``on_delete=PROTECT``, so
    recreating them would either raise or silently rewrite what a customer
    actually bought; and the ids have to survive so an open cart keeps pointing at
    the right option.

    A variation the operator removed is deleted when nothing references it, and
    deactivated when something does — ``is_active=False`` takes it out of the
    catalogue while leaving the order history intact and readable.

    Does nothing when the form posted no variant fields, so saving a product from
    a screen without this editor cannot wipe its variations.
    """
    if 'variant_name[]' not in request.POST:
        return

    from django.db.models import ProtectedError

    ids = request.POST.getlist('variant_id[]')
    names = request.POST.getlist('variant_name[]')
    prices = request.POST.getlist('variant_price[]')
    stocks = request.POST.getlist('variant_stock[]')

    existing = {v.id: v for v in product.variants.all()}
    kept = set()

    for position, raw_name in enumerate(names):
        name = (raw_name or '').strip()[:255]
        raw_price = (prices[position] if position < len(prices) else '').strip()
        if not name or not raw_price:
            continue
        try:
            price = Decimal(raw_price)
        except (InvalidOperation, ValueError):
            continue
        if price <= 0:
            continue

        raw_stock = (stocks[position] if position < len(stocks) else '').strip()
        stock = int(raw_stock) if raw_stock.isdigit() else None

        raw_id = (ids[position] if position < len(ids) else '').strip()
        variant = existing.get(int(raw_id)) if raw_id.isdigit() else None

        if variant is not None:
            variant.name = name
            variant.price = price
            variant.stock = stock
            variant.sort_order = position
            # Re-saving a row that had been deactivated brings it back.
            variant.is_active = True
            variant.save(update_fields=['name', 'price', 'stock', 'sort_order', 'is_active'])
            kept.add(variant.id)
        else:
            created = ProductVariant.objects.create(
                product=product, name=name, price=price, stock=stock, sort_order=position
            )
            kept.add(created.id)

    for variant_id, variant in existing.items():
        if variant_id in kept:
            continue
        try:
            variant.delete()
        except ProtectedError:
            # An order line still refers to it. Retire it instead of destroying
            # the record of what someone bought.
            variant.is_active = False
            variant.save(update_fields=['is_active'])


def _resolve_category_fields(request, product_name):
    """
    Work out which Category and SubCategory a submitted product belongs to.

    Args:
        request (HttpRequest): The POST request carrying the form fields
            'category' and 'subcategory', each holding a primary key or ''.
        product_name (str): The product's name, used for the fallback below.

    Returns:
        tuple[Category | None, SubCategory | None]

    Business Logic:
        The subcategory wins when both are supplied. A subcategory already
        knows its parent, so trusting it avoids storing a mismatched pair if
        the two dropdowns ever get out of step in the browser.

        When the admin leaves both blank we fall back to the keyword rules in
        categorization.py. Without that fallback, every product added after
        this feature shipped would arrive uncategorised and quietly disappear
        from the portal's category filters — the exact problem the backfill
        migration existed to fix.
    """
    subcategory_id = (request.POST.get('subcategory') or '').strip()
    category_id = (request.POST.get('category') or '').strip()

    if subcategory_id:
        subcategory = (
            SubCategory.objects.select_related('category')
            .filter(id=subcategory_id)
            .first()
        )
        if subcategory:
            return subcategory.category, subcategory

    if category_id:
        category = Category.objects.filter(id=category_id).first()
        if category:
            return category, None

    # Nothing chosen — infer it from the name.
    match = classify(product_name or '')
    if match is None:
        return None, None

    cat_slug, sub_slug = match
    category = Category.objects.filter(slug=cat_slug).first()
    if category is None:
        return None, None
    if sub_slug is None:
        return category, None

    subcategory = SubCategory.objects.filter(category=category, slug=sub_slug).first()
    return category, subcategory


@module_required('products')
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
        source_url = (request.POST.get('source_url') or '').strip()[:500]
        # Falls back to keyword classification when the admin picks neither.
        category, subcategory = _resolve_category_fields(request, name)
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
            source_url=source_url,
            category=category,
            subcategory=subcategory,
        )
        # Create ProductImage records for each uploaded image (limit to first 3)
        _, image_error = _store_product_images(product, images, 3)
        _save_attributes(request, product)
        # Notify customers if this is a published Amazon/Noon product
        settings = CompanySettings.get_settings()
        _notify_new_marketplace_product(product, settings)
        if image_error:
            # The product exists, so this is not a failure of the whole save.
            # Reported as an error anyway because the admin asked for images and
            # did not get them, and silence would look like success.
            return JsonResponse({'success': False, 'message': image_error})
        # Return a different message depending on whether it was saved as draft or published
        label = 'Draft saved!' if is_draft else 'Product added successfully!'
        return JsonResponse({'success': True, 'message': label})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('products')
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
        images = [{'id': img.id, 'url': img.src} for img in product.images.all()]
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
            # Sent as '' rather than null so the edit form can assign them
            # straight to a <select>'s value without null-checking each one.
            'category': product.category_id or '',
            'subcategory': product.subcategory_id or '',
            'source_url': product.source_url or '',
            'images': images,
            'attributes': [
                {'name': a.name, 'value': a.value} for a in product.attributes.all()
            ],
            'variants': [
                {
                    'id': v.id,
                    'name': v.name,
                    'price': str(v.price),
                    'stock': v.stock,
                    'image': v.src,
                    'is_active': v.is_active,
                }
                for v in product.variants.all()
            ],
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
        # Only touched when the form actually posted the field, so editing from
        # a screen without this input cannot wipe a saved link.
        if 'source_url' in request.POST:
            product.source_url = (request.POST.get('source_url') or '').strip()[:500]
        # Only reassign when the form actually submitted a category field.
        # Editing a product from a screen that has no category dropdown must
        # not silently wipe an assignment made elsewhere.
        if 'category' in request.POST or 'subcategory' in request.POST:
            product.category, product.subcategory = _resolve_category_fields(
                request, product.name
            )
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
        _, image_error = _store_product_images(
            product, new_images, max(0, 3 - current_count)
        )
        _save_attributes(request, product)
        _save_variants(request, product)
        if image_error:
            # Everything else on the form was saved; only the upload failed.
            return JsonResponse({'success': False, 'message': image_error})
        return JsonResponse({'success': True, 'message': f'{product.name} updated!'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@module_required('products')
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
@ensure_csrf_cookie
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
    catalogue_qs, selection_label = _catalogue_selection(
        request,
        # select_related for the category the page now groups under. The sort
        # below already joins on category__name, but a join for ORDER BY does
        # not populate p.category - reading the name in the template would have
        # cost one query per product.
        Product.objects
        .select_related('category')
        .prefetch_related('images')
        .filter(is_draft=False, is_private=False),
    )
    products = catalogue_qs.order_by('category__name', 'name')
    settings = CompanySettings.get_settings()

    # A price-free catalogue for handing to a distributor who adds their own
    # margin, or to a buyer before terms are agreed. See _catalogue_show_prices
    # for why this is decided here rather than hidden with CSS.
    show_prices = _catalogue_show_prices(request)

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
        # The heading this product sits under. Set here rather than reached for
        # in the template so the "no category" wording is written once, and so
        # {% regroup %} has a single value to group on - it compares adjacent
        # rows only, which is why the queryset above must stay ordered by
        # category__name for the grouping to come out whole.
        p.category_display = (
            p.category.name if p.category_id and p.category else 'Uncategorised'
        )
    return render(request, 'products/catalogue.html', {
        # Printed under the company name, so a catalogue handed to a buyer states
        # its own scope instead of looking like the full range.
        'selection_label': selection_label,
        'products': products,
        'settings': settings,
        'show_prices': show_prices,
        # Link to the same catalogue with prices flipped, keeping whichever
        # categories were selected. Built here rather than in the template so
        # the query string is assembled in one place with real encoding.
        'prices_toggle_url': _catalogue_toggle_url(request, show_prices),
        # The currency and markup controls only make sense when there are
        # prices on the page to convert or mark up.
        'fx_enabled': fx_enabled and show_prices,
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
    # Fetch non-draft products with their images, narrowed to whatever categories
    # the operator ticked in the export dialog (all of them when none were).
    catalogue_qs, selection_label = _catalogue_selection(
        request,
        # select_related for the two FKs the Category column reads. The sheet
        # was already ORDERED by category__name, which joins for the sort but
        # leaves p.category unpopulated - so printing the name would have gone
        # back to the database once per product and put back the N+1 that the
        # images prefetch below exists to avoid.
        Product.objects
        .select_related('category', 'subcategory')
        .prefetch_related('images')
        .filter(is_draft=False),
    )
    products = list(catalogue_qs.order_by('category__name', 'name'))

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
    # A catalogue with no prices in it - for a distributor who quotes their own
    # margin, or a buyer before terms. The price COLUMNS are dropped rather than
    # blanked: an empty "Price" column invites someone to wonder what belongs
    # there, and a hidden column in a spreadsheet is one right-click from being
    # visible again.
    show_prices = _catalogue_show_prices(request)

    cols = [
        ('No.',           6),
        ('Image',        12),
        # SKU first among the identifying columns because it is what the
        # importer matches on: a name is free text that someone will tidy up in
        # Excel, a SKU is the handle that survives the edit.
        ('SKU',          14),
        ('Product Name', 34),
        ('Category',     20),
    ] + ([
        ('Price',        13),
        ('Air Price',    13),
        ('Sea Price',    13),
    ] if show_prices else []) + [
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
    # The selection is stated in the file itself, not just its name — a sheet
    # forwarded on WhatsApp arrives without its filename attached, and a
    # partial catalogue that looks complete is how a buyer concludes you do
    # not stock something you do.
    _scope = f'  ·  {selection_label.upper()}' if selection_label else ''
    ws['A3'] = (
        f'PRODUCT CATALOGUE{_scope}  ·  '
        f'{datetime.date.today().strftime("%B %d, %Y")}  ·  {len(products)} products'
    )
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
        # The most specific label the product carries: a subcategory if it has
        # one, otherwise its category, otherwise nothing to say.
        if p.subcategory_id and p.subcategory:
            category_label = p.subcategory.name
        elif p.category_id and p.category:
            category_label = p.category.name
        else:
            category_label = '\u2014'

        row_vals = [
            (i,                                                         no_font,    'center'),
            (None,                                                      data_font,  'center'),  # image placeholder
            (p.sku or '\u2014',                                            data_font,  'center'),
            (p.name,                                                    name_font,  'left'),
            (category_label,                                            data_font,  'left'),
        ] + ([
            (float(p.price),                                            price_font, 'center'),
            (float(p.price_air)    if p.price_air    else '\u2014',     data_font,  'center'),
            (float(p.price_sea)    if p.price_sea    else '\u2014',     data_font,  'center'),
        ] if show_prices else []) + [
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

        # Try to embed the first product image in column B.
        #
        # Indexing the prefetched list, NOT .first(). The queryset above asks for
        # prefetch_related('images'), but .first() builds a fresh queryset with
        # its own LIMIT 1 and so ignores the cache entirely - one extra query per
        # product, which is the whole N+1: measured at 38 queries for 32
        # products, 156 for 150 and 406 for 400, climbing in lockstep with the
        # catalogue. Iterating the prefetched manager costs nothing.
        prefetched_images = list(p.images.all())
        first_img = prefetched_images[0] if prefetched_images else None
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
    # The selection goes in the filename so several exports in a row are
    # distinguishable in a downloads folder — 'catalogue_photo_frames_20260804.xlsx'
    # rather than three files called 'catalogue (1..3).xlsx'.
    filename = (
        f'catalogue{_catalogue_filename_suffix(selection_label)}'
        f'_{datetime.date.today().strftime("%Y%m%d")}.xlsx'
    )
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


# Column definitions for the bulk-upload template: (field, width, required,
# example1, example2).
#
# Module level rather than local to bulk_upload_template() because the IMPORTER
# needs the example values too - see BULK_TEMPLATE_EXAMPLE_SIGNATURES below.
# One definition means the two can never drift apart.
BULK_TEMPLATE_COLUMNS = [
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
    # Category slugs, matching what the 1688 extension exports. A display
    # name ("Home & Kitchen") is accepted too. Left blank, the importer
    # classifies the product from its name — see _resolve_row_category.
    ('category',       20, False, 'home-kitchen',      'health-personal-care'),
    ('subcategory',    20, False, 'kitchen',           'skin-treatments'),
    # Supplier listing URL — powers the "Contact supplier" button.
    ('source_url',     34, False, 'https://detail.1688.com/offer/123.html', ''),
]


def _bulk_template_example_signatures():
    """
    ``{(name, price, moq)}`` for the example rows the template ships with.

    Returns:
        frozenset[tuple[str, str, str]]: lower-cased, stripped signatures.

    Every template issued before this was fixed carries its examples INSIDE the
    data region the importer reads, so those files are still out there on
    people's disks. Matching on all three required fields rather than the name
    alone keeps a real product that happens to be called "Red Widget Pro" from
    being skipped - it would have to also cost 12.50 at an MOQ of 100.
    """
    sigs = set()
    by_field = {field: (ex1, ex2) for field, _w, _r, ex1, ex2 in BULK_TEMPLATE_COLUMNS}
    for idx in (0, 1):
        sigs.add((
            by_field['name'][idx].strip().lower(),
            by_field['price'][idx].strip(),
            by_field['moq'][idx].strip(),
        ))
    return frozenset(sigs)


BULK_TEMPLATE_EXAMPLE_SIGNATURES = _bulk_template_example_signatures()


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

    columns = BULK_TEMPLATE_COLUMNS
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
    ws['A5'] = 'Fill in product data below (* = required) — see the "Example" tab for a filled-in sample. For the Image column: click the cell, then use Insert > Picture (Excel) or Insert > Image (Sheets) to embed a photo.'
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

    # --- The examples, on a sheet of their OWN ----------------------------
    #
    # They used to occupy rows 8-9 of this sheet, which is exactly the region
    # the importer reads. Downloading the template and uploading it back
    # unchanged created "Red Widget Pro" and "Blue Water Bottle" as real
    # catalogue products - two junk rows per round trip - and nothing in the
    # file marked them as samples, so the importer could not tell them from
    # anything the user had typed.
    #
    # On their own tab they still show exactly what to enter, while the sheet
    # the importer reads starts out empty. The failure mode also inverts: data
    # typed on the wrong tab imports nothing and says so, instead of quietly
    # inserting examples nobody asked for.
    #
    # The importer ALSO skips these rows by value (see the example-signature
    # check in bulk_upload) because every template downloaded before this change
    # still has them in the data region.
    ex_ws = wb.create_sheet('Example')
    ex_ws.sheet_properties.tabColor = ORANGE

    ex_ws.merge_cells(f'A1:{last_col}1')
    ex_ws['A1'] = ('EXAMPLE ROWS — for reference only. Type your products on the '
                   '"Products" tab; nothing on this tab is imported.')
    ex_ws['A1'].font = Font(name='Calibri', size=10, bold=True, color=ORANGE)
    ex_ws['A1'].fill = PatternFill('solid', fgColor=DARK_BG)
    ex_ws['A1'].alignment = Alignment(horizontal='left', vertical='center', indent=2)
    ex_ws.row_dimensions[1].height = 24

    for col_idx, (name, width, required, *_rest) in enumerate(columns, start=1):
        cell = ex_ws.cell(row=2, column=col_idx)
        cell.value = name + (' *' if required else '')
        cell.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor=BLUE)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ex_ws.column_dimensions[get_column_letter(col_idx)].width = width
    ex_ws.row_dimensions[2].height = 26

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
    for row_offset, ex_idx in enumerate([0, 1], start=3):
        for col_idx, (name, width, required, ex1, ex2) in enumerate(columns, start=1):
            cell = ex_ws.cell(row=row_offset, column=col_idx)
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
        ex_ws.row_dimensions[row_offset].height = 40

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


# Where _parse_upload_rows stashes the row's real position in the uploaded
# file. Underscored so it cannot collide with a column header, and ignored by
# everything that reads rows by field name.
ROW_NUMBER_KEY = '__row__'

def _friendly_upload_error(exc):
    """
    Turn a parsing exception into something the person uploading can act on.

    Args:
        exc (Exception): whatever openpyxl, zipfile or csv raised.

    Returns:
        str: a message naming the likely cause and the fix.

    The handler used to emit ``f'Error processing file: {exc}'``, which showed
    the library's own wording to the operator. The single most common upload
    mistake - saving as .xls or CSV-renamed-to-.xlsx - surfaced as
    "File is not a zip file", because a modern .xlsx IS a zip and openpyxl says
    so when the magic bytes are wrong. Accurate, and useless to the person
    holding the file.
    """
    text = str(exc)
    lowered = text.lower()

    if 'not a zip file' in lowered or 'badzipfile' in lowered:
        return ('That file is not a readable .xlsx workbook. If it came from an '
                'older Excel (.xls) or was renamed from .csv, open it and use '
                'File > Save As > Excel Workbook (.xlsx).')
    if 'header row' in lowered:
        # Raised by _parse_upload_rows itself; already written for a human.
        return text
    if 'encoding' in lowered or isinstance(exc, UnicodeDecodeError):
        return ('That file could not be read as text. Save the CSV as UTF-8, or '
                'upload the .xlsx instead.')
    if isinstance(exc, MemoryError):
        return 'That file is too large to process. Split it into smaller batches.'
    return ('That file could not be read. Check it opens in Excel, then download '
            'a fresh template and copy your rows into it.')




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
    # `category` and `subcategory` were appended after the original nine so that
    # files produced by the 1688 browser extension carry the category through.
    # Appending rather than inserting keeps every previously-issued template and
    # spreadsheet valid: an older 9-column file simply leaves the two new
    # columns empty, and the importer treats that as "no category given".
    FIELDS = ['name', 'image', 'price', 'moq', 'weight', 'carton_length', 'carton_width',
              'carton_height', 'carton_qty', 'category', 'subcategory', 'source_url']
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
        # Read every column the sheet actually has, rather than a fixed count.
        #
        # This used to read exactly len(FIELDS) columns, which silently coupled
        # the reader to one specific column layout: the downloadable template
        # carries `source` and `ready_to_ship` in columns 10-11, so widening
        # FIELDS to add `category`/`subcategory` would have pushed those two
        # past the cutoff and made them stop importing. Reading by header name
        # across the sheet's real width removes that coupling entirely — any
        # column order works, and unknown columns are simply ignored downstream.
        #
        # max_column is capped so a sheet with stray formatting far to the right
        # cannot make this loop enormous.
        last_column = min(ws.max_column or len(FIELDS), 60)
        headers = [
            str(ws.cell(row=header_row, column=c).value or '').strip().lower().replace(' *', '')
            for c in range(1, last_column + 1)
        ]
        rows = []
        # Pairs whose header cell is blank are dropped — otherwise several empty
        # headers would collapse onto a single '' key and shadow one another.
        for r in range(header_row + 1, ws.max_row + 1):
            vals = [
                str(ws.cell(row=r, column=c).value or '').strip()
                for c in range(1, last_column + 1)
            ]
            if any(vals):  # Skip completely empty rows
                row = {
                    header: value
                    for header, value in zip(headers, vals)
                    if header
                }
                # The row number AS IT APPEARS IN THE FILE. The caller used to
                # derive it with `enumerate(..., start=2)`, which assumes the
                # header is row 1 - but the header is found anywhere in the
                # first ten rows, and in the downloadable template it is row 7.
                # Every error message was therefore off by the banner height,
                # sending someone fixing a failed import to row 2 when the bad
                # data was on row 8.
                row[ROW_NUMBER_KEY] = r
                rows.append(row)
        return rows
    else:
        # CSV parsing: read as UTF-8 with BOM handling, use DictReader for header-based mapping
        decoded = upload_file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(decoded))
        # Normalize header names and strip whitespace from values. line_num is
        # the real line in the file, which is what an error message has to
        # quote for it to be actionable.
        rows = []
        for row in reader:
            clean = {
                k.strip().lower().replace(' *', ''): (v or '').strip()
                for k, v in row.items() if k
            }
            clean[ROW_NUMBER_KEY] = reader.line_num
            rows.append(clean)
        return rows


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
        url_images = []          # (product, url) for rows whose `image` column is a link
        pending_variants = []    # rows naming a parent in `variant_of`, resolved after the loop
        errors = []

        for data_idx, row in enumerate(row_dicts):
            # `i` is the line number in the user's file, used in every message
            # below; `data_idx` stays 0-based from the first data row, which is
            # what selected_rows and the embedded-image map are keyed on.
            i = row.get(ROW_NUMBER_KEY) or (data_idx + 2)
            if selected_rows is not None and data_idx not in selected_rows:
                continue  # Skip rows not selected by the user
            name = (row.get('name') or '').strip()
            price_raw = (row.get('price') or '').strip()
            moq_raw = (row.get('moq') or '').strip()

            # Name, price, and MOQ are required for every product
            if not name or not price_raw or not moq_raw:
                errors.append(f'Row {i}: name, price, and moq are required — skipped')
                continue

            # The template's own example rows, left in place.
            #
            # Templates downloaded before the examples moved to their own tab
            # carry "Red Widget Pro" and "Blue Water Bottle" inside the data
            # region, and those files are still on people's disks. Uploading one
            # unchanged used to add both as real products. Matching on all three
            # required fields rather than the name alone means a genuine product
            # called "Red Widget Pro" is only skipped if it ALSO costs 12.50 at
            # an MOQ of 100 - at which point it is the sample.
            if (name.lower(), price_raw, moq_raw) in BULK_TEMPLATE_EXAMPLE_SIGNATURES:
                errors.append(f'Row {i}: "{name}" is the template\'s example row — skipped')
                continue

            # A row naming a parent in `variant_of` is a VARIATION of that product —
            # a colour or kit size — not a product of its own. Held back and attached
            # after the loop, once the parent row it points at has been created.
            #
            # Without this a 1688 listing selling seventeen SKUs imported as
            # seventeen near-identical catalogue products.
            variant_of = (row.get('variant_of') or '').strip()
            if variant_of:
                pending_variants.append((i, variant_of, name, price_raw, row))
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
            # The `image` column holds a URL in files exported by the sourcing
            # extension. It used to be read by nothing at all on this path, so a
            # CSV/XLSX import brought the products across and silently dropped every
            # photo — the images only arrived if you used the extension's own
            # "Push to site" button instead.
            image_url = (row.get('image') or '').strip()
            source = (row.get('source') or 'general').strip().lower()
            if source not in {'general', 'amazon', 'noon'}:
                source = 'general'
            ready_to_ship = str(row.get('ready_to_ship', '')).strip().lower() in {'1', 'yes', 'true'}

            # Category columns, written by the 1688 extension's exports. Blank
            # in a hand-filled template, in which case the keyword rules in
            # categorization.py fill it in — see _resolve_row_category.
            category, subcategory = _resolve_row_category(
                row.get('category'), row.get('subcategory'), name
            )
            source_url = (row.get('source_url') or '').strip()[:500]

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
                source_url=source_url,
                category=category,
                subcategory=subcategory,
            )
            created_products.append((product, image_filename))
            if image_url.lower().startswith(('http://', 'https://')):
                url_images.append((product, image_url))

        # --- Attach variation rows to their parent products ---
        #
        # Resolved after the main loop so a variation may appear anywhere in the
        # file, including above the product it belongs to. The parent is looked up
        # among the products this upload just created first, then among products
        # already in the catalogue — so a file can add variations to something
        # imported last week.
        variants_created = 0
        by_name = {p.name.lower(): p for p, _ in created_products}
        for row_no, parent_name, variant_name, variant_price_raw, row in pending_variants:
            parent = by_name.get(parent_name.lower())
            if parent is None:
                parent = Product.objects.filter(name__iexact=parent_name).first()
            if parent is None:
                errors.append(
                    f'Row {row_no}: "{variant_name}" is marked as a variation of '
                    f'"{parent_name}", which is not in this file or the catalogue — skipped'
                )
                continue
            try:
                variant_price = Decimal(variant_price_raw)
            except (ValueError, InvalidOperation):
                errors.append(f'Row {row_no}: invalid price on variation "{variant_name}" — skipped')
                continue

            variant_image = (row.get('image') or '').strip()
            if variant_image and not (
                variant_image.lower().startswith(('http://', 'https://'))
                and _api_host_is_allowed(urllib.parse.urlparse(variant_image).hostname)
            ):
                # Rendered as an <img src> on customer pages — same allowlist rule
                # as every other image URL that arrives from a file.
                variant_image = ''

            ProductVariant.objects.create(
                product=parent,
                name=variant_name[:255],
                price=variant_price,
                image_url=variant_image[:500],
                sort_order=parent.variants.count(),
            )
            variants_created += 1

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
        # Image URLs in the sheet that could not be downloaded, and are therefore
        # not on the product at all. Nothing is ever kept as a CDN link — see the
        # download loop below.
        images_failed = 0
        imaged_product_ids = set()
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
                imaged_product_ids.add(product.id)
                product_map.pop(_normalize_name(product.name), None)  # Don't match by name for this product

        # Download images named by URL in the `image` column.
        #
        # `_fetch_image` is the same guarded downloader the extension's import API
        # uses: a marketplace-CDN allowlist plus a resolved-IP check, so a token or
        # a hand-edited spreadsheet cannot point this at an internal address and
        # turn the server into a proxy. A refused or unreachable URL is skipped —
        # the product is still created, it just has no photo.
        if url_images:
            from django.core.files.base import ContentFile

            from .api import _fetch_image, _host_is_allowed

            for product, url in url_images:
                # An image embedded in the sheet for this row already won; don't
                # spend a network round trip to add a second photo of the same thing.
                if product.id in imaged_product_ids:
                    continue
                fetched = _fetch_image(url)
                if fetched is None:
                    # The download failed — blocked host, no network, dead link.
                    # NOTHING is stored.
                    #
                    # This used to keep the address and let the product page
                    # hotlink it. That is unusable for this customer base: alicdn
                    # and similar CDNs are unreachable or throttled from Pakistan
                    # and much of the region, so the buyer got a broken frame
                    # while staff on a working connection saw a photo and never
                    # knew. Same rule as the extension import path in api.py.
                    images_failed += 1
                    continue
                data, img_ext = fetched
                ProductImage.objects.create(
                    product=product,
                    image=ContentFile(data, name=f'{_normalize_name(product.name)}.{img_ext}'),
                    # Provenance. `src` still prefers the local file; this only
                    # records where it came from.
                    source_url=url[:500],
                )
                images_matched += 1
                # An explicit URL wins over filename matching for this product.
                product_map.pop(_normalize_name(product.name), None)

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
        if not created and not errors:
            # Nothing imported and nothing rejected: the file parsed, but every
            # row was blank. "0 product(s) uploaded successfully" reported this
            # as a success and left no clue what to do next - and since the
            # template's examples moved to their own tab, an untouched template
            # lands here every time.
            return JsonResponse({
                'success': False,
                'created': 0,
                'errors': [],
                'message': ('No product rows found. Enter your products on the '
                            '"Products" tab \u2014 the "Example" tab is a sample and '
                            'is never imported.'),
            })
        msg = f'{created} product(s) uploaded successfully.'
        if images_matched:
            msg += f' {images_matched} image(s) matched.'
        if variants_created:
            msg += f' {variants_created} variation(s) attached to their parent product.'
        if images_failed:
            msg += (f' {images_failed} image URL(s) could not be downloaded, so those '
                    f'products have no photo from the sheet — upload one by hand or '
                    f're-push from the extension.')
        if duplicates:
            msg += f' {duplicates} duplicate(s) skipped.'
        other_errors = len(errors) - duplicates
        if other_errors:
            msg += f' {other_errors} row(s) had errors.'
        return JsonResponse({'success': True, 'created': created, 'errors': errors, 'message': msg})

    except Exception as e:
        return JsonResponse({'success': False, 'message': _friendly_upload_error(e)})


@module_required('products')
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

    # `scope: 'all'` means every product in the catalogue rather than a tick-box
    # selection. Only the margin action accepts it: raising every price is a
    # legitimate whole-catalogue operation, whereas "delete everything" or
    # "give every product the same category" are almost always a mistake and
    # stay deliberately behind an explicit selection.
    scope = data.get('scope', 'selected')
    scope_label = ''
    exclude_private = bool(data.get('exclude_private'))

    if scope in ('all', 'category') and action == 'apply_margin':
        products = Product.objects.all()

        if scope == 'category':
            # Prices are usually reviewed a category at a time — freight and
            # margin differ far more between "Power Tools" and "Photo Frames"
            # than within either — so this is the scope people actually reach for.
            category_slugs = [s for s in (data.get('category_slugs') or []) if s]
            subcategory_slugs = [s for s in (data.get('subcategory_slugs') or []) if s]
            if not category_slugs and not subcategory_slugs:
                return JsonResponse(
                    {'success': False, 'message': 'Pick at least one category.'}
                )
            selector = Q()
            if category_slugs:
                selector |= Q(category__slug__in=category_slugs)
            if subcategory_slugs:
                selector |= Q(subcategory__slug__in=subcategory_slugs)
            products = products.filter(selector)
            names = list(
                Category.objects.filter(slug__in=category_slugs).values_list('name', flat=True)
            ) + list(
                SubCategory.objects.filter(slug__in=subcategory_slugs).values_list('name', flat=True)
            )
            scope_label = ', '.join(names) if len(names) <= 3 else f'{len(names)} categories'
        else:
            scope_label = 'whole catalogue'

        # Private products are the negotiated or customer-exclusive ones. A
        # blanket percentage across the catalogue should not quietly reprice a
        # figure that was agreed with somebody.
        if exclude_private:
            products = products.exclude(is_private=True)

        count = products.count()
        if count == 0:
            return JsonResponse(
                {'success': False, 'message': 'No products matched that selection.'}
            )
    elif scope == 'filtered':
        # Everything matching the list's current filters, not just the cards on
        # screen. Selection is a DOM checkbox scan, so without this a bulk action
        # could never reach past one page — which made every action on a
        # catalogue of a few hundred products a page-at-a-time chore.
        #
        # DELETE is excluded deliberately. Every other action here is reversible
        # — republish a draft, unset a category, adjust the price back — but
        # "delete everything matching this filter" is one mistyped search away
        # from an empty catalogue, so it stays behind an explicit selection where
        # the operator has seen each row.
        if action == 'delete':
            return JsonResponse(
                {'success': False,
                 'message': 'Deleting cannot be applied to a whole filter. '
                            'Select the products you mean to delete.'},
                status=400,
            )

        products = Product.objects.all()
        search = (data.get('q') or '').strip()
        if search:
            products = products.filter(Q(name__icontains=search) | Q(sku__icontains=search))

        # set_category already owns category_slug/subcategory_slug — there they
        # name the DESTINATION. When the caller needs both meanings at once it
        # sends the filter under filter_*; reading the plain names as a filter
        # then would move products into a category by first selecting only the
        # ones already in it.
        filter_sub = (data.get('filter_subcategory_slug')
                      or ('' if action == 'set_category' else data.get('subcategory_slug'))
                      or '').strip()
        filter_cat = (data.get('filter_category_slug')
                      or ('' if action == 'set_category' else data.get('category_slug'))
                      or '').strip()
        if filter_sub:
            products = products.filter(subcategory__slug=filter_sub)
        elif filter_cat:
            products = products.filter(category__slug=filter_cat)

        # Tags narrow the same way they do on the list: a product must carry
        # EVERY tag named, so each one gets its own join. See product_list for
        # why this is not a single __in lookup.
        filter_tags = [str(s).strip() for s in (data.get('tags') or []) if str(s).strip()]
        for slug in filter_tags:
            products = products.filter(tags__slug=slug)

        # Visibility comes from the list's own filter rather than being forced
        # to public.
        #
        # This is the fix for the bug that made every whole-filter action skip
        # private products. The page counted N matching rows, offered "select
        # all N matching", and the server then quietly acted on fewer — so a
        # category applied to "all 30" landed on 24 of them with no warning.
        # Rebuilding the identical set is the only thing that makes that offer
        # honest, which is why both sides call _apply_visibility.
        visibility = (data.get('visibility') or 'all').strip().lower()
        if visibility not in VISIBILITY_FILTERS:
            visibility = 'all'
        products = _apply_visibility(products, visibility)

        # Still honoured, but it can no longer contradict the band on screen:
        # asked for the private list AND to skip private products, the filter
        # would match nothing at all.
        if exclude_private and visibility != 'private':
            products = products.exclude(is_private=True)

        # A tag filter adds a JOIN, and update()/delete() across one is fragile.
        # Collapsing to a pk subquery leaves every action below operating on the
        # products table alone, exactly as the selected-ids branch does.
        products = Product.objects.filter(pk__in=products.values('pk'))

        count = products.count()
        if count == 0:
            return JsonResponse(
                {'success': False, 'message': 'No products match the current filters.'}
            )
        described = ' · '.join(filter(None, [
            f'search "{search}"' if search else '',
            filter_sub or filter_cat or '',
            f'{len(filter_tags)} tag(s)' if filter_tags else '',
            visibility if visibility != 'all' else '',
        ])) or 'all products'
        scope_label = described[:200]
    else:
        if not ids:
            return JsonResponse({'success': False, 'message': 'No products selected'})
        products = Product.objects.filter(id__in=ids)
        if exclude_private:
            products = products.exclude(is_private=True)
        count = products.count()
        if count == 0:
            return JsonResponse({'success': False, 'message': 'No matching products found'})
        scope_label = f'{count} selected'

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

    # --- Assign a category / subcategory to everything selected ---
    #
    # Imports classify products from their name, which is a guess and is often
    # wrong or blank. Fixing that one product at a time through the edit dialog is
    # the single most tedious job on this screen.
    if action == 'set_category':
        category, subcategory = _resolve_row_category(
            data.get('category_slug'), data.get('subcategory_slug'), ''
        )
        if category is None and subcategory is None:
            return JsonResponse(
                {'success': False, 'message': 'Pick a category or subcategory first.'}
            )
        updated = products.update(category=category, subcategory=subcategory)
        label = subcategory.name if subcategory else category.name
        return JsonResponse({
            'success': True,
            'message': f'{updated} product(s) moved to {label}',
        })

    # --- Add, remove or clear tags across a whole selection ---
    #
    # This is the reason tags exist. A category holds one value per product, so
    # "these forty need photographing" or "these came from the Guangzhou
    # supplier" has nowhere to live — and setting it one product at a time
    # through the edit dialog is the job nobody actually does. Applied over a
    # filter it is a single action for the whole set.
    #
    # All three are reversible, which is why they are allowed on the whole-filter
    # scope where delete is not: a tag applied to the wrong 200 products is
    # undone by removing it from the same 200.
    if action in ('add_tags', 'remove_tags', 'clear_tags'):
        product_ids = list(products.values_list('id', flat=True))
        Through = Product.tags.through

        if action == 'clear_tags':
            removed = Through.objects.filter(product_id__in=product_ids).delete()[0]
            log_action(
                request, 'products.clear_tags',
                target=f'{count} product(s)',
                detail=f'Cleared {removed} tag assignment(s). Scope: {scope_label}',
            )
            return JsonResponse({
                'success': True,
                'message': f'Cleared {removed} tag(s) from {count} product(s)',
            })

        tag_ids = [int(t) for t in (data.get('tag_ids') or []) if str(t).isdigit()]
        tags = list(ProductTag.objects.filter(id__in=tag_ids))

        # Typing a tag that does not exist yet creates it. Tagging happens in the
        # middle of another job — you are looking at forty products and realise
        # they need a label — and being sent to a separate screen to define it
        # first is how the label ends up never being applied at all.
        if action == 'add_tags':
            for raw in list(data.get('new_tags') or [])[:20]:
                name = str(raw).strip()[:60]
                if not name:
                    continue
                # Case-insensitive, so "needs photos" does not quietly become a
                # second tag sitting beside "Needs Photos".
                tag = ProductTag.objects.filter(name__iexact=name).first()
                if tag is None:
                    palette = [c for c, _ in ProductTag.COLOUR_CHOICES]
                    tag = ProductTag.objects.create(
                        name=name,
                        colour=palette[ProductTag.objects.count() % len(palette)],
                    )
                if tag.id not in {t.id for t in tags}:
                    tags.append(tag)

        if not tags:
            return JsonResponse(
                {'success': False, 'message': 'Pick or type at least one tag.'}
            )

        names = ', '.join(t.name for t in tags)
        if action == 'add_tags':
            # ignore_conflicts leans on the (product, producttag) unique
            # constraint, so re-tagging a set that already carries the tag is a
            # no-op instead of an IntegrityError. One statement whatever the size.
            Through.objects.bulk_create(
                [Through(product_id=pid, producttag_id=t.id)
                 for pid in product_ids for t in tags],
                ignore_conflicts=True,
                batch_size=1000,
            )
            verb = 'added to'
        else:
            Through.objects.filter(
                product_id__in=product_ids,
                producttag_id__in=[t.id for t in tags],
            ).delete()
            verb = 'removed from'

        log_action(
            request, f'products.{action}',
            target=f'{count} product(s)',
            detail=f'{names} {verb} {count} product(s). Scope: {scope_label}',
        )
        return JsonResponse({
            'success': True,
            'message': f'{names} {verb} {count} product(s)',
        })

    # --- Adjust prices by a percentage, up or down ---
    #
    # A POSITIVE percentage raises prices (a margin); a NEGATIVE one lowers them
    # (a discount, or undoing a markup applied to the wrong selection).
    #
    # THIS OVERWRITES THE STORED PRICE. `price` holds what the supplier charges,
    # so after this runs the original figure is gone and cannot be recovered from
    # the row. It also does not compose the way people expect: -20% does NOT undo
    # +20%, because the second percentage applies to the already-changed number
    # (100 → 120 → 96). Both facts are stated in the confirmation dialog, and
    # every run is written to the audit log so a mistaken run can at least be
    # identified after the fact.
    #
    # Variant prices move too. For a product that sells variations the customer
    # pays the VARIANT price, so an adjustment applied only to Product.price would
    # leave every real selling price untouched.
    if action == 'apply_margin':
        try:
            margin = Decimal(str(data.get('margin')))
        except (InvalidOperation, TypeError, ValueError):
            return JsonResponse({'success': False, 'message': 'Invalid percentage'})
        if margin == 0:
            return JsonResponse(
                {'success': False, 'message': 'Enter a percentage other than zero.'}
            )
        # -100% or below would zero out or invert every price. -99% is already an
        # absurd discount; the cap is here to stop a typo, not to be useful.
        if margin <= -100 or margin > 1000:
            return JsonResponse(
                {'success': False,
                 'message': 'Percentage must be between -99 and 1000.'}
            )

        multiplier = Decimal('1') + (margin / Decimal('100'))
        variants_updated = 0
        product_ids = list(products.values_list('id', flat=True))
        # Summed before/after, so the history can answer "how much did this move"
        # in money and not only as a percentage. Read before anything is written.
        total_before = sum(
            (Decimal(str(p)) for p in products.values_list('price', flat=True)),
            Decimal('0'),
        )
        # A price of 0 would make a product free and break the order maths, so a
        # large discount on an already-cheap item floors here instead.
        floor = Decimal('0.01')

        def _adjust(value):
            return max(floor, (Decimal(str(value)) * multiplier).quantize(Decimal('0.01')))

        for product in products:
            product.price = _adjust(product.price)
            # price_air / price_sea are derived from price, so leaving them would
            # leave landed prices quoting the old cost base.
            if product.price_air is not None:
                product.price_air = _adjust(product.price_air)
            if product.price_sea is not None:
                product.price_sea = _adjust(product.price_sea)
            product.save(update_fields=['price', 'price_air', 'price_sea'])

            for variant in product.variants.all():
                variant.price = _adjust(variant.price)
                variant.save(update_fields=['price'])
                variants_updated += 1

        # '+20%' / '-15%', so the log and the toast both read unambiguously.
        signed = f'{"+" if margin > 0 else ""}{margin}%'
        direction = 'raised' if margin > 0 else 'reduced'

        total_after = sum(
            (Decimal(str(p)) for p in
             Product.objects.filter(id__in=product_ids).values_list('price', flat=True)),
            Decimal('0'),
        )

        PriceAdjustment.objects.create(
            user=request.user if request.user.is_authenticated else None,
            percentage=margin,
            scope=scope if scope in dict(PriceAdjustment.SCOPE_CHOICES) else PriceAdjustment.SCOPE_SELECTED,
            scope_label=scope_label[:200],
            products_affected=count,
            variants_affected=variants_updated,
            total_before=total_before,
            total_after=total_after,
            excluded_private=exclude_private,
        )

        log_action(
            request,
            'products.apply_margin',
            target=f'{count} product(s)',
            detail=(f'{signed} applied to {count} product price(s) and '
                    f'{variants_updated} variation price(s). Scope: {scope}. '
                    f'Product ids: '
                    f'{",".join(str(i) for i in sorted(product_ids))}'),
        )

        message = f'{count} product(s) {direction} by {signed}'
        if variants_updated:
            message += f' ({variants_updated} variation(s) too)'
        return JsonResponse({'success': True, 'message': message})

    return JsonResponse({'success': False, 'message': 'Unknown action'})


# =============================================================================
# CATEGORY MANAGEMENT
# =============================================================================
# The taxonomy used to be editable only through Django's own /admin/, which most
# of the team never opens and which sits outside this app's navigation and
# permissions model entirely. Since categories decide what customers can filter
# the catalogue by, adding one needed to be possible from the same screen the
# products are on.
# =============================================================================

@module_required('products')
def category_manage(request):
    """
    List, create, rename, reorder, deactivate and delete categories and their
    subcategories.

    Args:
        request (HttpRequest): GET renders the screen; POST performs one action
            identified by the ``action`` field and redirects back.

    Returns:
        HttpResponse: the rendered screen, or a redirect after a POST.

    Business Logic:
        Deleting a category does NOT delete its products — the FK is SET_NULL, so
        they become uncategorised and are still in the catalogue. Deactivating is
        the gentler option and is what the screen nudges towards: an inactive
        category disappears from the portal's filters and from the extension's
        dropdowns while keeping its products' assignment intact.
    """
    if request.method == 'POST':
        action = request.POST.get('action', '')
        name = (request.POST.get('name') or '').strip()

        if action == 'add_category':
            if not name:
                messages.error(request, 'Give the category a name.')
            elif Category.objects.filter(name__iexact=name).exists():
                messages.error(request, f'A category called "{name}" already exists.')
            else:
                Category.objects.create(name=name, ordering=Category.objects.count())
                messages.success(request, f'Category "{name}" added.')

        elif action == 'add_subcategory':
            parent = Category.objects.filter(id=request.POST.get('category_id')).first()
            if parent is None:
                messages.error(request, 'Pick a category to add the subcategory to.')
            elif not name:
                messages.error(request, 'Give the subcategory a name.')
            elif parent.subcategories.filter(name__iexact=name).exists():
                messages.error(request, f'"{parent.name}" already has a subcategory called "{name}".')
            else:
                SubCategory.objects.create(
                    category=parent, name=name, ordering=parent.subcategories.count()
                )
                messages.success(request, f'Subcategory "{name}" added to {parent.name}.')

        elif action == 'rename_category':
            category = Category.objects.filter(id=request.POST.get('category_id')).first()
            if category and name:
                # The slug is deliberately NOT regenerated. It is what the portal
                # filter URLs, the extension's exports and any bookmarked link all
                # key on, so renaming "Home" to "Home & Kitchen" must not silently
                # break them.
                category.name = name
                category.save(update_fields=['name'])
                messages.success(request, 'Category renamed.')

        elif action == 'rename_subcategory':
            subcategory = SubCategory.objects.filter(id=request.POST.get('subcategory_id')).first()
            if subcategory and name:
                subcategory.name = name
                subcategory.save(update_fields=['name'])
                messages.success(request, 'Subcategory renamed.')

        elif action == 'toggle_category':
            category = Category.objects.filter(id=request.POST.get('category_id')).first()
            if category:
                category.is_active = not category.is_active
                category.save(update_fields=['is_active'])
                messages.success(
                    request,
                    f'"{category.name}" {"shown" if category.is_active else "hidden"}.'
                )

        elif action == 'toggle_subcategory':
            subcategory = SubCategory.objects.filter(id=request.POST.get('subcategory_id')).first()
            if subcategory:
                subcategory.is_active = not subcategory.is_active
                subcategory.save(update_fields=['is_active'])
                messages.success(
                    request,
                    f'"{subcategory.name}" {"shown" if subcategory.is_active else "hidden"}.'
                )

        elif action == 'delete_category':
            category = Category.objects.filter(id=request.POST.get('category_id')).first()
            if category:
                label, count = category.name, category.products.count()
                category.delete()
                note = f' {count} product(s) are now uncategorised.' if count else ''
                messages.success(request, f'Category "{label}" deleted.{note}')

        elif action == 'delete_subcategory':
            subcategory = SubCategory.objects.filter(id=request.POST.get('subcategory_id')).first()
            if subcategory:
                label = subcategory.name
                subcategory.delete()
                messages.success(request, f'Subcategory "{label}" deleted.')

        return redirect('category_manage')

    categories = (
        Category.objects
        .prefetch_related('subcategories', 'products')
        .order_by('ordering', 'name')
    )
    return render(request, 'products/category_manage.html', {
        'categories': categories,
        'uncategorised_count': Product.objects.filter(category__isnull=True).count(),
    })


@module_required('products')
def price_history(request):
    """
    Every bulk price adjustment: when, by whom, over what, and how much.

    Answers the two questions a price history is for — how often prices have
    moved, and what that did to the catalogue in money rather than percentages.
    A percentage alone is not comparable across runs: +10% over eleven products
    and +10% over the whole catalogue are very different events.

    Placed orders are unaffected by any row here. OrderItem stores the unit price
    on the line at checkout, so an order raised at ¥5 stays at ¥5 no matter how
    often the product is repriced afterwards. The screen says so, because it is
    the first thing anyone wonders when they see this list.
    """
    settings = CompanySettings.get_settings()
    adjustments = PriceAdjustment.objects.select_related('user')

    paginator = Paginator(adjustments, 40)
    page_obj = paginator.get_page(request.GET.get('page'))

    totals = adjustments.aggregate(
        runs=Count('id'),
        products=Sum('products_affected'),
        variants=Sum('variants_affected'),
    )
    # Net money movement across every recorded run. Summed from the stored
    # before/after totals rather than recomputed, so a later edit to a single
    # product cannot rewrite history.
    net = sum((a.difference for a in adjustments), Decimal('0'))

    return render(request, 'products/price_history.html', {
        'settings': settings,
        'page_obj': page_obj,
        'adjustments': page_obj.object_list,
        'run_count': totals['runs'] or 0,
        'products_touched': totals['products'] or 0,
        'variants_touched': totals['variants'] or 0,
        'net_change': net,
    })


# Headers in the catalogue export, mapped to the Product field each one writes.
# Keyed on the lower-cased header text so the lookup survives someone widening
# a column or changing its capitalisation in Excel.
#
# `No.`, `Image` and `CBM/Ctn` are deliberately absent: the first two are
# presentation, and CBM is computed from the three carton dimensions, so
# accepting it would let a stale figure overwrite the numbers it is derived
# from.
CATALOGUE_IMPORT_FIELDS = {
    'price':        ('price', 'decimal'),
    'air price':    ('price_air', 'decimal'),
    'sea price':    ('price_sea', 'decimal'),
    'moq':          ('moq', 'int'),
    'weight (kg)':  ('weight', 'decimal'),
    'l (cm)':       ('carton_length', 'decimal'),
    'w (cm)':       ('carton_width', 'decimal'),
    'h (cm)':       ('carton_height', 'decimal'),
    'pcs/ctn':      ('carton_qty', 'int'),
}

# What the exporter writes where a product has no value. Read back it means
# "there was nothing here", not "clear this field".
CATALOGUE_BLANKS = {'', '-', '—', 'none', 'null', 'n/a'}


def _catalogue_cell(value, kind):
    """
    Read one spreadsheet cell as the type its column expects.

    Args:
        value: the raw cell value from openpyxl.
        kind (str): 'decimal' or 'int'.

    Returns:
        tuple[bool, object]: ``(has_value, parsed)``. ``has_value`` is False for
        a cell that should be left alone.

    Raises:
        ValueError: when the cell holds something that is not a number.

    A BLANK CELL LEAVES THE FIELD ALONE. This is the whole safety property of
    the importer: the export writes an em dash wherever a product has no weight
    or no carton size, so reading blanks as "set to null" would mean every
    round trip quietly erased the fields that were empty at export time - and a
    half-filled sheet would wipe whatever the operator had not got to yet.
    Clearing a value is therefore not something this file can do; it is done in
    the product form, where it is explicit.
    """
    if value is None:
        return False, None
    text = str(value).strip()
    if text.lower() in CATALOGUE_BLANKS:
        return False, None

    # Excel hands back numbers for numeric cells and strings for anything the
    # operator typed; both have to land in the same place. Thousands separators
    # and a stray currency symbol are what people actually paste in.
    cleaned = text.replace(',', '').replace(' ', '').strip()
    for symbol in ('AED', 'RMB', 'CNY', 'USD', '$', '¥', '£', '€'):
        cleaned = cleaned.replace(symbol, '')
    cleaned = cleaned.strip()
    if not cleaned:
        return False, None

    if kind == 'int':
        return True, int(Decimal(cleaned))
    return True, Decimal(cleaned)


@module_required('products')
def catalogue_import(request):
    """
    Update existing products from a filled-in catalogue export.

    Args:
        request (HttpRequest): POST carrying `catalogue_file`, an .xlsx saved
            from the catalogue export.

    Returns:
        JsonResponse: ``{success, updated, skipped, errors, message}``.

    WHAT THIS IS FOR

    The catalogue export is how prices and carton specs leave the system; this
    is how a revised sheet comes back. Re-pricing forty products meant opening
    forty product forms, so in practice it was done in Excel and then typed
    back in - which is where the typos came from.

    IT UPDATES, IT DOES NOT CREATE

    A row that matches nothing is reported, never inserted. Creating products
    belongs to the bulk upload, which collects the fields a new product needs
    (category, images, source) that this sheet does not carry. Silently
    creating from a catalogue file would also mean one mistyped SKU quietly
    adds a duplicate product rather than telling anyone.

    MATCHING

    SKU first, because it is the column the operator has no reason to edit;
    then the exact product name. A row whose SKU matches more than one product
    is reported rather than guessed at.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST required.'}, status=405)

    upload = request.FILES.get('catalogue_file')
    if not upload:
        return JsonResponse({'success': False, 'message': 'Choose a catalogue file to upload.'})
    if not upload.name.lower().endswith('.xlsx'):
        return JsonResponse({
            'success': False,
            'message': 'The catalogue import expects the .xlsx file produced by '
                       'Download Excel. Export the catalogue first, edit it, then '
                       'upload it here.',
        })

    try:
        from openpyxl import load_workbook

        workbook = load_workbook(filename=io.BytesIO(upload.read()), data_only=True)
        sheet = workbook.active

        # Find the header row. The export puts it at row 5 under the company
        # banner, but looking for it rather than hard-coding 5 means a sheet
        # someone has added a note to still imports.
        header_row = None
        for row_number in range(1, min(13, sheet.max_row + 1)):
            texts = [
                str(sheet.cell(row=row_number, column=c).value or '').strip().lower()
                for c in range(1, min(sheet.max_column or 1, 40) + 1)
            ]
            if 'product name' in texts or 'sku' in texts:
                header_row = row_number
                break
        if header_row is None:
            return JsonResponse({
                'success': False,
                'message': 'No header row found. This does not look like a catalogue '
                           'export - it needs the row carrying "SKU" and "Product Name".',
            })

        last_column = min(sheet.max_column or 1, 40)
        headers = {}
        for column in range(1, last_column + 1):
            text = str(sheet.cell(row=header_row, column=column).value or '').strip().lower()
            if text:
                headers[text] = column

        if 'sku' not in headers and 'product name' not in headers:
            return JsonResponse({
                'success': False,
                'message': 'That sheet has neither a SKU nor a Product Name column, '
                           'so there is no way to tell which products the rows are for.',
            })

        updatable = {
            header: (field, kind)
            for header, (field, kind) in CATALOGUE_IMPORT_FIELDS.items()
            if header in headers
        }
        if not updatable:
            return JsonResponse({
                'success': False,
                'message': 'That sheet has no columns this import can apply. A '
                           'catalogue exported without prices still carries MOQ, '
                           'weight and carton size.',
            })

        updated, unchanged, errors = 0, 0, []
        changed_fields_total = 0

        # One transaction for the whole file: a sheet that fails halfway should
        # not leave the catalogue half re-priced, with no record of where it
        # stopped.
        with transaction.atomic():
            for row_number in range(header_row + 1, sheet.max_row + 1):
                sku = str(sheet.cell(row=row_number, column=headers['sku']).value or '').strip() \
                    if 'sku' in headers else ''
                name = str(sheet.cell(row=row_number, column=headers['product name']).value or '').strip() \
                    if 'product name' in headers else ''

                if not sku and not name:
                    continue  # blank row, or the spacer under the banner

                product = None
                if sku and sku not in CATALOGUE_BLANKS:
                    matches = list(Product.objects.filter(sku__iexact=sku)[:2])
                    if len(matches) > 1:
                        errors.append(
                            f'Row {row_number}: SKU "{sku}" matches more than one '
                            'product — skipped')
                        continue
                    product = matches[0] if matches else None
                if product is None and name:
                    product = Product.objects.filter(name__iexact=name).first()

                if product is None:
                    errors.append(
                        f'Row {row_number}: no product matches '
                        f'{"SKU " + sku if sku else name[:40]} — skipped')
                    continue

                changed = []
                row_failed = False
                for header, (field, kind) in updatable.items():
                    raw = sheet.cell(row=row_number, column=headers[header]).value
                    try:
                        has_value, parsed = _catalogue_cell(raw, kind)
                    except (ValueError, ArithmeticError, InvalidOperation):
                        errors.append(
                            f'Row {row_number}: "{raw}" is not a number for '
                            f'{header} — row skipped')
                        row_failed = True
                        break
                    if not has_value:
                        continue
                    if getattr(product, field) != parsed:
                        setattr(product, field, parsed)
                        changed.append(field)

                if row_failed:
                    continue
                if changed:
                    product.save(update_fields=changed)
                    updated += 1
                    changed_fields_total += len(changed)
                else:
                    unchanged += 1

        if updated:
            message = (f'{updated} product(s) updated '
                       f'({changed_fields_total} field(s) changed).')
            if unchanged:
                message += f' {unchanged} row(s) already matched.'
        elif unchanged:
            message = (f'Nothing to change — all {unchanged} row(s) already match '
                       'the catalogue.')
        else:
            message = 'No rows could be applied. See the details below.'
        if errors:
            message += f' {len(errors)} row(s) skipped.'

        return JsonResponse({
            'success': bool(updated or unchanged),
            'updated': updated,
            'skipped': len(errors),
            'errors': errors[:50],
            'message': message,
        })

    except Exception as exc:
        return JsonResponse({'success': False, 'message': _friendly_upload_error(exc)})
