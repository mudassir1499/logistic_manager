"""
Server-side conversion events for Meta and TikTok.

WHY THIS EXISTS

The browser pixel is no longer a complete record. Safari's tracking
prevention, iOS App Tracking Transparency and ordinary ad blockers each drop a
share of pixel fires, and the share is largest on exactly the mobile traffic
these campaigns buy. Both platforms now weight server-reported events heavily
when deciding who to show an ad to, so a campaign running on browser events
alone is optimising on a partial, biased sample of its own conversions.

HOW IT FITS WITH THE PIXEL

Every event is sent TWICE on purpose - once by the browser via
window.trackEvent, once from here - and both copies carry the same
``event_id``. Meta and TikTok use that id to discard the duplicate and keep
whichever arrived, which is how you get the coverage of server-side sending
without double-counting. An event sent from here WITHOUT a matching event_id
would be counted as a second conversion, so the id is not optional.

MATCH QUALITY

A server event with no identifying data cannot be attributed to anyone and is
close to worthless. What raises match quality, in rough order of value:

  * ``fbc`` / ``ttclid`` - the click id the ad platform itself put in the
    landing URL. This is the strongest signal because it names the click.
  * ``fbp`` - the pixel's own browser cookie.
  * hashed email and phone.
  * IP address and user agent.

PII IS HASHED HERE, NEVER SENT RAW. Email and phone are lower-cased, stripped
and SHA-256 hashed before they leave this process, which is what both
platforms require. The raw values never appear in a payload or a log line.

FAILURE IS SILENT AND NON-BLOCKING

Sending happens on a background thread. A slow or failing ad endpoint must
never add latency to a checkout or hold a form submission open - the customer's
request is the thing that matters, and a lost analytics event is not worth a
timeout in front of them. Errors are logged, never raised.
"""

import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.request
import uuid

# urllib, not the requests library. requests is not in requirements.txt, and
# this module is imported by portal.views at load time - so an environment
# without it (every environment built from requirements.txt, production
# included) failed to import portal.views, then urls.py, and every page on the
# site returned a server error. Two JSON POSTs do not justify a dependency
# that can take the whole site down by being absent.

logger = logging.getLogger(__name__)

META_API_VERSION = 'v21.0'
META_ENDPOINT = 'https://graph.facebook.com/%s/%s/events'
TIKTOK_ENDPOINT = 'https://business-api.tiktok.com/open_api/v1.3/event/track/'

# Business event name -> (meta name, tiktok name). Mirrors the MAP in
# portal/base.html; the two must agree or the browser and server copies of the
# same action arrive under different names and never deduplicate.
EVENT_MAP = {
    'view_item': ('ViewContent', 'ViewContent'),
    'add_to_cart': ('AddToCart', 'AddToCart'),
    'begin_checkout': ('InitiateCheckout', 'InitiateCheckout'),
    'purchase': ('Purchase', 'CompletePayment'),
    'lead': ('Lead', 'SubmitForm'),
    'sign_up': ('CompleteRegistration', 'CompleteRegistration'),
    'search': ('Search', 'Search'),
    'contact': ('Contact', 'Contact'),
}

# How long to wait on the ad platform before giving up. Short on purpose: this
# runs off-thread, but a hung socket still holds a worker thread open.
TIMEOUT_SECONDS = 5


def new_event_id():
    """
    A fresh id for one conversion, shared between the browser and the server.

    Returns:
        str: a uuid4 hex string.
    """
    return uuid.uuid4().hex


def _hashed(value):
    """
    SHA-256 of a normalised identifier, or None when there is nothing to hash.

    Args:
        value (str | None): an email address or phone number.

    Returns:
        str | None: lower-case hex digest.

    Both platforms specify lower-cased and whitespace-stripped input, so a
    value hashed any other way simply fails to match and silently costs match
    quality rather than erroring.
    """
    if not value:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _digits_only(value):
    """Phone numbers match on digits alone; punctuation defeats the hash."""
    if not value:
        return None
    digits = ''.join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def _client_ip(request):
    """
    The visitor's address, preferring the proxy header.

    cPanel sits behind a proxy, so REMOTE_ADDR is the load balancer. The first
    entry in X-Forwarded-For is the client.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def gather_identity(request, email=None, phone=None):
    """
    Collect everything that can identify this visitor to an ad platform.

    Args:
        request (HttpRequest): the live request.
        email (str | None): raw email; hashed before sending.
        phone (str | None): raw phone; digits are hashed before sending.

    Returns:
        dict: the pieces found. Raw PII is NOT included — only hashes.

    The click ids are read from the cookies the middleware stores, falling back
    to the query string on the landing hit itself, because a visitor who
    converts on the first page has no cookie yet.
    """
    return {
        'em': _hashed(email),
        'ph': _hashed(_digits_only(phone)),
        'fbc': request.COOKIES.get('_fbc') or request.GET.get('fbclid') or '',
        'fbp': request.COOKIES.get('_fbp', ''),
        'ttclid': request.COOKIES.get('ttclid') or request.GET.get('ttclid') or '',
        'ttp': request.COOKIES.get('_ttp', ''),
        'ip': _client_ip(request),
        'ua': request.META.get('HTTP_USER_AGENT', ''),
        'url': request.build_absolute_uri(),
    }


def _meta_payload(event_name, event_id, identity, custom, settings, now):
    user_data = {}
    if identity.get('em'):
        user_data['em'] = [identity['em']]
    if identity.get('ph'):
        user_data['ph'] = [identity['ph']]
    if identity.get('fbc'):
        user_data['fbc'] = identity['fbc']
    if identity.get('fbp'):
        user_data['fbp'] = identity['fbp']
    if identity.get('ip'):
        user_data['client_ip_address'] = identity['ip']
    if identity.get('ua'):
        user_data['client_user_agent'] = identity['ua']

    event = {
        'event_name': event_name,
        'event_time': now,
        'event_id': event_id,
        'action_source': 'website',
        'event_source_url': identity.get('url', ''),
        'user_data': user_data,
    }
    if custom:
        event['custom_data'] = custom

    body = {'data': [event]}
    if settings.capi_test_code:
        body['test_event_code'] = settings.capi_test_code
    return body


def _tiktok_payload(event_name, event_id, identity, custom, settings, now):
    user = {}
    if identity.get('em'):
        user['email'] = identity['em']
    if identity.get('ph'):
        user['phone'] = identity['ph']
    if identity.get('ttclid'):
        user['ttclid'] = identity['ttclid']
    if identity.get('ttp'):
        user['ttp'] = identity['ttp']
    if identity.get('ip'):
        user['ip'] = identity['ip']
    if identity.get('ua'):
        user['user_agent'] = identity['ua']

    event = {
        'event': event_name,
        'event_time': now,
        'event_id': event_id,
        'user': user,
        'page': {'url': identity.get('url', '')},
    }
    if custom:
        # TikTok nests value/currency/contents under `properties`, where Meta
        # keeps them flat in custom_data. Same figures, different envelope.
        event['properties'] = custom

    body = {
        'event_source': 'web',
        'event_source_id': settings.tiktok_pixel_id,
        'data': [event],
    }
    if settings.capi_test_code:
        body['test_event_code'] = settings.capi_test_code
    return body


def _post(url, body, headers, platform):
    """POST a JSON body; log the outcome; never raise."""
    data = json.dumps(body).encode('utf-8')
    request_headers = {'Content-Type': 'application/json'}
    request_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=request_headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            logger.info('%s conversions API accepted the event (%s)', platform, response.status)
    except urllib.error.HTTPError as exc:
        # Logged at warning, not error: a rejected event is worth knowing
        # about but is not a fault in the request the customer just made.
        detail = ''
        try:
            detail = exc.read().decode('utf-8', 'replace')[:400]
        except Exception:
            pass
        logger.warning('%s conversions API returned %s: %s', platform, exc.code, detail)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning('%s conversions API unreachable: %s', platform, exc)
    except Exception:  # pragma: no cover - belt and braces on a daemon thread
        logger.exception('%s conversions API failed unexpectedly', platform)


def _send_now(business_event, identity, custom, event_id, settings):
    """
    The actual network work. Runs on a background thread.

    Wrapped whole, not just around the HTTP call. _post guards its own
    network exceptions, but payload building reads values that came from a
    form - a surprise there would otherwise kill the thread with a traceback
    and no indication which event was lost. Nothing in here is worth taking a
    thread down for.
    """
    try:
        _send_now_inner(business_event, identity, custom, event_id, settings)
    except Exception:
        logger.exception('conversions: failed to send %s', business_event)


def _send_now_inner(business_event, identity, custom, event_id, settings):
    names = EVENT_MAP.get(business_event)
    if not names:
        return
    meta_name, tiktok_name = names
    now = int(time.time())

    if settings.meta_pixel_id and settings.meta_capi_token:
        _post(
            META_ENDPOINT % (META_API_VERSION, settings.meta_pixel_id),
            _meta_payload(meta_name, event_id, identity, custom, settings, now),
            {'Authorization': 'Bearer %s' % settings.meta_capi_token},
            'Meta',
        )

    if settings.tiktok_pixel_id and settings.tiktok_capi_token:
        _post(
            TIKTOK_ENDPOINT,
            _tiktok_payload(tiktok_name, event_id, identity, custom, settings, now),
            {'Access-Token': settings.tiktok_capi_token,
             'Content-Type': 'application/json'},
            'TikTok',
        )


def send_conversion(business_event, request, email=None, phone=None,
                    custom_data=None, event_id=None, blocking=False):
    """
    Report a conversion to whichever ad platforms are configured.

    Args:
        business_event (str): one of EVENT_MAP's keys, e.g. ``'lead'``.
        request (HttpRequest): the request the conversion happened on.
        email (str | None): raw email, hashed before sending.
        phone (str | None): raw phone, hashed before sending.
        custom_data (dict | None): value, currency, content_ids and so on.
        event_id (str | None): the id the BROWSER pixel used for the same
            action. Pass it, or the platform counts two conversions instead of
            deduplicating one.
        blocking (bool): send on this thread. Only for tests — in a request
            this would put an ad platform's latency in front of the customer.

    Returns:
        str: the event_id used, so a caller that generated one can hand the
        same value to the template.

    Does nothing at all when no platform has both an id and a token, so a site
    with the pixels configured but the Conversions API not set up behaves
    exactly as it did before.
    """
    from settings_manager.models import CompanySettings

    event_id = event_id or new_event_id()

    try:
        settings = CompanySettings.get_settings()
    except Exception:
        logger.warning('conversions: settings unavailable, event dropped')
        return event_id

    meta_on = bool(settings.meta_pixel_id and settings.meta_capi_token)
    tiktok_on = bool(settings.tiktok_pixel_id and settings.tiktok_capi_token)
    if not (meta_on or tiktok_on):
        return event_id

    identity = gather_identity(request, email=email, phone=phone)
    custom = dict(custom_data or {})

    if blocking:
        _send_now(business_event, identity, custom, event_id, settings)
        return event_id

    # Daemon so a pending send never holds up a worker shutting down. The
    # event is expendable; the process is not.
    thread = threading.Thread(
        target=_send_now,
        args=(business_event, identity, custom, event_id, settings),
        daemon=True,
    )
    thread.start()
    return event_id
