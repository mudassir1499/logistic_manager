"""
Automatic SKU generation.

WHY THE CATALOGUE NEEDED THIS

Of 127 products, 10 had a SKU and 117 did not. The ten that did were supplier
codes carried over from the 1688 listing - "1103", "RS550", "17promax",
"999999" - which identify the product in the SUPPLIER's system, not in this
one. Two different factories can and do use the same code, and a code means
nothing to a picker in a warehouse or on an invoice line.

THE FORMAT

    <CATEGORY PREFIX>-<4-digit sequence>        e.g.  TOO-0042, HEA-0007

Category-prefixed rather than one flat sequence because the prefix is the part a
human reads: seeing HEA-0007 on a packing list tells you it is Health & Personal
Care without a lookup. The number is per-category, so each category counts from
0001 and stays short.

Uncategorised products get GEN. They still get a real SKU rather than being
skipped, because "no SKU" is the problem being solved.

PREFIXES ARE STORED, NOT DERIVED ON THE FLY

Category.sku_prefix holds it. Deriving from the name at generation time looked
simpler and is wrong: this catalogue has both "Tools And Home Improvements" and
"Tools & Machinery", and any simple derivation gives both TOO. Worse, renaming a
category would silently change the prefix and the next product would get a SKU
that no longer matches its neighbours. Stored once, it is stable and editable.
"""

import re

# Four digits allows 9,999 products per category, which this catalogue will not
# reach; the fixed width is what makes SKUs sort correctly as text.
SEQUENCE_DIGITS = 4
PREFIX_LENGTH = 3
FALLBACK_PREFIX = 'GEN'          # products with no category

_NON_ALNUM = re.compile(r'[^A-Z0-9]+')


def derive_prefix(name, taken=()):
    """
    Build a short, unique prefix from a category name.

    Args:
        name (str): The category name, e.g. "Health & Personal Care".
        taken (iterable): Prefixes already in use, so this one differs.

    Returns:
        str: An uppercase prefix of PREFIX_LENGTH characters.

    Examples:
        >>> derive_prefix('Health & Personal Care')
        'HEA'
        >>> derive_prefix('Tools & Machinery', taken={'TOO'})
        'TOM'

    Collisions are resolved by preferring the initials of the significant words
    ("Tools & Machinery" -> TOM) before falling back to numbering, because
    initials stay readable where TOO2 does not.
    """
    taken = {t.upper() for t in taken if t}
    cleaned = _NON_ALNUM.sub(' ', (name or '').upper()).strip()
    if not cleaned:
        return FALLBACK_PREFIX

    words = [w for w in cleaned.split() if w not in ('AND', 'THE', 'OF', 'FOR')]
    candidates = []

    # First choice: the opening letters of the first word.
    first = words[0] if words else cleaned
    candidates.append(first[:PREFIX_LENGTH])

    # Then the initials of the first few words, which is what distinguishes
    # two categories that begin with the same word.
    if len(words) >= 2:
        candidates.append(''.join(w[0] for w in words)[:PREFIX_LENGTH])
    if len(words) >= 2:
        candidates.append((words[0][:2] + words[1][0])[:PREFIX_LENGTH])
    if len(words) >= 3:
        candidates.append((words[0][0] + words[1][0] + words[2][0])[:PREFIX_LENGTH])

    for candidate in candidates:
        candidate = candidate.ljust(PREFIX_LENGTH, 'X')[:PREFIX_LENGTH]
        if candidate not in taken:
            return candidate

    # Everything readable is taken. Number it rather than fail.
    base = candidates[0].ljust(PREFIX_LENGTH, 'X')[:PREFIX_LENGTH]
    for n in range(2, 100):
        candidate = (base[:PREFIX_LENGTH - len(str(n))] + str(n))
        if candidate not in taken:
            return candidate
    return base


def prefix_for(product):
    """
    The SKU prefix a product should use.

    Args:
        product (Product): The product, saved or unsaved.

    Returns:
        str: The category's stored prefix, or GEN when it has no category.
    """
    category = getattr(product, 'category', None)
    if category is None:
        return FALLBACK_PREFIX
    prefix = (getattr(category, 'sku_prefix', '') or '').strip().upper()
    return prefix or FALLBACK_PREFIX


def next_sku(product, taken=None):
    """
    The next SKU for a product. Never reuses one that has been issued before.

    Args:
        product (Product): The product needing a SKU.
        taken (set | None): SKUs already handed out in this run but not yet
            written. Without it, numbering a batch in a loop would give every
            one of them the same number, because none is saved until the end.

    Returns:
        str: e.g. 'HEA-0007'.

    WHY A STORED COUNTER AND NOT max(existing)

    Reading the highest SKU in the table looks equivalent and quietly reuses
    numbers. Delete the highest-numbered product in a category and the maximum
    drops, so the next product created is handed the SKU that product had.
    Anything already printed - a packing list, an invoice line, a barcode on a
    carton in a warehouse - then points at a different item.

    SkuSequence remembers the highest number ever issued per prefix and only
    ever counts up, so a retired SKU stays retired. The increment is done with
    an F() expression inside a transaction, so two people adding a product at
    the same moment cannot both read the same value and collide.
    """
    from django.db import transaction
    from django.db.models import F

    from .models import Product, SkuSequence

    prefix = prefix_for(product)
    taken = taken if taken is not None else set()

    with transaction.atomic():
        sequence, _ = SkuSequence.objects.get_or_create(prefix=prefix)

        # An existing catalogue may already hold SKUs in this scheme from before
        # the sequence existed. Catch the counter up to them once, or the first
        # generated SKU would collide with one already in use.
        highest_in_use = 0
        pattern = prefix + '-'
        for sku in Product.objects.filter(sku__startswith=pattern).values_list('sku', flat=True):
            tail = sku[len(pattern):]
            if tail.isdigit():
                highest_in_use = max(highest_in_use, int(tail))
        if highest_in_use > sequence.last_number:
            SkuSequence.objects.filter(pk=sequence.pk).update(last_number=highest_in_use)
            sequence.last_number = highest_in_use

        while True:
            SkuSequence.objects.filter(pk=sequence.pk).update(last_number=F('last_number') + 1)
            sequence.refresh_from_db(fields=['last_number'])
            candidate = '%s-%0*d' % (prefix, SEQUENCE_DIGITS, sequence.last_number)
            # A supplier code could happen to look like ours. Step past it
            # rather than issuing a duplicate.
            if candidate in taken or Product.objects.filter(sku=candidate).exists():
                continue
            return candidate


def looks_generated(sku):
    """
    True when a SKU follows this scheme.

    Lets the backfill tell its own codes apart from supplier codes, so a re-run
    does not renumber products it already handled.
    """
    return bool(re.fullmatch(r'[A-Z0-9]{%d}-\d{%d}' % (PREFIX_LENGTH, SEQUENCE_DIGITS),
                             (sku or '').strip()))
