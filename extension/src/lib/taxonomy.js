/**
 * src/lib/taxonomy.js
 *
 * A snapshot of the catalogue's categories, bundled with the extension.
 *
 * WHY BUNDLE IT: the category dropdowns used to be populated only from the
 * site's /ping/ endpoint, so with no site address and token configured they
 * were empty and no category could be assigned at all — which meant the
 * category columns in every export came out blank.
 *
 * This snapshot makes the dropdowns work offline, on first install, and before
 * anything is configured. When the site IS reachable its live taxonomy replaces
 * this, so a category added on the site shows up without touching the
 * extension.
 *
 * Regenerate after changing categories on the site:
 *     python manage.py shell -c "..."   (see extension/README.md)
 */

(function (MLK) {
  'use strict';

  MLK.DEFAULT_TAXONOMY = [
    {
      "slug": "health-personal-care",
      "name": "Health & Personal Care",
      "subcategories": [
        {
          "slug": "pain-relief",
          "name": "Pain Relief"
        },
        {
          "slug": "skin-treatments",
          "name": "Skin Treatments"
        },
        {
          "slug": "nail-fungus-care",
          "name": "Nail & Fungus Care"
        },
        {
          "slug": "sprays-drops",
          "name": "Sprays & Drops"
        },
        {
          "slug": "supplements",
          "name": "Supplements"
        },
        {
          "slug": "oral-care",
          "name": "Oral Care"
        },
        {
          "slug": "fitness-massage",
          "name": "Fitness & Massage"
        }
      ]
    },
    {
      "slug": "beauty-hair-care",
      "name": "Beauty & Hair Care",
      "subcategories": [
        {
          "slug": "hair-care",
          "name": "Hair Care"
        },
        {
          "slug": "hair-removal",
          "name": "Hair Removal"
        },
        {
          "slug": "brushes",
          "name": "Brushes"
        }
      ]
    },
    {
      "slug": "games-party",
      "name": "Games & Party",
      "subcategories": [
        {
          "slug": "card-games",
          "name": "Card Games"
        }
      ]
    },
    {
      "slug": "toys-novelties",
      "name": "Toys & Novelties",
      "subcategories": [
        {
          "slug": "squishies-fidgets",
          "name": "Squishies & Fidgets"
        },
        {
          "slug": "kids-toys",
          "name": "Kids Toys"
        }
      ]
    },
    {
      "slug": "home-kitchen",
      "name": "Home & Kitchen",
      "subcategories": [
        {
          "slug": "kitchen",
          "name": "Kitchen"
        },
        {
          "slug": "home-appliances",
          "name": "Home Appliances"
        },
        {
          "slug": "sealing-machines",
          "name": "Sealing Machines"
        },
        {
          "slug": "home-essentials",
          "name": "Home Essentials"
        }
      ]
    },
    {
      "slug": "photo-frames",
      "name": "Photo Frames",
      "subcategories": []
    },
    {
      "slug": "tools-machinery",
      "name": "Tools & Machinery",
      "subcategories": [
        {
          "slug": "power-tools",
          "name": "Power Tools"
        },
        {
          "slug": "cleaning-equipment",
          "name": "Cleaning Equipment"
        }
      ]
    },
    {
      "slug": "phone-electronics",
      "name": "Phone & Electronics",
      "subcategories": [
        {
          "slug": "phone-accessories",
          "name": "Phone Accessories"
        }
      ]
    },
    {
      "slug": "pet-supplies",
      "name": "Pet Supplies",
      "subcategories": [
        {
          "slug": "pet-grooming",
          "name": "Pet Grooming"
        },
        {
          "slug": "pet-toys",
          "name": "Pet Toys"
        }
      ]
    }
  ];

  /**
   * Look up a category by slug in whichever taxonomy is active.
   * Returns null when the slug is unknown, so callers can fall back cleanly.
   */
  MLK.findCategory = function (taxonomy, slug) {
    if (!slug) return null;
    return (taxonomy || []).find(function (c) { return c.slug === slug; }) || null;
  };

  /** Human-readable name for a slug, or the slug itself when not found. */
  MLK.categoryName = function (taxonomy, slug) {
    const category = MLK.findCategory(taxonomy, slug);
    return category ? category.name : (slug || '');
  };

  /** Human-readable subcategory name within a category. */
  MLK.subcategoryName = function (taxonomy, categorySlug, subSlug) {
    const category = MLK.findCategory(taxonomy, categorySlug);
    if (!category || !subSlug) return subSlug || '';
    const sub = (category.subcategories || []).find(function (s) { return s.slug === subSlug; });
    return sub ? sub.name : subSlug;
  };
})(globalThis.MLK);

if (typeof module !== 'undefined' && module.exports) {
  module.exports = globalThis.MLK.DEFAULT_TAXONOMY;
}
