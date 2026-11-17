"""
Canonicalising supplier listing URLs.

WHY THIS EXISTS

The extension's import de-duplicated on product NAME, and that is wrong in both
directions.

It misses real duplicates. The same 1688 offer scraped twice does not
necessarily produce the same name: the extension can translate titles (see
translate.js), so scraping with translation off and then on yields two different
strings for one listing and imports it twice. Sellers also edit their titles.
This is the "it adds lots of product cards" problem - the second copy is not a
variant, it is the same offer under a different name.

It also invents duplicates that are not there. 1688 titles are long keyword
strings and two genuinely different listings from the same factory often carry
byte-identical names. Name matching silently skips the second one, and the
operator is told "1 duplicate skipped" with no way to know a real product was
dropped.

The listing URL is the right key: one offer, one id, stable across title edits
and translation. What it is not is stable as a *string* - the same offer reached
from search, from a shop page, or from a direct link carries different tracking
parameters and different hosts (detail. / m. / www.). So it has to be reduced to
a canonical form before it can be compared, which is what this module does.
"""

import re
from urllib.parse import urlsplit, urlunsplit

# 1688 offer pages are /offer/<numeric id>.html on any of several hosts. The id
# is the only durable part; everything else is routing and tracking.
_OFFER_PATH = re.compile(r'/offer/(\d+)\.html', re.IGNORECASE)

# Hosts that serve the same 1688 catalogue. m. is the mobile site, air. and
# sale. show up in shared links, and a bare 1688.com appears in pasted URLs.
_1688_HOSTS = re.compile(r'(^|\.)1688\.com$', re.IGNORECASE)

CANONICAL_1688 = 'https://detail.1688.com/offer/{}.html'


def canonical_source_url(raw):
    """
    Reduce a supplier listing URL to a form that compares equal for one listing.

    Args:
        raw (str): A URL as scraped, pasted, or stored. May be blank.

    Returns:
        str: The canonical URL, or '' when there is nothing usable.

    Examples:
        >>> canonical_source_url('https://detail.1688.com/offer/123.html?spm=a26')
        'https://detail.1688.com/offer/123.html'
        >>> canonical_source_url('https://m.1688.com/offer/123.html')
        'https://detail.1688.com/offer/123.html'
        >>> canonical_source_url('HTTP://Example.COM/Widget/?ref=x#top')
        'http://example.com/Widget'

    Non-1688 URLs are normalised but not rewritten: the host is lowercased, the
    query and fragment are dropped, and a trailing slash is removed. The path
    keeps its case because plenty of sites serve case-sensitive paths and
    lowercasing one would produce a 404 if anybody followed it.
    """
    raw = (raw or '').strip()
    if not raw:
        return ''

    # A bare "detail.1688.com/offer/1.html" has no scheme, and urlsplit would
    # read the whole thing as a path with no host at all.
    if '//' not in raw:
        raw = 'https://' + raw.lstrip('/')

    try:
        parts = urlsplit(raw)
    except ValueError:
        return ''

    host = (parts.hostname or '').lower()
    if not host:
        return ''

    if _1688_HOSTS.search(host):
        match = _OFFER_PATH.search(parts.path)
        if match:
            return CANONICAL_1688.format(match.group(1))
        # A 1688 URL that is not an offer page (a shop front, a search) has no
        # id to key on. Fall through to generic normalisation rather than
        # inventing one.

    path = parts.path.rstrip('/')
    scheme = parts.scheme.lower() or 'https'
    return urlunsplit((scheme, host, path, '', ''))


def offer_id(raw):
    """
    The 1688 offer id in a URL, or '' when it is not a 1688 offer page.

    Args:
        raw (str): Any URL.

    Returns:
        str: The numeric id as a string, e.g. '677382919274'.

    Useful for display ("offer 677382919274") and for a cheap equality test that
    does not need the whole URL rebuilt.
    """
    raw = (raw or '').strip()
    if not raw:
        return ''
    if '//' not in raw:
        raw = 'https://' + raw.lstrip('/')
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ''
    if not _1688_HOSTS.search((parts.hostname or '').lower()):
        return ''
    match = _OFFER_PATH.search(parts.path)
    return match.group(1) if match else ''
