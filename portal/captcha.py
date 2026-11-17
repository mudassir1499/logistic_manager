"""
A small self-hosted CAPTCHA for the public enquiry forms.

WHY SELF-HOSTED

Google reCAPTCHA (and hCaptcha, which loads from the same kind of CDN) is
unreliable or blocked in mainland China, where this business operates - the
widget would fail to load for the owner and for Chinese visitors, turning a
spam problem into a lost-enquiry problem. This challenge is generated and
checked entirely on this server: no third-party script, nothing leaving the
country, and it works with JavaScript switched off.

HOW IT WORKS

The form shows a simple sum ("What is 4 + 7?"). Alongside it goes a signed
token holding a random nonce and an HMAC of nonce + correct answer, keyed by
SECRET_KEY. The answer itself is never in the page, so the token cannot be
decoded to read it, and without SECRET_KEY nobody can mint a token for an
answer of their choosing.

Each token can be used once (its nonce is recorded in the cache) and expires
after a few hours, so a bot cannot solve one challenge by hand and then replay
it thousands of times.

WHAT IT DOES NOT DO

A bot written specifically for this site could read the sum and answer it.
That is not what the inbox is receiving - it is generic form-filling bots that
post to anything with a <form> - and the honeypot, timing and content checks in
portal/antispam.py still run on everything that passes this gate.
"""

import hmac
import secrets

from django.core import signing
from django.core.cache import cache
from django.utils.crypto import salted_hmac

SALT = 'portal.enquiry-captcha'

# Long enough for someone to write a detailed enquiry, short enough that a
# harvested token is useless by the time anyone could misuse it.
MAX_AGE_SECONDS = 3 * 60 * 60

# Form field names. Not configurable on purpose: the templates and the tests
# refer to them directly.
TOKEN_FIELD = 'captcha_token'
ANSWER_FIELD = 'captcha_answer'


def _digest(nonce, answer):
    return salted_hmac(SALT, f'{nonce}:{answer}').hexdigest()


def new_challenge():
    """
    A fresh question and the token that goes with it.

    Returns:
        dict: ``question`` (str, e.g. "4 + 7"), ``a`` and ``b`` (ints, for
        templates that want to phrase the sum in their own language) and
        ``token`` (str, for the hidden field).

    Addition of two single digits only: hard for nothing but a script, and
    answerable by anyone on any keyboard without thinking about it.
    """
    a = secrets.randbelow(9) + 1
    b = secrets.randbelow(9) + 1
    nonce = secrets.token_urlsafe(12)
    token = signing.dumps({'n': nonce, 'h': _digest(nonce, a + b)}, salt=SALT)
    return {'question': f'{a} + {b}', 'a': a, 'b': b, 'token': token}


def verify(token, answer):
    """
    Whether ``answer`` is the right answer for the challenge in ``token``.

    Args:
        token (str): the hidden field the form carried back.
        answer (str): what the visitor typed.

    Returns:
        bool: True exactly once per correctly answered, unexpired token.
    """
    answer = (answer or '').strip()
    if not token or not answer.isdigit() or len(answer) > 3:
        return False

    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
        nonce, expected = str(data['n']), str(data['h'])
    except (signing.BadSignature, KeyError, TypeError):
        return False

    if not hmac.compare_digest(expected, _digest(nonce, int(answer))):
        return False

    # One use per token. cache.add only writes when the key is absent, so it
    # doubles as the "seen before?" check without a race between two requests.
    # If the cache itself is unavailable the answer is still checked; only the
    # replay protection is lost, which beats refusing every real enquiry.
    try:
        return cache.add(f'captcha-used:{nonce}', 1, MAX_AGE_SECONDS)
    except Exception:                                            # noqa: BLE001
        return True
