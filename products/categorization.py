"""
products/categorization.py

The product taxonomy (categories and subcategories) and the keyword rules that
map a product name onto it.

WHY THIS LIVES IN ITS OWN MODULE:
    Two separate callers need the same taxonomy and the same rules:

      1. The data migration 0014, which creates the taxonomy rows and
         categorises the products that already existed when this feature
         shipped.
      2. The `categorize_products` management command, which the admin re-runs
         after adding new products.

    Keeping the rules in one place means fixing a miscategorised product is a
    one-line edit here rather than the same edit in two files that can drift
    apart.

HOW MATCHING WORKS:
    Product names in this catalogue are supplier-supplied free text, with
    inconsistent casing and a fair number of typos ("Suqishies", "Weilding",
    "Cartiage"). There is no structured attribute to key off, so we match
    keywords against the lowercased name.

    RULES is an ORDERED list and the FIRST match wins. Order is load-bearing:
    specific rules must precede general ones. "Pet Comb" has to be tested
    before the generic "comb" rule or a pet product lands in Hair Care, and
    "Shouwu Shampoo Cream" has to hit "shampoo" before the generic "cream"
    rule drops it into Skin Treatments. Each such ordering dependency is
    called out in a comment at the rule that depends on it.
"""

import re

# ---------------------------------------------------------------------------
# TAXONOMY
# ---------------------------------------------------------------------------
# Shape: (category_name, category_slug, ordering, [(sub_name, sub_slug, ordering), ...])
#
# Slugs are written out explicitly rather than derived with slugify() because
# the data migration builds these rows from historical models, which do not
# carry the custom save() that would otherwise fill the slug in.
#
# Category ordering puts the largest categories first so the portal filter bar
# leads with what customers actually browse; "Photo Frames" deliberately has no
# subcategories because splitting nine frames further would add clicks without
# adding clarity.
TAXONOMY = [
    ('Health & Personal Care', 'health-personal-care', 10, [
        ('Pain Relief', 'pain-relief', 10),
        ('Skin Treatments', 'skin-treatments', 20),
        ('Nail & Fungus Care', 'nail-fungus-care', 30),
        ('Sprays & Drops', 'sprays-drops', 40),
        ('Supplements', 'supplements', 50),
        ('Oral Care', 'oral-care', 60),
        ('Fitness & Massage', 'fitness-massage', 70),
    ]),
    ('Beauty & Hair Care', 'beauty-hair-care', 20, [
        ('Hair Care', 'hair-care', 10),
        ('Hair Removal', 'hair-removal', 20),
        ('Brushes', 'brushes', 30),
    ]),
    ('Games & Party', 'games-party', 30, [
        ('Card Games', 'card-games', 10),
    ]),
    ('Toys & Novelties', 'toys-novelties', 40, [
        ('Squishies & Fidgets', 'squishies-fidgets', 10),
        ('Kids Toys', 'kids-toys', 20),
    ]),
    ('Home & Kitchen', 'home-kitchen', 50, [
        ('Kitchen', 'kitchen', 10),
        ('Home Appliances', 'home-appliances', 20),
        ('Sealing Machines', 'sealing-machines', 30),
        ('Home Essentials', 'home-essentials', 40),
    ]),
    ('Photo Frames', 'photo-frames', 60, []),
    ('Tools & Machinery', 'tools-machinery', 70, [
        ('Power Tools', 'power-tools', 10),
        ('Cleaning Equipment', 'cleaning-equipment', 20),
    ]),
    ('Phone & Electronics', 'phone-electronics', 80, [
        ('Phone Accessories', 'phone-accessories', 10),
    ]),
    ('Pet Supplies', 'pet-supplies', 90, [
        ('Pet Grooming', 'pet-grooming', 10),
        ('Pet Toys', 'pet-toys', 20),
    ]),
]


# ---------------------------------------------------------------------------
# MATCHING RULES
# ---------------------------------------------------------------------------
# Shape: (keywords, category_slug, subcategory_slug or None)
#
# `keywords` is a tuple of plain lowercase substrings; a rule fires when ANY of
# them appears in the lowercased product name. Substring matching (rather than
# whole-word) is deliberate — it absorbs plurals and the supplier typos noted
# above without a rule per spelling.
RULES = [
    # -- Pet products -------------------------------------------------------
    # MUST precede the generic 'comb' (Hair Care) and 'toy' (Kids Toys) rules,
    # otherwise "Pet Comb" and "Dog Fun toy" are pulled into the wrong branch.
    (('pet comb', 'pet brush'), 'pet-supplies', 'pet-grooming'),
    (('dog', 'puppy', 'cat toy'), 'pet-supplies', 'pet-toys'),

    # -- Sealing machines ---------------------------------------------------
    # MUST precede the 'machine' rule under Power Tools, or the bag sealers are
    # filed as workshop tools.
    (('sealing', 'sealer'), 'home-kitchen', 'sealing-machines'),

    # -- Hair care ----------------------------------------------------------
    # 'shampoo' and 'protein connecting' MUST precede the generic 'cream' rule
    # in Skin Treatments; both these products are creams by name.
    (('shampoo', 'protein connecting', 'hair straight'), 'beauty-hair-care', 'hair-care'),
    (('wax bean', 'waxing'), 'beauty-hair-care', 'hair-removal'),
    (('comb',), 'beauty-hair-care', 'hair-care'),
    (('brush',), 'beauty-hair-care', 'brushes'),

    # -- Health: specific conditions before generic dosage forms ------------
    (('pain', 'lumber', 'patch and care'), 'health-personal-care', 'pain-relief'),
    (('fungus', 'fungi', 'mite'), 'health-personal-care', 'nail-fungus-care'),
    (('acne', 'psoriasis', 'posrias', 'eczema', 'wart', 'thai cream'),
     'health-personal-care', 'skin-treatments'),
    (('toothpaste', 'tooth'), 'health-personal-care', 'oral-care'),
    (('collagen', 'barley', 'navitas', 'prostat', 'jian qiao', 'organic'),
     'health-personal-care', 'supplements'),
    # 'south moon' covers the ear/tinnitus drops, which are drops rather than
    # sprays but belong with them as an applied-liquid remedy.
    (('spray', 'south moon', 'tinnidrop', 'drops'),
     'health-personal-care', 'sprays-drops'),
    (('resistance band', 'leg pillow', 'neck', 'shoulder', 'masager', 'massager'),
     'health-personal-care', 'fitness-massage'),
    # Generic fallback for the remaining topical creams. MUST stay after every
    # rule above that matches a product whose name also contains "cream".
    (('cream', 'ointment'), 'health-personal-care', 'skin-treatments'),

    # -- Games --------------------------------------------------------------
    # Several party games do not carry the word "cards" in their name
    # ("uno no mercy", "What Do you meme", "Do you know your Family"), so they
    # are matched by title fragment instead.
    (('card', 'uno', 'meme', 'know your family', 'strangers', 'drink'),
     'games-party', 'card-games'),

    # -- Toys ---------------------------------------------------------------
    # 'suqish' is the supplier's misspelling of squishy in "Butter Suqishies";
    # both spellings are listed rather than relying on a fuzzy match.
    (('squish', 'suqish', 'needoh', 'fidget'), 'toys-novelties', 'squishies-fidgets'),
    (('toy', 'led shuttle', 'led tablet', 'spining', 'spinning'),
     'toys-novelties', 'kids-toys'),

    # -- Tools --------------------------------------------------------------
    (('pressure washer', 'washer'), 'tools-machinery', 'cleaning-equipment'),
    # 'weilding' is the catalogue's spelling of welding; both are listed.
    (('drill', 'weilding', 'welding', 'machine'), 'tools-machinery', 'power-tools'),

    # -- Phone & electronics ------------------------------------------------
    (('phone', 'selfie', 'tpu', 'silicon cover', 'charger cable'),
     'phone-electronics', 'phone-accessories'),

    # -- Home & kitchen -----------------------------------------------------
    (('cutting board', 'kitchen', 'cloth stand'), 'home-kitchen', 'kitchen'),
    (('blanket', 'water filter', 'shoe dryer', 'dryer', 'filter'),
     'home-kitchen', 'home-appliances'),
    (('charcoal', 'bamboo'), 'home-kitchen', 'home-essentials'),

    # -- Photo frames -------------------------------------------------------
    (('frame',), 'photo-frames', None),
]

# Frame products named only by paper size ("A1 Gold", "A3 Silver", "A4 (21*29.7)")
# carry no word that any keyword rule would catch. This pattern recognises a
# leading A-series size and is tried after RULES produces no match.
FRAME_SIZE_PATTERN = re.compile(r'^\s*a[0-6]\b', re.IGNORECASE)


def classify(name):
    """
    Map a product name onto the taxonomy.

    Args:
        name (str): The raw product name, e.g. "Sumifun Patch and Care".

    Returns:
        tuple[str, str | None] | None:
            (category_slug, subcategory_slug) when a rule matches — the
            subcategory element is None for categories that have none, such as
            Photo Frames. Returns None when nothing matches, which the callers
            report rather than silently guessing at.
    """
    if not name:
        return None

    haystack = name.lower()

    for keywords, category_slug, subcategory_slug in RULES:
        for keyword in keywords:
            if keyword in haystack:
                return (category_slug, subcategory_slug)

    # Paper-size frame names are checked last so a product like "A4 Cutting
    # Board" would still be caught by its more meaningful keyword first.
    if FRAME_SIZE_PATTERN.match(name):
        return ('photo-frames', None)

    return None
