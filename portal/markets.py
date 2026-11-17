"""
portal/markets.py

The countries this business sells into, and the facts about each that a landing
page can state truthfully.

WHY THIS EXISTS

Ranking in several countries is not a setting. Google decides a page is relevant
to Pakistan because the page is about Pakistan — it names the ports, the
currency, the route — not because an IP lookup swapped a flag. A single homepage
that renders differently per visitor gives the crawler nothing extra to index:
Googlebot crawls almost entirely from US addresses, so it would only ever see
one version, and the other markets would never be indexed at all.

So each market gets its own crawlable URL with its own content, and the set is
tied together with reciprocal hreflang.

WHAT IS DELIBERATELY NOT IN HERE

No transit times, no freight rates, no duty percentages. Only UAE and Saudi
Arabia have rates configured in ShippingDestination; inventing numbers for the
rest would put a promise on a public page that operations never agreed to, and
a wrong delivery estimate is the kind of thing a customer quotes back at you.
Where real rates exist the view pulls them from the database; where they do not,
the page says the shipment is quoted individually, which is true.

Everything here is a checkable fact: country names, ISO codes, the ports and
cities importers actually ship into, and the local currency.
"""

# Ordered: the markets already served first, then the ones being opened.
MARKETS = [
    {
        'slug': 'uae',
        'country': 'United Arab Emirates',
        'short': 'UAE',
        'code': 'AE',
        'hreflang': 'en-AE',
        'currency': 'AED',
        'cities': ['Dubai', 'Abu Dhabi', 'Sharjah', 'Ajman'],
        'ports': ['Jebel Ali', 'Port Khalifa'],
        'blurb': (
            'Our established lane. Sea freight consolidates into Jebel Ali and air '
            'clears through Dubai, and most of our customers are trading companies '
            'and Amazon.ae sellers restocking on a monthly cycle.'
        ),
    },
    {
        'slug': 'saudi-arabia',
        'country': 'Saudi Arabia',
        'short': 'KSA',
        'code': 'SA',
        'hreflang': 'en-SA',
        'currency': 'SAR',
        'cities': ['Riyadh', 'Jeddah', 'Dammam'],
        'ports': ['Jeddah Islamic Port', 'King Abdulaziz Port'],
        'blurb': (
            'Sea freight into Jeddah and Dammam, air into Riyadh. SABER and SASO '
            'conformity is the step that catches most first-time importers, so we '
            'check documentation requirements before goods leave the factory.'
        ),
    },
    {
        'slug': 'pakistan',
        'country': 'Pakistan',
        'short': 'Pakistan',
        'code': 'PK',
        'hreflang': 'en-PK',
        'currency': 'PKR',
        'cities': ['Karachi', 'Lahore', 'Islamabad', 'Faisalabad'],
        'ports': ['Karachi Port', 'Port Qasim'],
        'blurb': (
            'Sea freight into Karachi and Port Qasim. Most enquiries we get from '
            'Pakistan are from traders already buying in China informally and '
            'looking for someone on the ground to verify a factory before paying it.'
        ),
    },
    {
        'slug': 'united-kingdom',
        'country': 'United Kingdom',
        'short': 'UK',
        'code': 'GB',
        'hreflang': 'en-GB',
        'currency': 'GBP',
        'cities': ['London', 'Manchester', 'Birmingham', 'Felixstowe'],
        'ports': ['Felixstowe', 'Southampton', 'London Gateway'],
        'blurb': (
            'Sea freight into Felixstowe and Southampton. UK buyers are usually '
            'Amazon FBA sellers who need cartons labelled to Amazon’s spec before '
            'they leave China, which is work we do at the factory rather than after '
            'arrival.'
        ),
    },
    {
        'slug': 'usa',
        'country': 'United States',
        'short': 'USA',
        'code': 'US',
        'hreflang': 'en-US',
        'currency': 'USD',
        'cities': ['Los Angeles', 'New York', 'Houston', 'Savannah'],
        'ports': ['Los Angeles / Long Beach', 'New York / New Jersey'],
        'blurb': (
            'Sea freight into the West and East coasts. US shipments carry the most '
            'compliance load of any lane we run — FDA, CPSC and FCC rules depend '
            'entirely on what the product is, so we confirm which apply before '
            'production rather than at the border.'
        ),
    },
    {
        'slug': 'canada',
        'country': 'Canada',
        'short': 'Canada',
        'code': 'CA',
        'hreflang': 'en-CA',
        'currency': 'CAD',
        'cities': ['Toronto', 'Vancouver', 'Montreal'],
        'ports': ['Vancouver', 'Prince Rupert', 'Montreal'],
        'blurb': (
            'Sea freight into Vancouver and Prince Rupert for the west, Montreal '
            'for the east. Canadian buyers tend to order smaller, more frequent '
            'consignments, which makes consolidation worth more than it is on a '
            'full-container lane.'
        ),
    },
    {
        'slug': 'nigeria',
        'country': 'Nigeria',
        'short': 'Nigeria',
        'code': 'NG',
        'hreflang': 'en-NG',
        'currency': 'NGN',
        'cities': ['Lagos', 'Abuja', 'Port Harcourt'],
        'ports': ['Apapa', 'Tin Can Island', 'Lekki Deep Sea Port'],
        'blurb': (
            'Sea freight into Lagos. Verification matters more on this lane than '
            'any other we run: the most common thing we are asked for is proof that '
            'a factory exists and can produce, before a deposit is sent.'
        ),
    },
    {
        'slug': 'kenya',
        'country': 'Kenya',
        'short': 'Kenya',
        'code': 'KE',
        'hreflang': 'en-KE',
        'currency': 'KES',
        'cities': ['Nairobi', 'Mombasa'],
        'ports': ['Mombasa'],
        'blurb': (
            'Sea freight into Mombasa, with inland delivery to Nairobi. PVoC '
            'pre-export verification is required for most goods, so inspection is '
            'arranged in China rather than discovered on arrival.'
        ),
    },
]

MARKETS_BY_SLUG = {m['slug']: m for m in MARKETS}


def get_market(slug):
    """The market with this slug, or None."""
    return MARKETS_BY_SLUG.get((slug or '').strip().lower())


# ISO code -> slug, for turning a visitor's country into a suggestion. Used only
# to OFFER the local page, never to redirect to it — an automatic redirect means
# Googlebot (which crawls from US addresses) only ever reaches one of these
# pages, and the rest never get indexed.
SLUG_BY_COUNTRY_CODE = {m['code']: m['slug'] for m in MARKETS}
