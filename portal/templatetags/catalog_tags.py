"""
portal/templatetags/catalog_tags.py

Template tags supporting the catalogue filter bar.

The filter bar has to build links that change ONE query parameter while keeping
the rest intact. Clicking a category on the marketplace must not throw away the
customer's ?source=amazon choice or the search term they just typed. Writing
that inline in a template means hard-coding every other parameter into every
link, which breaks silently as soon as a new filter is added.
"""

from django import template
from django.utils.html import format_html_join

register = template.Library()


@register.simple_tag(takes_context=True)
def catalog_query(context, **overrides):
    """
    Build a query string from the current request, with the given overrides.

    Usage in a template:
        <a href="{% catalog_query category='photo-frames' %}">Photo Frames</a>
        <a href="{% catalog_query category='' %}">All categories</a>

    Passing an empty string REMOVES that parameter, which is how the "All" and
    "clear filter" links are written.

    Returns:
        str: e.g. '?source=amazon&category=photo-frames', or '?' when no
        parameters remain — '?' rather than '' so the link still points at the
        current page with a clean query string instead of resolving to the
        browser's idea of the current URL including its existing parameters.
    """
    request = context.get('request')
    if request is None:
        return '?'

    params = request.GET.copy()

    for key, value in overrides.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value

    # Changing a filter must return to the first page; keeping the old page
    # number would land the customer on an empty page whenever the new filter
    # yields fewer results than before.
    #
    # UNLESS the caller asked for a specific page. The pagination links are built
    # with this same tag ({% catalog_query page=... %}) precisely so that "Next"
    # carries the active category, search and sort with it — and popping the key
    # unconditionally made every one of those links resolve back to page 1.
    if 'page' not in overrides:
        params.pop('page', None)

    encoded = params.urlencode()
    return f'?{encoded}' if encoded else '?'


@register.simple_tag(takes_context=True)
def catalog_hidden_inputs(context, *exclude):
    """
    Render the current query parameters as hidden <input> tags.

    The search box is a GET form, and submitting a form replaces the entire
    query string. Without these hidden fields, running a search would silently
    drop the category the customer had selected.

    Args:
        *exclude: Parameter names the form posts itself and must not duplicate
            — normally 'q', plus 'page' which is always reset on a new search.

    Returns:
        SafeString: the hidden inputs, already escaped.
    """
    request = context.get('request')
    if request is None:
        return ''

    skip = set(exclude) | {'page'}
    pairs = [
        (key, value)
        for key in request.GET
        if key not in skip
        for value in request.GET.getlist(key)
        if value
    ]
    if not pairs:
        return ''

    return format_html_join(
        '\n',
        '<input type="hidden" name="{}" value="{}">',
        pairs,
    )


@register.filter
def absolutize(url, base_url):
    """
    Turn a possibly-relative URL into an absolute one.

    Open Graph and schema.org both require absolute URLs — Facebook silently
    drops an og:image it cannot resolve, which shows up as a share card with no
    picture and no error anywhere.

    Product images are a mix: locally stored files render as '/media/…', while
    images kept as supplier CDN links are already absolute. Prefixing blindly
    would corrupt the second kind into
    'https://mudassirllc.com https://cbu01.alicdn.com/…', so the scheme is
    checked first.

    Args:
        url (str): A relative path or an absolute URL.
        base_url (str): The site's base URL, e.g. 'https://mudassirllc.com'.

    Returns:
        str: An absolute URL, or '' when there was nothing to absolutize.
    """
    text = (url or '').strip()
    if not text:
        return ''
    if text.startswith(('http://', 'https://', '//')):
        return text
    return f"{(base_url or '').rstrip('/')}/{text.lstrip('/')}"
