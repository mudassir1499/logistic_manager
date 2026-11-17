"""
Google Sign-In for the customer portal (OpenID Connect, authorization-code flow).

WHY THIS IS HAND-ROLLED RATHER THAN django-allauth
--------------------------------------------------
allauth is the usual answer and it is a good library. It is the wrong fit here:
this project's authentication is not Django's default. A signup creates three
linked rows (Customer business record, User login, customer-role Profile) and
sets a legacy ``session['customer_id']`` that public portal views still read.
Wiring allauth into that needs a custom SocialAccountAdapter, allauth's own
migrations, a SocialApp row or provider settings, and template overrides - more
moving parts than the flow itself, on a cPanel host where every extra pinned
dependency is another thing that can fail to install.

The flow below is the standard authorization-code flow and uses nothing outside
the standard library.

THE FLOW
--------
1. ``start()``     - send the browser to Google with a one-time ``state`` and
                     ``nonce``, both stored in the session.
2. Google          - authenticates the person and redirects back with a ``code``.
3. ``exchange_code()`` - swap that code for tokens on a direct back-channel
                     HTTPS call authenticated with the client secret.
4. ``decode_id_token()`` - read the identity claims and check every one that
                     matters before trusting them.

ON SKIPPING THE JWT SIGNATURE CHECK
-----------------------------------
The ID token is a signed JWT and this module does NOT verify that signature.
That is deliberate and it is what Google documents: when the token is obtained
directly from the token endpoint over HTTPS, with the request authenticated by
your client secret, the channel itself establishes that the token came from
Google. Signature verification exists for tokens received any other way - for
example an ID token passed from a browser - and this code never accepts one of
those.

Everything the signature would not have covered anyway is still checked
explicitly in ``decode_id_token``: issuer, audience, expiry, and the nonce that
ties the response to this specific browser session.

If this module is ever changed to accept an ID token from the front end (a
Google One Tap credential, say), that exception no longer applies and the
signature MUST be verified against Google's JWKS before anything else.
"""

import base64
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.urls import reverse

# Google's OpenID Connect endpoints. These are stable and published in Google's
# discovery document at https://accounts.google.com/.well-known/openid-configuration
AUTH_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'

# Both spellings appear in real tokens and both are legitimate.
VALID_ISSUERS = {'accounts.google.com', 'https://accounts.google.com'}

# openid gives the ID token, email gives the address, profile gives the name.
# Nothing more is requested: every extra scope is another consent checkbox and
# another thing to justify holding.
SCOPES = 'openid email profile'

SESSION_STATE = 'google_oauth_state'
SESSION_NONCE = 'google_oauth_nonce'
SESSION_NEXT = 'google_oauth_next'

# Server clocks drift. A minute of tolerance on expiry avoids rejecting a
# perfectly good token because this host is slightly ahead of Google.
CLOCK_SKEW_SECONDS = 60

# The token exchange is a blocking call in the middle of a page load. If Google
# is unreachable the person should get an error quickly, not a hung worker.
TOKEN_TIMEOUT_SECONDS = 10


class GoogleAuthError(Exception):
    """A Google sign-in attempt failed. The message is safe to show a user."""


def is_configured():
    """
    True when both halves of the OAuth client are present.

    Returns:
        bool: whether sign-in with Google can be offered at all.

    The button is hidden when this is False rather than shown and broken, so a
    deployment without credentials simply has password login.
    """
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def redirect_uri(request):
    """
    The callback URL, absolute.

    Args:
        request (HttpRequest): used to derive scheme and host.

    Returns:
        str: e.g. https://mudassirllc.com/accounts/google/callback/

    This must match a redirect URI registered in the Google Cloud console
    EXACTLY - scheme, host, port, path and trailing slash. A mismatch is the
    single most common cause of redirect_uri_mismatch, and building it from the
    request rather than hardcoding it keeps localhost and production consistent.
    """
    return request.build_absolute_uri(reverse('account_google_callback'))


def start(request, next_url=''):
    """
    Begin sign-in: mint the one-time values and build the URL to send the browser to.

    Args:
        request (HttpRequest): the current request; its session holds the secrets.
        next_url (str): where to land after a successful sign-in. Already
            validated as a safe internal path by the caller.

    Returns:
        str: the Google consent URL to redirect to.

    state and nonce do different jobs and both are needed:
      * state is CSRF protection for the callback. Without it an attacker can
        feed a victim's browser an authorization code from the attacker's own
        Google account and silently log the victim into it.
      * nonce ties the returned ID token to this sign-in attempt, so a token
        captured from an earlier one cannot be replayed.
    """
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    request.session[SESSION_STATE] = state
    request.session[SESSION_NONCE] = nonce
    request.session[SESSION_NEXT] = next_url or ''

    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': redirect_uri(request),
        'response_type': 'code',
        'scope': SCOPES,
        'state': state,
        'nonce': nonce,
        # No refresh token is wanted. This is sign-in, not ongoing access to the
        # person's Google data, so there is nothing to refresh and nothing to store.
        'access_type': 'online',
        # Show the account chooser rather than silently reusing whichever Google
        # account the browser happens to be signed into. People share machines.
        'prompt': 'select_account',
    }
    return AUTH_ENDPOINT + '?' + urllib.parse.urlencode(params)


def consume_state(request, returned_state):
    """
    Check the state Google echoed back, and clear it so it cannot be reused.

    Args:
        request (HttpRequest): holds the expected value in its session.
        returned_state (str): the ``state`` query parameter from the callback.

    Raises:
        GoogleAuthError: if it is missing or does not match.

    Popping before comparing is deliberate: it makes the value one-shot, so a
    replayed callback URL fails even if the original was valid.
    """
    expected = request.session.pop(SESSION_STATE, None)
    if not expected or not returned_state:
        raise GoogleAuthError('That sign-in link has expired. Please try again.')
    if not secrets.compare_digest(str(expected), str(returned_state)):
        raise GoogleAuthError('That sign-in request could not be verified. Please try again.')


def exchange_code(request, code):
    """
    Swap the authorization code for tokens on the back channel.

    Args:
        request (HttpRequest): used to rebuild the identical redirect_uri.
        code (str): the one-time code Google put in the callback query string.

    Returns:
        dict: Google's token response, including ``id_token``.

    Raises:
        GoogleAuthError: on any network or protocol failure.

    This call goes server-to-server over TLS and carries the client secret, so
    the browser never sees it and cannot tamper with it.
    """
    payload = urllib.parse.urlencode({
        'code': code,
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
        # Sent again and must match the one from the authorization request.
        # Google checks it; it is not redundant.
        'redirect_uri': redirect_uri(request),
        'grant_type': 'authorization_code',
    }).encode('utf-8')

    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=TOKEN_TIMEOUT_SECONDS) as response:
            body = response.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        # Google explains the failure in the body (invalid_grant for a reused or
        # expired code, redirect_uri_mismatch for a console misconfiguration).
        # It goes to the log, never to the user.
        detail = exc.read().decode('utf-8', 'replace')[:500]
        raise GoogleAuthError('Google rejected the sign-in attempt.') from Exception(detail)
    except urllib.error.URLError as exc:
        raise GoogleAuthError('Could not reach Google. Please try again.') from exc

    try:
        tokens = json.loads(body)
    except json.JSONDecodeError as exc:
        raise GoogleAuthError('Google returned an unreadable response.') from exc

    if 'id_token' not in tokens:
        raise GoogleAuthError('Google did not return an identity token.')
    return tokens


def _b64url_decode(segment):
    """Decode one base64url JWT segment, restoring the padding JWTs strip."""
    padding = '=' * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def decode_id_token(raw_token, expected_nonce):
    """
    Read the identity claims out of the ID token, checking each one that matters.

    Args:
        raw_token (str): the ``id_token`` from the token response.
        expected_nonce (str): the nonce minted in ``start()`` for this attempt.

    Returns:
        dict: {'sub', 'email', 'email_verified', 'name', 'given_name', 'family_name'}

    Raises:
        GoogleAuthError: if any check fails.

    See the module docstring for why the signature is not verified here. These
    checks are the ones that still matter, and skipping any of them is what
    turns a working integration into a broken one:

      iss  - the token really is Google's.
      aud  - it was issued for THIS application. A token minted for some other
             site would otherwise be accepted, letting that site's operator sign
             in as any of its users here.
      exp  - it has not expired.
      nonce- it belongs to this sign-in attempt and is not a replay.
      email_verified - Google has confirmed the person controls the address.
             Accounts here are matched by email, so an unverified one would let
             somebody claim an address they do not own.
    """
    parts = raw_token.split('.')
    if len(parts) != 3:
        raise GoogleAuthError('Google returned a malformed identity token.')

    try:
        claims = json.loads(_b64url_decode(parts[1]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise GoogleAuthError('Google returned an unreadable identity token.') from exc

    if claims.get('iss') not in VALID_ISSUERS:
        raise GoogleAuthError('That identity token was not issued by Google.')

    if claims.get('aud') != settings.GOOGLE_OAUTH_CLIENT_ID:
        raise GoogleAuthError('That identity token was issued for a different application.')

    try:
        expires_at = int(claims.get('exp', 0))
    except (TypeError, ValueError):
        expires_at = 0
    if expires_at + CLOCK_SKEW_SECONDS < time.time():
        raise GoogleAuthError('That sign-in took too long. Please try again.')

    if expected_nonce:
        token_nonce = claims.get('nonce')
        if not token_nonce or not secrets.compare_digest(str(token_nonce), str(expected_nonce)):
            raise GoogleAuthError('That sign-in could not be verified. Please try again.')

    email = (claims.get('email') or '').strip().lower()
    if not email:
        raise GoogleAuthError('Google did not share an email address for that account.')

    # Google sends this as a real boolean in the ID token, but Workspace tokens
    # have historically used the string "true", so accept both rather than
    # silently treating "true" as unverified.
    verified = claims.get('email_verified')
    if verified not in (True, 'true', 'True'):
        raise GoogleAuthError(
            'That Google account has an unverified email address. '
            'Verify it with Google first, or register with a password.'
        )

    return {
        'sub': claims.get('sub') or '',
        'email': email,
        'email_verified': True,
        'name': (claims.get('name') or '').strip(),
        'given_name': (claims.get('given_name') or '').strip(),
        'family_name': (claims.get('family_name') or '').strip(),
    }
