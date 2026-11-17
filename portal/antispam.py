"""
Spam scoring for the public enquiry forms.

THE PROBLEM THIS SOLVES

The contact form and the homepage sourcing form accepted any POST carrying a
name, an email and a message. No honeypot, no timing check, no rate limit. The
result was 31 spam enquiries out of 37 — 84% — each one also firing a
notification email, so the inbox that exists to catch customers was mostly
catching bots.

WHY NOT A CAPTCHA

reCAPTCHA is the reflex answer and it is the wrong one here. This business
operates from Xuzhou, and Google's services are blocked in mainland China: the
widget would fail to load for the owner testing his own form and for any
Chinese visitor, which turns a spam problem into a lost-enquiry problem. The
checks below run entirely on this server and cost the visitor nothing — no
puzzle, no third-party script, no request leaving the country.

Bots kept getting past these checks, so the forms now also carry a small
self-hosted CAPTCHA (portal/captcha.py) - generated and checked on this server,
for the same reason. It runs before this scoring; anything that passes it is
still scored here.

NOTHING IS DELETED

A high score marks the message as spam; it does not discard it. A false
positive on a real enquiry is far more expensive than a spam message sitting in
a tab nobody opens — the whole point of this inbox is that a customer bothered
to write. Flagged messages are hidden from the default list and skip the
notification email, and stay fully readable under the Spam filter.
"""

import re
from datetime import timedelta

from django.utils import timezone

# Score at or above which a message is treated as spam. Each signal below is
# worth less than this on its own, so a single quirk in a real enquiry (one
# link, or shouting) never flags it — it takes a combination.
SPAM_THRESHOLD = 5

# Link shorteners and publish-anything hosts. These carry no legitimate purpose
# in a sourcing enquiry: a customer sending a product reference sends the
# marketplace URL, not a telegra.ph page. Every spam message in the current
# inbox used telegra.ph.
BAD_LINK_DOMAINS = (
    'telegra.ph', 't.me', 'bit.ly', 'tinyurl.com', 'goo.gl', 'ow.ly',
    'is.gd', 'buff.ly', 'cutt.ly', 'rb.gy', 'shorturl.at', 'rebrand.ly',
    'telegram.me', 'bitly.com', 'tiny.cc', 'lnkd.in',
)

# The marketplaces a genuine sourcing enquiry links to. A link here is a signal
# of a REAL enquiry and cancels out the generic "contains a link" suspicion —
# "paste the product link" is something this business actively wants people to
# do, so the filter must not punish it.
GOOD_LINK_DOMAINS = (
    '1688.com', 'alibaba.com', 'aliexpress.com', 'taobao.com', 'tmall.com',
    'amazon.', 'noon.com', 'made-in-china.com', 'globalsources.com',
    'dhgate.com', 'ebay.', 'shein.com', 'temu.com',
)

# Phrases from the money-making spam genre. Matched case-insensitively as whole
# phrases rather than single words, so "income" or "earn" in an ordinary
# sentence does not trip anything.
SPAM_PHRASES = (
    'per month', 'per day', 'passive income', 'make money', 'earn money',
    'financial freedom', 'crypto', 'bitcoin', 'forex', 'binary option',
    'investment opportunity', 'work from home', 'get rich',
    'read the news', 'linear progression', 'xpress confidence',
    'seo services', 'rank your website', 'guest post', 'backlink',
    'increase your traffic', 'web design services', 'casino', 'viagra',
)

URL_RE = re.compile(r'https?://[^\s<>"\']+|www\.[^\s<>"\']+', re.IGNORECASE)
# A large number written with separators or as a run of zeros: $50,000,000.
BIG_MONEY_RE = re.compile(r'[\$€£]\s?\d[\d,.\s]{5,}|\d{1,3}(?:,\d{3}){2,}')
CYRILLIC_RE = re.compile(r'[Ѐ-ӿ]')


def _domains(text):
    """Every domain mentioned in the text, lowercased."""
    found = []
    for url in URL_RE.findall(text or ''):
        cleaned = url.lower().split('//')[-1]
        found.append(cleaned.split('/')[0].lstrip('www.'))
    return found


def score_submission(name='', email='', message='', subject='',
                     elapsed_seconds=None, honeypot='', recent_duplicate=False):
    """
    Score one enquiry. Higher is more likely to be spam.

    Args:
        name, email, message, subject (str): the submitted fields.
        elapsed_seconds (float | None): seconds between the form being served
            and submitted, or None when unknown.
        honeypot (str): the decoy field; any content means a bot filled it.
        recent_duplicate (bool): whether the same message arrived recently.

    Returns:
        tuple[int, list[str]]: the score, and the reasons behind it.

    Reasons are returned rather than just a number so the back office can show
    WHY something was flagged. A filter nobody can audit is one nobody trusts,
    and the first false positive would otherwise mean switching the whole thing
    off.
    """
    score = 0
    reasons = []
    body = f'{subject or ""}\n{message or ""}'
    lowered = body.lower()

    # --- Mechanical signals: no human produces these -----------------------

    if (honeypot or '').strip():
        score += 10
        reasons.append('hidden field was filled in')

    if elapsed_seconds is not None and elapsed_seconds < 3:
        # Nobody reads a form, types a name, an email and an enquiry in under
        # three seconds.
        #
        # Scored BELOW the threshold deliberately. Only the honeypot is
        # decisive on its own, because nothing legitimate fills it; timing is
        # inference, and a filter that rejects a real enquiry on inference
        # alone costs more than the spam it stops. In combination with any
        # other signal it still tips the balance immediately.
        score += 4
        reasons.append(f'submitted {elapsed_seconds:.1f}s after loading')

    if recent_duplicate:
        score += 6
        reasons.append('identical message already received')

    # --- Link signals -------------------------------------------------------

    domains = _domains(body)
    bad = [d for d in domains if any(b in d for b in BAD_LINK_DOMAINS)]
    good = [d for d in domains if any(g in d for g in GOOD_LINK_DOMAINS)]

    if bad:
        score += 6
        reasons.append(f'link to {bad[0]}')

    if len(domains) >= 3 and not good:
        score += 3
        reasons.append(f'{len(domains)} links')

    # A genuine product reference is evidence FOR the enquiry, so it pulls the
    # score back down. This is what stops the filter fighting the "paste a
    # product link" behaviour the business wants to encourage.
    if good:
        score -= 2
        reasons.append(f'links to {good[0]} (looks genuine)')

    # --- Content signals ----------------------------------------------------

    hits = [p for p in SPAM_PHRASES if p in lowered]
    if hits:
        score += 2 * min(len(hits), 3)
        reasons.append('phrases: ' + ', '.join(hits[:3]))

    if BIG_MONEY_RE.search(body):
        score += 2
        reasons.append('large money figure')

    letters = [c for c in body if c.isalpha()]
    if len(letters) >= 20:
        upper = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper > 0.6:
            score += 2
            reasons.append('mostly capitals')

    if CYRILLIC_RE.search(body):
        # Not spam by itself, but this business writes to the UAE, Saudi and the
        # USA in English and Arabic. Cyrillic alongside other signals is telling.
        score += 1
        reasons.append('cyrillic text')

    if name and name.lower() == (name or '').lower().replace(' ', '') and len(name) > 14:
        score += 1
        reasons.append('name has no spaces and is unusually long')

    return max(score, 0), reasons


def is_duplicate(message, within_days=14):
    """
    Whether this exact message body arrived recently.

    Args:
        message (str): the submitted body.
        within_days (int): how far back to look.

    Returns:
        bool

    The spam in the inbox arrived as the same text from several addresses, so
    the message itself is the stable identifier — not the sender. Deliberately
    an exact match on the trimmed body: anything fuzzier risks flagging two
    customers who both wrote "I need a quote for phone cases".
    """
    from portal.models import ContactMessage

    body = (message or '').strip()
    if len(body) < 25:
        # Too short to be distinctive; two people really can write the same
        # one-liner.
        return False

    cutoff = timezone.now() - timedelta(days=within_days)
    return (ContactMessage.objects
            .filter(created_at__gte=cutoff, message__startswith=body[:200])
            .exists())
