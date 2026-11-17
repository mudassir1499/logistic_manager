"""
Capture the ad platforms' click ids on the landing hit.

WHY

``fbclid`` and ``ttclid`` are appended to the landing URL by Meta and TikTok
when someone clicks an ad. They are by far the strongest signal a server-side
conversion can carry, because they name the actual click rather than trying to
infer a person from an email hash and an IP address.

They only exist on the FIRST page of the visit. By the time the visitor
reaches the contact form two pages later the query string is long gone, so
unless something stores them on the way past, every server-side conversion
goes out with nothing better than an IP address to match on.

The Meta browser pixel writes ``_fbc`` itself, but only when it loads — which
is exactly the case that server-side sending exists to cover. Writing it here
too means the click id survives even when the pixel is blocked.

COOKIE FORMAT

``_fbc`` has a shape Meta specifies: ``fb.1.<unix ms>.<fbclid>``. Inventing a
different format means the value is accepted and then matches nothing. TikTok
takes ``ttclid`` as-is.
"""

import time

# Meta's documented window for click attribution is 7 days for clicks; the
# cookie conventionally lives longer so a later conversion still carries it.
COOKIE_MAX_AGE = 90 * 24 * 60 * 60  # 90 days


class ClickIdMiddleware:
    """
    Persist ``fbclid`` / ``ttclid`` from the query string into cookies.

    Only writes when the parameter is present and no cookie exists yet, so a
    later click does not overwrite the id that actually drove the visit, and
    an ordinary page view does no cookie work at all.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        fbclid = request.GET.get('fbclid', '').strip()
        ttclid = request.GET.get('ttclid', '').strip()

        response = self.get_response(request)

        # Nothing to do on the overwhelming majority of requests.
        if not fbclid and not ttclid:
            return response

        secure = request.is_secure()

        if fbclid and not request.COOKIES.get('_fbc'):
            # Meta's required shape. A bare fbclid here is accepted by the API
            # and then matches nothing, which is the worst kind of failure:
            # silent, and it looks like it is working.
            value = 'fb.1.%d.%s' % (int(time.time() * 1000), fbclid)
            response.set_cookie(
                '_fbc', value, max_age=COOKIE_MAX_AGE,
                samesite='Lax', secure=secure,
                # Readable by JavaScript on purpose: the browser pixel reads
                # and reuses the same cookie, so the two copies of an event
                # carry the same click id.
                httponly=False,
            )

        if ttclid and not request.COOKIES.get('ttclid'):
            response.set_cookie(
                'ttclid', ttclid, max_age=COOKIE_MAX_AGE,
                samesite='Lax', secure=secure, httponly=False,
            )

        return response
