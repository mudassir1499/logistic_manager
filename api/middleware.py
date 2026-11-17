"""
CORS for /api/v1/.

WHY THIS IS NEEDED AT ALL

A native mobile app does not care about CORS - it is a browser rule. But a web
client (a PWA, a React front end on another domain, a partner's dashboard)
cannot call this API from a browser without it, and the failure is total and
confusing: the request is sent, the server answers correctly, and the browser
throws the response away with a console message about the missing header.

WHY IT IS AN ALLOWLIST AND NOT ``*``

products/api.py answers the extension with ``Access-Control-Allow-Origin: *``,
and that is right there: those endpoints are bearer-token only, so a hostile
page copying the request still needs the token, which the browser never attaches
on its own.

This API is different. SessionAuthentication is enabled so the browsable docs
work for a logged-in staff user - which means a cookie CAN authenticate a
request here. ``*`` plus credentials is refused by browsers anyway, but relying
on that is relying on a browser rule to hold the line. An explicit allowlist,
empty by default, means cross-origin access is something somebody turned on for
a named site rather than something that was always there.

Set it with DJANGO_API_CORS_ORIGINS in .env:

    DJANGO_API_CORS_ORIGINS=https://app.mudassirllc.com,https://partner.example.com

Left unset, no cross-origin browser client can call the API - which is the
correct state until one exists.
"""

from django.conf import settings

API_PREFIX = '/api/v1/'


class ApiCorsMiddleware:
    """Add CORS headers to /api/v1/ responses for allowlisted origins."""

    def __init__(self, get_response):
        self.get_response = get_response
        # Read once at startup. These do not change without a restart, and
        # re-reading settings per request buys nothing.
        self.allowed = set(getattr(settings, 'API_CORS_ORIGINS', []) or [])

    def __call__(self, request):
        origin = request.META.get('HTTP_ORIGIN', '')
        is_api = request.path.startswith(API_PREFIX)

        # Answer the preflight ourselves. A browser sends OPTIONS before any
        # request carrying an Authorization header, and Django would route it to
        # a view that does not handle OPTIONS and return 405 - which the browser
        # reports as a CORS failure, sending people to look at the wrong thing.
        if is_api and request.method == 'OPTIONS' and origin in self.allowed:
            from django.http import HttpResponse
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        if is_api and origin and origin in self.allowed:
            response['Access-Control-Allow-Origin'] = origin
            # Vary matters: without it a cache could serve a response containing
            # one origin's header to a request from another.
            response['Vary'] = 'Origin'
            response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            response['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, PUT, DELETE, OPTIONS'
            response['Access-Control-Max-Age'] = '86400'

        return response
