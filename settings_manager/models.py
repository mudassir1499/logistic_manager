"""
settings_manager/models.py

This module defines the database models for the Settings Manager app in a Django logistics management system.

The Settings Manager app stores global configuration and reference data used across the entire system.
Unlike most models where you create many rows, these models are typically singletons or small lookup tables:
- ShippingCompany: A lookup table of freight companies the logistics company works with.
- CompanySettings: A singleton (single-row) table storing the company's global configuration.

Business Context:
    A logistics company needs to know:
    - Which shipping companies offer what rates (air per KG, sea per CBM, KSA variants, battery variants)
    - What the company's own settings are (name, commission %, default shipping rates, currency, exchange rates)
    - The CompanySettings table is designed as a singleton: only one row ever exists (pk=1).
      This guarantees there's always exactly one settings record to query.
"""

# Import Django's ORM models for database field definitions
from django.db import models

# Import Decimal for precise financial calculations (currency conversions, FX rates)
from decimal import Decimal


# CURRENCY_CHOICES defines the currencies supported by the logistics business across its operating regions.
# Each tuple is (database_value, display_label). The label includes the full currency name for clarity.
# This list is used in both CompanySettings and khata/models.py for consistent currency handling.
CURRENCY_CHOICES = [
    ('AED', 'AED — UAE Dirham'),       # UAE Dirham — primary currency for UAE operations
    ('RMB', 'RMB — Chinese Yuan'),       # Chinese Yuan — used when sourcing from China
    ('USD', 'USD — US Dollar'),          # US Dollar — common for international transactions
    ('EUR', 'EUR — Euro'),               # Euro — for European trade
    ('GBP', 'GBP — British Pound'),      # British Pound — for UK trade
    ('SAR', 'SAR — Saudi Riyal'),        # Saudi Riyal — for KSA operations
]

# The glyph to print in front of a price, per currency code.
#
# Falls back to the code itself for anything unmapped, so a currency added to
# CURRENCY_CHOICES without a symbol still renders sensibly ("SAR 120.00") rather
# than showing a blank or crashing.
#
# RMB and CNY both map to ¥ — RMB is the name of the money, CNY the ISO code, and
# this project's dropdown uses RMB while other systems send CNY.
CURRENCY_SYMBOLS = {
    'RMB': '¥',
    'CNY': '¥',
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
    'AED': 'AED',
    'SAR': 'SAR',
}


class ShippingCompany(models.Model):
    """
    Represents a shipping/freight company that the logistics company uses to transport goods.

    In international logistics, the logistics company doesn't own ships or planes — it partners with
    freight forwarders and shipping companies. Each company has different rates for different routes
    and cargo types. This model stores the company details and their per-company rates.

    Attributes:
        name (str): The name of the shipping company (e.g., "DHL Freight", "Aramex", "Maersk").
        website (str, optional): URL to the company's website for reference.
        shipping_rate_sheet (FileField, optional): Uploaded Excel file with the company's rate card.
        air_rate (Decimal): Air freight rate per KG for standard cargo (0 = use global default).
        sea_rate (Decimal): Sea freight rate per CBM for standard cargo (0 = use global default).
        ksa_air_rate (Decimal): Air freight rate per KG for KSA routes (0 = use global default).
        ksa_sea_rate (Decimal): Sea freight rate per CBM for KSA routes (0 = use global default).
        nbb_air_rate (Decimal): No Brand Battery air rate per KG for UAE (0 = use global default).
        nbb_sea_rate (Decimal): No Brand Battery sea rate per CBM for UAE (0 = use global default).
        nbb_ksa_air_rate (Decimal): No Brand Battery air rate per KG for KSA (0 = use global default).
        nbb_ksa_sea_rate (Decimal): No Brand Battery sea rate per CBM for KSA (0 = use global default).

    Business Logic:
        The logistics company negotiates rates with multiple shipping companies. Each company may offer
        better rates for certain routes. If a company-specific rate is 0, the system falls back to the
        global default from CompanySettings. This allows per-company overrides without requiring every rate
        to be filled in. The rate sheet upload lets the admin store the original Excel quote from the company.
    """

    # CharField for the shipping company's name. This is required and displayed in dropdowns throughout the system.
    name = models.CharField(max_length=100, verbose_name='Shipping Company Name')

    # URLField for the company's website. Optional (blank=True). Used for quick reference or verifying contact info.
    website = models.URLField(max_length=255, blank=True, verbose_name='Website URL')

    # FileField for uploading the company's rate sheet (typically an Excel file).
    # upload_to='shipping_rate_sheets/': stores files in MEDIA_ROOT/shipping_rate_sheets/.
    # blank=True, null=True means uploading a rate sheet is optional.
    # The admin can download this file to review original quotes from the shipping company.
    shipping_rate_sheet = models.FileField(upload_to='shipping_rate_sheets/', blank=True, null=True, verbose_name='Shipping Rate Excel Sheet')

    # --- Per-company shipping rates ---
    # Each rate is a DecimalField with default=0. A value of 0 means "use the global default rate"
    # from CompanySettings instead of this company-specific rate. This design avoids duplicating
    # the global rate in every company record and makes overrides explicit.

    # Standard air freight rate per kilogram. Used for calculating air shipping costs to UAE.
    # Formula: shipping_cost = total_weight × air_rate
    air_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Air Rate per KG')

    # Standard sea freight rate per CBM (cubic meter). Used for calculating sea shipping costs to UAE.
    # Formula: shipping_cost = total_cbm × sea_rate
    sea_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Sea Rate per CBM')

    # Air freight rate per KG specifically for Saudi Arabia (KSA) routes.
    # KSA often has different routing and customs requirements, so rates may differ from UAE.
    ksa_air_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='KSA Air Rate per KG')

    # Sea freight rate per CBM specifically for Saudi Arabia (KSA) routes.
    ksa_sea_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='KSA Sea Rate per CBM')

    # No Brand Battery (NBB) air rate per KG for UAE. Batteries are hazardous goods requiring special handling.
    # Airlines charge premium rates for battery shipments, and not all carriers accept them.
    nbb_air_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='No Brand Battery Air Rate per KG')

    # No Brand Battery (NBB) sea rate per CBM for UAE. Sea freight is more accommodating for batteries than air.
    nbb_sea_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='No Brand Battery Sea Rate per CBM')

    # No Brand Battery air rate per KG for KSA routes. KSA may have additional restrictions on battery imports.
    nbb_ksa_air_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='No Brand Battery KSA Air Rate per KG')

    # No Brand Battery sea rate per CBM for KSA routes.
    nbb_ksa_sea_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='No Brand Battery KSA Sea Rate per CBM')

    # --- Air volumetric rule and minimum charges ---
    # A rate per KG is only half of an air freight price. The other half is WHICH
    # kilograms get charged, and every one of the fields above was missing it.
    #
    # Air freight bills the greater of what a shipment weighs and what it
    # "weighs" for the space it takes up:
    #
    #     volumetric kg = (length x width x height in cm) / divisor
    #
    # The divisor is the carrier's own convention. 6000 is the IATA figure;
    # express couriers commonly use 5000, which charges roughly 20% more for the
    # identical carton. It is per-company because two forwarders quoting the same
    # rate per KG are not quoting the same price if their divisors differ - and
    # that difference is exactly what a rate comparison needs to capture.
    #
    # 0 means "use the global default", matching every rate field above.
    volumetric_divisor = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='Air Volumetric Divisor',
        help_text='Divides L x W x H in cm to give volumetric kg. Usually 6000 (IATA) or 5000 '
                  '(express couriers - about 20% dearer for the same box). 0 uses the global default.',
    )

    # Minimum billable air weight. A forwarder cannot process a 0.4 kg shipment
    # for 0.4 x the rate - the paperwork and handling cost the same as for a
    # heavy one - so consignments below the minimum are charged up to it.
    min_chargeable_kg = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='Minimum Air Chargeable Weight (KG)',
        help_text='Air shipments lighter than this are billed at this weight. 0 uses the global default.',
    )

    # Minimum billable sea volume, for the same reason: a consolidator sells slots
    # in a container and cannot sell a fifth of one for a fifth of the price.
    min_cbm = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        verbose_name='Minimum Sea Volume (CBM)',
        help_text='Sea shipments smaller than this are billed at this volume. Commonly 1.000. '
                  '0 uses the global default.',
    )

    class Meta:
        """
        Meta options for the ShippingCompany model.
        """
        # Human-readable singular name in the Django admin.
        verbose_name = 'Shipping Company'

        # Human-readable plural name. Django would default to "ShippingCompanys" which is incorrect.
        verbose_name_plural = 'Shipping Companies'

        # ordering = ['name'] means shipping companies are sorted alphabetically by name.
        # This makes the dropdown list in the admin easy to navigate.
        ordering = ['name']

    def __str__(self):
        """
        Returns the name of the shipping company.

        Returns:
            str: The company name (used in admin dropdowns, order forms, and lists).
        """
        return self.name

    def has_custom_rates(self):
        """
        Checks whether this shipping company has any non-zero custom rates defined.

        Returns:
            bool: True if at least one rate field has a non-zero value, False otherwise.

        Business Logic:
            In the admin or rate comparison view, this helps quickly identify which companies
            have negotiated custom rates vs. those using global defaults. A company with all
            zero rates is effectively using the global CompanySettings rates for everything.
        """
        # any() returns True if at least one element in the list is truthy.
        # All rate fields are checked; if any has a non-zero value, the company has custom rates.
        return any([self.air_rate, self.sea_rate, self.ksa_air_rate, self.ksa_sea_rate,
                    self.nbb_air_rate, self.nbb_sea_rate, self.nbb_ksa_air_rate, self.nbb_ksa_sea_rate])


class TeamMember(models.Model):
    """
    A real person on the team, shown in "Meet Our Team" on the About page.

    Why this is a table:
        That section shipped with three people hardcoded into the template —
        a founder, a "Head of Supplier Relations" and a "Quality Control
        Manager" — illustrated with stock photographs of strangers. Two of the
        three names appear to be placeholders that were never replaced.

        That is the same problem the homepage credibility figures had, and it is
        worse here, because a named person with a job title is a specific factual
        claim about who works for you. A visitor who has been burned buying from
        China is looking for exactly this page, and a reverse image search that
        lands on a stock library is the end of the conversation.

        Rows mean the owner puts their actual colleagues in, from Settings, with
        their real photographs — and, just as importantly, that the section
        renders NOTHING until they do. An empty team section is honest; three
        invented people are not.

    Attributes:
        name (str): The person's name as they want it shown.
        role (str): Their job title.
        photo (Image): A real photograph of them.
        bio (str): Optional one-or-two lines shown under the role.
        email, linkedin_url (str): Optional contact links.
        sort_order (int): Display order; the founder usually goes first.
        is_active (bool): Untick to hide someone without deleting them.
    """

    name = models.CharField(max_length=120, verbose_name='Full Name')
    role = models.CharField(
        max_length=120, verbose_name='Job Title',
        help_text='e.g. Founder & CEO, Quality Control Manager.')
    photo = models.ImageField(
        upload_to='team/', blank=True, null=True,
        help_text='A real photograph of this person. Square works best, around '
                  '600x600. A clear phone photo beats a stock portrait — anyone '
                  'checking whether you are real will reverse image search it.')
    bio = models.CharField(
        max_length=250, blank=True, default='',
        help_text='Optional. One line on what they do or how long they have been '
                  'doing it, e.g. "Twelve years sourcing electronics in Shenzhen."')
    email = models.EmailField(
        max_length=254, blank=True, default='',
        help_text='Optional. Shown as a contact link on the card.')
    linkedin_url = models.URLField(
        max_length=255, blank=True, default='', verbose_name='LinkedIn URL',
        help_text='Optional. A real LinkedIn profile is strong evidence a person '
                  'exists, which is the whole job of this section.')
    sort_order = models.PositiveSmallIntegerField(
        default=0, help_text='Lower numbers appear first.')
    is_active = models.BooleanField(
        default=True,
        help_text='Untick to hide this person from the website without deleting them.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Team Member'
        verbose_name_plural = 'Team Members'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.name} — {self.role}'

    @property
    def initials(self):
        """
        Up to two initials, for the placeholder shown when there is no photo.

        A monogram is a better empty state than a silhouette icon: it still
        identifies the person, and it does not look like a missing image.
        """
        parts = [p for p in (self.name or '').split() if p]
        return ''.join(p[0].upper() for p in parts[:2]) or '?'


class ShippingDestination(models.Model):
    """
    A country you quote freight to.

    Why this is a table and not more columns:
        Rates started as columns on ShippingCompany - air_rate and sea_rate for
        the UAE, then ksa_air_rate and ksa_sea_rate when Saudi Arabia was added,
        then four more when battery cargo needed its own pricing. That is eight
        columns for two countries and two cargo types, and the pattern costs a
        schema migration, a form field, an export column and an import mapping
        every time either list grows. Six cargo types across three countries
        would be thirty-six columns.

        A row per country turns "add Oman" into data entry.

    Attributes:
        name (str): The country as you want it printed on a rate sheet.
        code (str): ISO 3166-1 alpha-2, e.g. 'AE'. The stable identifier.
        is_active (bool): Untick to stop quoting it without deleting its rates.
        sort_order (int): Display order; ties break alphabetically.
    """

    name = models.CharField(max_length=100, verbose_name='Destination Country')
    code = models.CharField(
        max_length=2, unique=True, verbose_name='Country Code',
        help_text='Two-letter ISO code, e.g. AE for the UAE, SA for Saudi Arabia. '
                  'This is what rate sheets are matched on when you re-import them, '
                  'so it must not change once rates exist.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Untick to stop offering this destination in the calculator and on '
                  'new rate sheets. Existing rates are kept.',
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0, help_text='Lower numbers appear first.')

    class Meta:
        verbose_name = 'Shipping Destination'
        verbose_name_plural = 'Shipping Destinations'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f'{self.name} ({self.code})'


class CargoType(models.Model):
    """
    A category of goods that carries its own freight rate.

    Freight is not priced per product, it is priced per category, because what
    the carrier cares about is handling and risk rather than what the thing is.
    A branded phone case and an unbranded one weigh the same and cost different
    amounts to fly: the branded one can be held at customs over trademark
    paperwork, and anything with a lithium cell in it is dangerous goods.

    These are rows rather than a choices list so that adding a category is data
    entry rather than a migration - the list genuinely grows as forwarders
    introduce new categories.

    Attributes:
        name (str): Printed on rate sheets and shown to customers.
        slug (str): The stable key. Renaming `name` must not orphan rates.
        is_active (bool): Untick to retire a category without deleting rates.
        sort_order (int): Display order.
        customer_selectable (bool): Whether it appears in the public calculator.
        description (str): Help text shown beside the option.
    """

    name = models.CharField(max_length=80, verbose_name='Cargo Type')
    slug = models.SlugField(
        max_length=80, unique=True,
        help_text='Stable identifier, e.g. non-branded-battery. Used to match rate '
                  'sheets on re-import - changing it orphans existing rates.',
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    customer_selectable = models.BooleanField(
        default=True, verbose_name='Offer in the public calculator',
        help_text='Untick for categories you price internally but do not want '
                  'visitors choosing from the website calculator.',
    )
    description = models.CharField(
        max_length=200, blank=True, default='',
        help_text='One line shown under the option, e.g. "Power banks, cordless tools, '
                  'anything containing a lithium cell."',
    )

    class Meta:
        verbose_name = 'Cargo Type'
        verbose_name_plural = 'Cargo Types'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class ShippingRate(models.Model):
    """
    One forwarder's price for one cargo type, to one country, by one method.

    This is the row a freight forwarder fills in. Everything that decides the
    price of that lane lives here, not just the rate: a rate per KG is
    meaningless without knowing which kilograms are charged, and two forwarders
    quoting the same figure on different divisors are not quoting the same price.

    Attributes:
        company, destination, cargo_type: what this rate is for.
        method (str): 'air' or 'sea'.
        rate (Decimal): per KG for air, per CBM for sea.
        minimum (Decimal): minimum billable KG (air) or CBM (sea). 0 inherits.
        volumetric_divisor (Decimal): air only. 0 inherits from the company.
        transit_days (str): free text, e.g. '5-8' - forwarders quote ranges.
        notes (str): anything the forwarder wrote in the Notes column.

    A missing row means the forwarder does not price that lane. That is
    deliberately different from a rate of zero, which would win every
    comparison and show the customer free shipping.
    """

    METHOD_AIR = 'air'
    METHOD_SEA = 'sea'
    METHOD_CHOICES = [
        (METHOD_AIR, 'Air Freight'),
        (METHOD_SEA, 'Sea Freight'),
    ]

    company = models.ForeignKey(
        ShippingCompany, on_delete=models.CASCADE, related_name='rates')
    destination = models.ForeignKey(
        ShippingDestination, on_delete=models.CASCADE, related_name='rates')
    cargo_type = models.ForeignKey(
        CargoType, on_delete=models.CASCADE, related_name='rates')
    method = models.CharField(max_length=3, choices=METHOD_CHOICES)

    rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Per KG for air freight, per CBM for sea freight.')
    minimum = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        verbose_name='Minimum Charge',
        help_text='Minimum billable weight in KG (air) or volume in CBM (sea). '
                  '0 falls back to the company, then the global default.')
    volumetric_divisor = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Air only. Divides L x W x H in cm to give volumetric kg. '
                  '0 falls back to the company, then the global default.')
    transit_days = models.CharField(
        max_length=30, blank=True, default='',
        help_text='As quoted, e.g. "5-8" or "30-40".')
    notes = models.CharField(max_length=250, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Shipping Rate'
        verbose_name_plural = 'Shipping Rates'
        ordering = ['company__name', 'destination__sort_order', 'method',
                    'cargo_type__sort_order']
        constraints = [
            # One rate per lane. Without this an import that ran twice would
            # leave two rows for the same lane and the comparison would silently
            # depend on which one the query happened to return first.
            models.UniqueConstraint(
                fields=['company', 'destination', 'cargo_type', 'method'],
                name='uniq_rate_per_lane',
            ),
        ]
        indexes = [
            # The calculator's only query: every rate for one lane, cheapest first.
            models.Index(fields=['destination', 'cargo_type', 'method'],
                         name='idx_rate_lane'),
        ]

    def __str__(self):
        unit = 'KG' if self.method == self.METHOD_AIR else 'CBM'
        return (f'{self.company.name} - {self.destination.code} '
                f'{self.get_method_display()} {self.cargo_type.name}: {self.rate}/{unit}')

    def save(self, *args, **kwargs):
        """Persist, then mirror onto the legacy column if this is one of the eight."""
        super().save(*args, **kwargs)
        sync_legacy_rate_columns(self.company)


class ShippingRateSheet(models.Model):
    """
    A rate request workbook that was generated for a forwarder.

    Kept so that "what did we send them, and when?" has an answer. A forwarder
    who returns a sheet three weeks later may be filling in a version that
    predates a cargo type being added, and the record of what was issued is what
    makes that diagnosable rather than mysterious.

    Attributes:
        company: who it was for.
        method (str): 'air' or 'sea' - the two are separate documents.
        workbook (File): the generated .xlsx.
        generated_at (datetime): when.
        imported_at (datetime): when a filled copy was last read back, if ever.
    """

    company = models.ForeignKey(
        ShippingCompany, on_delete=models.CASCADE, related_name='rate_sheets')
    method = models.CharField(max_length=3, choices=ShippingRate.METHOD_CHOICES)
    workbook = models.FileField(upload_to='shipping_rate_sheets/')
    generated_at = models.DateTimeField(auto_now_add=True)
    imported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Rate Request Sheet'
        verbose_name_plural = 'Rate Request Sheets'
        ordering = ['-generated_at']

    def __str__(self):
        return f'{self.company.name} {self.get_method_display()} ({self.generated_at:%Y-%m-%d})'


# The eight (destination, cargo slug, method) lanes that existed as columns on
# ShippingCompany before rates became rows.
#
# orders/views.py still reads those columns directly when pricing an order, in
# three places, one of which builds the field name from a string. Rewriting that
# is a separate job with its own risk, so the columns are kept in step instead:
# edit a rate anywhere and the legacy column follows.
#
# This is a bridge, not a design. When the order flow reads ShippingRate, delete
# this function, the eight columns, and this comment.
LEGACY_RATE_COLUMNS = {
    ('AE', 'general', 'air'): 'air_rate',
    ('AE', 'general', 'sea'): 'sea_rate',
    ('SA', 'general', 'air'): 'ksa_air_rate',
    ('SA', 'general', 'sea'): 'ksa_sea_rate',
    ('AE', 'non-branded-battery', 'air'): 'nbb_air_rate',
    ('AE', 'non-branded-battery', 'sea'): 'nbb_sea_rate',
    ('SA', 'non-branded-battery', 'air'): 'nbb_ksa_air_rate',
    ('SA', 'non-branded-battery', 'sea'): 'nbb_ksa_sea_rate',
}


def sync_legacy_rate_columns(company):
    """
    Copy the eight legacy lanes from ShippingRate back onto the company columns.

    Args:
        company (ShippingCompany): the company whose columns to refresh.

    Returns:
        list[str]: the column names that changed.

    Order pricing still reads those columns. Without this, a rate edited through
    the new rate sheets would change what the website quotes and leave what the
    order screen charges untouched - the two would disagree, and nothing would
    say so.
    """
    if company is None or company.pk is None:
        return []

    current = {
        (r.destination.code, r.cargo_type.slug, r.method): r.rate
        for r in ShippingRate.objects.filter(company=company)
                                     .select_related('destination', 'cargo_type')
    }

    changed = []
    for key, column in LEGACY_RATE_COLUMNS.items():
        value = current.get(key, Decimal('0'))
        if getattr(company, column) != value:
            setattr(company, column, value)
            changed.append(column)

    if changed:
        # update_fields so this cannot disturb anything else being edited on the
        # same row, and so it stays cheap when called per saved rate.
        company.save(update_fields=changed)
    return changed


class CompanySettings(models.Model):
    """
    Represents the global settings for the logistics company.

    This is a SINGLETON model — there should only ever be ONE row in this table (pk=1).
    The get_settings() class method ensures this singleton behavior by creating the row if it doesn't exist.
    All other parts of the system query CompanySettings.get_settings() to read configuration.

    Attributes:
        company_name (str): The legal/business name shown on invoices, emails, and the website.
        company_phone (str): Main contact phone number.
        company_address (str): Full business address for invoices and legal documents.
        commission_percentage (Decimal): Default commission rate applied to orders (e.g., 5.00 = 5%).
        air_shipping_rate (Decimal): Global default air rate per KG for UAE standard cargo.
        sea_shipping_rate (Decimal): Global default sea rate per KG for UAE standard cargo.
        ksa_shipping_rate (Decimal): Global default KSA shipping rate per KG.
        ksa_air_shipping_rate (Decimal): Global default KSA air rate per KG.
        ksa_sea_shipping_rate (Decimal): Global default KSA sea rate per KG.
        no_brand_battery_air_shipping_rate (Decimal): Global UAE NBB air rate per KG.
        no_brand_battery_sea_shipping_rate (Decimal): Global UAE NBB sea rate per KG.
        no_brand_battery_ksa_air_shipping_rate (Decimal): Global KSA NBB air rate per KG.
        no_brand_battery_ksa_sea_shipping_rate (Decimal): Global KSA NBB sea rate per KG.
        currency (str): Default currency for the system (e.g., 'AED').
        exchange_rate_enabled (bool): Whether to show an exchange rate conversion on invoices.
        exchange_rate_from (str): The "from" currency for the exchange rate display.
        exchange_rate_to (str): The "to" currency for the exchange rate display.
        exchange_rate (Decimal): The conversion rate (e.g., 1.95 means 1 FROM = 1.95 TO).

    Business Logic:
        This model stores everything that is "company-wide" rather than per-order or per-customer.
        When a new order is created, the system reads the default commission percentage and shipping rates
        from this model. The admin can update these settings once, and all future orders use the new values.
        The exchange rate feature is useful for international customers who want to see prices in their
        local currency alongside the base currency.
    """

    # Company name displayed on invoices, quotes, emails, and the website footer/header.
    # Default is 'My Company' so the system works out of the box before the admin configures it.
    company_name = models.CharField(max_length=255, default='My Company')

    # Main contact phone number for the business. Optional (blank=True).
    company_phone = models.CharField(max_length=50, blank=True)

    # WhatsApp business number for customer chat. Optional (blank=True).
    # If empty, the WhatsApp floating button will fall back to company_phone.
    whatsapp_number = models.CharField(max_length=50, blank=True, verbose_name='WhatsApp Number')

    # =============================================================================
    # PRODUCT SHARING
    # =============================================================================
    # What gets copied, or handed to the phone's share sheet, when someone uses
    # the Share buttons on a product page. Sharing a bare URL asks the recipient
    # to click before they know what it is or who sent it; a line of context and
    # a number to reply to is the difference between a link and a pitch.
    #
    # These are settings rather than template text because they are marketing
    # copy: the marketplaces served will change, and changing them should not
    # need a developer, a deploy, and a static-file rebuild.
    # =============================================================================
    share_pitch = models.CharField(
        max_length=200,
        blank=True,
        # Plain ASCII on purpose. This default is written by a migration, and
        # `migrate` runs BEFORE fix_db_collation in the deploy order — on a
        # database whose columns are still latin1 a non-ASCII default is either
        # rejected or silently mangled. Anything typed into Settings afterwards
        # can use whatever characters it likes.
        default='Available for Amazon UAE, KSA and USA - shipped direct from China',
        verbose_name='Product share tagline',
        help_text='One line added under the product name when a product is shared. '
                  'Leave blank to share just the name and the link.',
    )

    share_contact = models.CharField(
        max_length=50,
        blank=True,
        default='+8617651652712',
        verbose_name='Product share contact number',
        help_text='Shown in the shared message so the recipient can reply directly. '
                  'Leave blank to fall back to the WhatsApp number, then the company phone.',
    )

    # =============================================================================
    # SOCIAL MEDIA LINKS
    # =============================================================================
    # These URLs are displayed in the website footer and used in structured data.
    # Leave blank to hide a particular social network.
    # =============================================================================
    facebook_url = models.URLField(max_length=255, blank=True, verbose_name='Facebook URL',
                                   help_text='Full Facebook page URL.')
    instagram_url = models.URLField(max_length=255, blank=True, verbose_name='Instagram URL',
                                    help_text='Full Instagram profile URL.')
    linkedin_url = models.URLField(max_length=255, blank=True, verbose_name='LinkedIn URL',
                                   help_text='Full LinkedIn company/page URL.')
    twitter_url = models.URLField(max_length=255, blank=True, verbose_name='X (Twitter) URL',
                                  help_text='Full X/Twitter profile URL.')
    youtube_url = models.URLField(max_length=255, blank=True, verbose_name='YouTube URL',
                                  help_text='Full YouTube channel URL.')
    tiktok_url = models.URLField(max_length=255, blank=True, verbose_name='TikTok URL',
                                 help_text='Full TikTok profile URL.')
    whatsapp_channel_url = models.URLField(max_length=255, blank=True, verbose_name='WhatsApp Channel URL',
                                           help_text='WhatsApp channel/community invite URL.')

    # Full business address. Used on invoices, shipping documents, and legal forms.
    # TextField allows unlimited length for multi-line addresses.
    company_address = models.TextField(blank=True)

    # Default commission percentage applied to all orders. DecimalField with 2 decimal places.
    # Example: 5.00 means the logistics company adds a 5% commission on top of the product cost.
    # Individual orders can override this, but this is the default.
    commission_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                                verbose_name='Commission %')

    # --- Global default shipping rates ---
    # These are the fallback rates used when a ShippingCompany has rate=0 for a particular method.
    # The admin sets these once and they apply to all orders unless a specific company overrides them.

    # Global default air shipping rate per KG for standard cargo to UAE.
    # Formula: air_cost = total_weight × air_shipping_rate
    air_shipping_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                            verbose_name='Air Shipping Rate per KG')

    # Global default sea shipping rate per KG for standard cargo to UAE.
    # Note: while sea freight is typically per CBM, this model stores it per KG for some calculations.
    sea_shipping_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                            verbose_name='Sea Shipping Rate per KG')

    # Global default KSA shipping rate per KG.
    ksa_shipping_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                            verbose_name='KSA Shipping Rate per KG')

    # Global default KSA air shipping rate per KG.
    ksa_air_shipping_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                verbose_name='KSA Air Shipping Rate per KG')

    # Global default KSA sea shipping rate per KG.
    ksa_sea_shipping_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                verbose_name='KSA Sea Shipping Rate per KG')

    # --- No Brand Battery (NBB) global rates ---
    # Batteries require special handling and different (usually higher) rates.
    # These are the global defaults for battery shipments.

    # UAE No Brand Battery air rate per KG.
    no_brand_battery_air_shipping_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                             verbose_name='UAE No Brand Battery Air Rate per KG')

    # UAE No Brand Battery sea rate per KG.
    no_brand_battery_sea_shipping_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                             verbose_name='UAE No Brand Battery Sea Rate per KG')

    # KSA No Brand Battery air rate per KG.
    no_brand_battery_ksa_air_shipping_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                                 verbose_name='KSA No Brand Battery Air Rate per KG')

    # KSA No Brand Battery sea rate per KG.
    no_brand_battery_ksa_sea_shipping_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                                 verbose_name='KSA No Brand Battery Sea Rate per KG')

    # --- Global air volumetric rule and minimum charges ---
    # The fallbacks behind the matching ShippingCompany fields. Set once here and
    # a forwarder only needs its own value when it actually differs.
    #
    # 6000 is the IATA divisor and the right default: it is the more generous of
    # the two common conventions, so a company that has not been configured yet
    # under-quotes rather than over-quotes, and an under-quote is caught when the
    # real rate sheet is entered rather than after a customer has been billed.
    volumetric_divisor = models.DecimalField(
        max_digits=10, decimal_places=2, default=6000,
        verbose_name='Default Air Volumetric Divisor',
        help_text='Divides L x W x H in cm to give volumetric kg. 6000 is the IATA standard; '
                  'express couriers often use 5000. Individual companies can override this.',
    )
    min_chargeable_kg = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='Default Minimum Air Chargeable Weight (KG)',
        help_text='Air shipments lighter than this are billed at this weight. 0 disables the minimum.',
    )
    min_cbm = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        verbose_name='Default Minimum Sea Volume (CBM)',
        help_text='Sea shipments smaller than this are billed at this volume. Commonly 1.000. '
                  '0 disables the minimum.',
    )

    # Default currency for the entire system. Used when displaying prices and on invoices.
    # The choices restrict this to the supported currencies defined in CURRENCY_CHOICES.
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='AED',
                                verbose_name='Currency')

    # Boolean flag controlling whether an exchange rate line is shown on invoices.
    # When True, the invoice shows: "Exchange Rate: 1 AED = 1.95 RMB" or similar.
    # Useful for international customers who want to see conversion to their local currency.
    exchange_rate_enabled = models.BooleanField(default=False,
                                                verbose_name='Show Exchange Rate on Invoice')

    # The "from" currency for the exchange rate display. Default is AED (UAE Dirham).
    exchange_rate_from = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='AED',
                                          verbose_name='Exchange Rate: From Currency')

    # The "to" currency for the exchange rate display. Default is RMB (Chinese Yuan).
    # This is useful because many suppliers are in China and customers may want to see RMB equivalents.
    exchange_rate_to = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='RMB',
                                        verbose_name='Exchange Rate: To Currency')

    # The actual exchange rate value. max_digits=12, decimal_places=6 allows very precise rates.
    # Example: if exchange_rate = 1.952500, then 1 AED = 1.952500 RMB.
    # 6 decimal places are needed because some currency pairs have very small rates.
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6, default=0,
                                        verbose_name='Exchange Rate (1 FROM = ? TO)')

    # =============================================================================
    # MULTI-CURRENCY FX RATES
    # =============================================================================
    # fx_rates stores a JSON object mapping currency codes to exchange rates
    # relative to the base currency (the `currency` field above).
    # Example: {"USD": "3.67", "EUR": "4.12", "RMB": "1.95", "GBP": "4.75", "SAR": "0.98"}
    # This enables the customer portal to display prices in multiple currencies.
    # =============================================================================
    fx_rates = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='FX Rates (JSON)',
        help_text="JSON object mapping currency codes to rates relative to base currency. Example: {'USD': '3.67', 'EUR': '4.12'}"
    )

    # =============================================================================
    # EMAIL CONFIGURATION
    # =============================================================================
    # These settings control how the system sends transactional emails to customers
    # (order confirmations, shipping notifications, delivery updates).
    # If SMTP is not configured, the system falls back to Django's console backend
    # for development and debugging.
    # =============================================================================

    # The "From" email address shown in outgoing emails. This is what customers see
    # when they receive an order confirmation or shipping notification.
    email_from_address = models.EmailField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='From Email Address',
        help_text='The email address shown as the sender in all outgoing emails. Example: orders@mudassirllc.com'
    )

    # SMTP server hostname for sending emails. Common values: smtp.gmail.com, mail.example.com
    # Leave blank to use Django's console backend (prints emails to the terminal instead of sending).
    email_smtp_host = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='SMTP Host',
        help_text='The SMTP server hostname. Leave blank to use console backend for development.'
    )

    # SMTP server port. Common values: 25 (unencrypted), 587 (TLS), 465 (SSL)
    email_smtp_port = models.PositiveIntegerField(
        default=587,
        verbose_name='SMTP Port',
        help_text='The SMTP server port. Common values: 587 (TLS) or 465 (SSL).'
    )

    # SMTP username for authentication. Often the same as the from email address.
    email_smtp_user = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='SMTP Username',
        help_text='The username for SMTP authentication. Often the same as the From Email Address.'
    )

    # SMTP password for authentication. Stored as plain text (not ideal for production,
    # but acceptable for this logistics application where the admin controls the server).
    # In production, use environment variables or Django's password field encryption.
    email_smtp_password = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='SMTP Password',
        help_text='The password for SMTP authentication. Use an app-specific password if available.'
    )

    # Whether to use TLS (Transport Layer Security) when connecting to the SMTP server.
    # True for port 587, False for port 25 or 465 (which uses SSL instead).
    email_use_tls = models.BooleanField(
        default=True,
        verbose_name='Use TLS',
        help_text='Enable TLS encryption for SMTP connections. Recommended for port 587.'
    )

    # =============================================================================
    # SECURITY SMTP PROFILE
    # =============================================================================
    # Used for security-sensitive emails: customer registration, login alerts,
    # password reset, and account notifications.
    # =============================================================================
    security_email_from_address = models.EmailField(
        max_length=255,
        blank=True,
        default='security@mudassirllc.com',
        verbose_name='Security Email From Address',
        help_text='Sender address for security/login/password-reset emails. Example: security@mudassirllc.com'
    )
    security_email_smtp_host = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Security SMTP Host',
        help_text='SMTP server for security emails. Leave blank to use the order-status SMTP server.'
    )
    security_email_smtp_port = models.PositiveIntegerField(
        default=587,
        verbose_name='Security SMTP Port',
        help_text='SMTP port for security emails. Common values: 587 (TLS) or 465 (SSL).'
    )
    security_email_smtp_user = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Security SMTP Username',
        help_text='SMTP username for security emails.'
    )
    security_email_smtp_password = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Security SMTP Password',
        help_text='SMTP password for security emails.'
    )
    security_email_use_tls = models.BooleanField(
        default=True,
        verbose_name='Security SMTP Use TLS',
        help_text='Enable TLS for the security SMTP connection.'
    )

    # =============================================================================
    # NEWS SMTP PROFILE
    # =============================================================================
    # Used for marketing/announcement emails: new Amazon/Noon products, catalog
    # updates, and company news.
    # =============================================================================
    news_email_from_address = models.EmailField(
        max_length=255,
        blank=True,
        default='news@mudassirllc.com',
        verbose_name='News Email From Address',
        help_text='Sender address for product/news announcements. Example: news@mudassirllc.com'
    )
    news_email_smtp_host = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='News SMTP Host',
        help_text='SMTP server for news emails. Leave blank to use the order-status SMTP server.'
    )
    news_email_smtp_port = models.PositiveIntegerField(
        default=587,
        verbose_name='News SMTP Port',
        help_text='SMTP port for news emails. Common values: 587 (TLS) or 465 (SSL).'
    )
    news_email_smtp_user = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='News SMTP Username',
        help_text='SMTP username for news emails.'
    )
    news_email_smtp_password = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='News SMTP Password',
        help_text='SMTP password for news emails.'
    )
    news_email_use_tls = models.BooleanField(
        default=True,
        verbose_name='News SMTP Use TLS',
        help_text='Enable TLS for the news SMTP connection.'
    )

    # Custom email template content for order confirmation emails.
    # If left blank, the system uses the default template in templates/emails/order_confirmation.html.
    email_template_confirmation = models.TextField(
        blank=True,
        default='',
        verbose_name='Order Confirmation Email Template',
        help_text='Custom HTML/template content for order confirmation emails. Leave blank to use the default template.'
    )

    # Custom email template content for order shipped notifications.
    email_template_shipped = models.TextField(
        blank=True,
        default='',
        verbose_name='Order Shipped Email Template',
        help_text='Custom HTML/template content for order shipped notifications. Leave blank to use the default template.'
    )

    # Custom email template content for order delivered notifications.
    email_template_delivered = models.TextField(
        blank=True,
        default='',
        verbose_name='Order Delivered Email Template',
        help_text='Custom HTML/template content for order delivered notifications. Leave blank to use the default template.'
    )

    # =============================================================================
    # META ADS / TRACKING CONFIGURATION
    # =============================================================================
    # meta_pixel_id stores the Facebook/Meta Pixel ID used for conversion tracking
    # on ad campaigns. When set, the pixel base code is injected into every public
    # page and conversion events fire on key actions (contact, register, quote).
    # =============================================================================
    meta_pixel_id = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='Meta (Facebook) Pixel ID',
        help_text='Your Meta Pixel ID (e.g., 123456789012345). Leave blank to disable tracking.'
    )

    # TikTok's equivalent. Kept as its own field rather than reusing the Meta one
    # because the two platforms are switched on and off independently - an
    # advertiser very often runs Meta for months before testing TikTok, and a
    # shared field would mean pasting an id that silently breaks the other tag.
    tiktok_pixel_id = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='TikTok Pixel ID',
        help_text='Your TikTok Pixel ID from TikTok Ads Manager > Assets > Events '
                  '(e.g. CABC1D2E3F4G5H6I7J8K). Leave blank to disable TikTok tracking.'
    )

    # Server-side conversion reporting (utils/conversions.py). Added by migration
    # 0031; the columns exist in every database that has run it, so they must
    # stay on the model - without them Django never fills these NOT NULL columns
    # and creating the settings row fails.
    meta_capi_token = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='Meta Conversions API token',
        help_text='Events Manager > your dataset > Settings > Generate access token. '
                  'Leave blank to send browser events only.',
    )
    tiktok_capi_token = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='TikTok Events API token',
        help_text='TikTok Ads Manager > Assets > Events > Manage > Generate access token. '
                  'Leave blank to send browser events only.',
    )
    capi_test_code = models.CharField(
        max_length=64, blank=True, default='',
        verbose_name='Conversions API test code',
        help_text='Optional. While set, events are flagged as test traffic so they appear in '
                  'the platform test tool and do NOT affect optimisation. Clear it once you '
                  'have confirmed events arrive.',
    )

    # =============================================================================
    # GOOGLE SEARCH & ANALYTICS CONFIGURATION
    # =============================================================================
    # These two fields drive the Google side of the public site:
    #
    #   google_analytics_id      - The GA4 Measurement ID ("G-XXXXXXXXXX"). When set,
    #                              the gtag.js snippet is injected into every public
    #                              page and pageviews/conversions are reported to
    #                              Google Analytics 4. Blank disables tracking
    #                              entirely, so no half-configured tag ever ships.
    #   google_site_verification - The token from the Search Console "HTML tag"
    #                              verification method. It is rendered as
    #                              <meta name="google-site-verification"> in <head>,
    #                              which is how Google confirms we own the domain.
    #                              It must stay on the site forever — removing it
    #                              un-verifies the property and cuts off Search
    #                              Console data.
    #
    # Both live in the database (not in code) so the business owner can rotate them
    # from /settings/ without a redeploy.
    # =============================================================================
    google_analytics_id = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='Google Analytics 4 Measurement ID',
        help_text='Your GA4 Measurement ID (e.g., G-ABC1234XYZ). Leave blank to disable Google Analytics.'
    )

    google_site_verification = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Google Search Console Verification Token',
        help_text='The content value from the Search Console "HTML tag" method. Paste only the token, not the whole <meta> tag.'
    )

    # =============================================================================
    # HOMEPAGE CREDIBILITY FIGURES
    # =============================================================================
    # The homepage used to hard-code eight statistics: "500+ Products Sourced",
    # "98% Quality Pass Rate", "200+ Verified Suppliers", "4.8/5 Client Rating",
    # "150+ Active Importers", "7+ Years in China", "100% Payment Protection",
    # "24/7 Client Support". None of them came from anywhere — they were template
    # placeholders that shipped as if they were facts.
    #
    # That is a problem twice over. Commercially, the visitor is someone who has
    # been burned buying from China before and is actively scanning for reasons to
    # distrust you; round unsourced numbers read as marketing filler and undercut
    # the specific, verifiable claims around them. Legally, publishing figures you
    # cannot substantiate is a consumer-protection risk in most markets.
    #
    # These fields replace them. Every one is OPTIONAL and every one defaults to
    # empty, and the template renders a figure ONLY when it has been filled in. So
    # the site ships with no unverified claims at all, and the owner adds real
    # numbers — ones they can back up — from Settings when they have them.
    #
    # They are CharFields rather than integers on purpose: "7+", "150+" and "under
    # 24h" are all legitimate values, and forcing them into numbers would mean
    # inventing a precision that does not exist.
    # =============================================================================
    stat_years_in_china = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='Years operating in China',
        help_text='e.g. "7+". Leave blank to hide this figure from the homepage.'
    )
    stat_products_sourced = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='Products sourced',
        help_text='e.g. "500+". Only enter a number you could evidence if a client asked. Blank hides it.'
    )
    stat_verified_suppliers = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='Verified suppliers',
        help_text='e.g. "200+". Factories you have actually visited and vetted. Blank hides it.'
    )
    stat_active_clients = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='Active clients',
        help_text='e.g. "150+". Businesses currently ordering through you. Blank hides it.'
    )
    stat_response_time = models.CharField(
        max_length=40,
        blank=True,
        default='24 hours',
        verbose_name='Quote response time',
        help_text='e.g. "24 hours". This is a promise you make, so keep it one you can keep. Blank hides it.'
    )

    # =============================================================================
    # BRANDING
    # =============================================================================
    logo = models.ImageField(
        upload_to='branding/',
        blank=True,
        null=True,
        verbose_name='Company Logo',
        help_text='Recommended 512×512 px (square), PNG with a transparent background, under 200 KB. '
                  'Used in the website header and footer, on invoices and packing lists, and as the '
                  'logo Google shows beside your search listing. Leave empty to use the built-in mark.'
    )
    logo_wide = models.ImageField(
        upload_to='branding/',
        blank=True,
        null=True,
        verbose_name='Wide Logo (optional)',
        help_text='Recommended 600×160 px, PNG with a transparent background. A horizontal '
                  'logo-plus-name lockup for document headers. Falls back to the square logo.'
    )

    # =============================================================================
    # SITE IDENTITY
    # =============================================================================
    # site_url replaces the domain that was hardcoded in 99 places across templates
    # and Python — canonical tags, Open Graph URLs, every JSON-LD block, robots.txt
    # and the sitemap. Changing domain, adding a "www." prefix or running a staging
    # copy previously meant editing all of them, and the ones that were missed
    # failed silently (Google simply indexed the wrong address).
    # =============================================================================
    site_url = models.CharField(
        max_length=255,
        blank=True,
        default='https://mudassirllc.com',
        verbose_name='Website Address',
        help_text='Full public address with https:// and NO trailing slash, e.g. https://mudassirllc.com. '
                  'Used to build canonical links, sitemap entries and social share URLs.'
    )

    # =============================================================================
    # BUSINESS PROFILE (used in the structured data Google reads)
    # =============================================================================
    # These were hardcoded inside the JSON-LD in base.html, so changing your opening
    # hours meant editing a template and Google kept serving the old ones until then.
    # =============================================================================
    business_city = models.CharField(
        max_length=100, blank=True, default='Xuzhou',
        verbose_name='City', help_text='City your office is in. Shown to Google as your business location.'
    )
    business_region = models.CharField(
        max_length=100, blank=True, default='Jiangsu',
        verbose_name='Province / State'
    )
    business_country = models.CharField(
        max_length=2, blank=True, default='CN',
        verbose_name='Country Code',
        help_text='Two-letter country code, e.g. CN for China, AE for the UAE.'
    )
    opening_time = models.CharField(
        max_length=5, blank=True, default='09:00',
        verbose_name='Opening Time', help_text='24-hour format, e.g. 09:00.'
    )
    closing_time = models.CharField(
        max_length=5, blank=True, default='18:00',
        verbose_name='Closing Time', help_text='24-hour format, e.g. 18:00.'
    )
    working_days = models.CharField(
        max_length=120, blank=True,
        default='Monday,Tuesday,Wednesday,Thursday,Friday,Saturday',
        verbose_name='Working Days',
        help_text='Comma-separated English day names. Only these are published to Google.'
    )
    languages_spoken = models.CharField(
        max_length=120, blank=True, default='en,ar,ur,zh',
        verbose_name='Languages Spoken',
        help_text='Comma-separated two-letter codes, e.g. en,ar,ur,zh. Tells Google which '
                  'languages your team can serve customers in.'
    )

    # =============================================================================
    # INVOICING
    # =============================================================================
    # The invoice template previously printed only the company name, address, phone
    # and currency. That is not enough to be a valid tax invoice in the UAE, and it
    # gave the customer no way to actually pay — every payment had to start with a
    # message asking for bank details.
    # =============================================================================
    tax_registration_number = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='Tax Registration Number (TRN)',
        help_text='Your UAE TRN. A tax invoice must show it for a VAT-registered customer to '
                  'reclaim input tax. Leave blank if you are not VAT-registered — it is then hidden.'
    )
    vat_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name='VAT Percentage',
        help_text='e.g. 5.00 for the UAE standard rate. Leave at 0 to omit VAT from invoices entirely.'
    )

    bank_name = models.CharField(max_length=150, blank=True, default='', verbose_name='Bank Name')
    bank_account_name = models.CharField(
        max_length=150, blank=True, default='', verbose_name='Account Holder Name',
        help_text='Must match the name on the account exactly, or transfers get rejected.'
    )
    bank_account_number = models.CharField(max_length=64, blank=True, default='', verbose_name='Account Number')
    bank_iban = models.CharField(max_length=64, blank=True, default='', verbose_name='IBAN')
    bank_swift = models.CharField(max_length=32, blank=True, default='', verbose_name='SWIFT / BIC')
    bank_branch = models.CharField(max_length=150, blank=True, default='', verbose_name='Branch')

    PAYMENT_TERMS_CHOICES = [
        ('due_on_receipt', 'Due on receipt'),
        ('net_7', 'Net 7 days'),
        ('net_15', 'Net 15 days'),
        ('net_30', 'Net 30 days'),
        ('net_45', 'Net 45 days'),
        ('net_60', 'Net 60 days'),
    ]
    default_payment_terms = models.CharField(
        max_length=20, choices=PAYMENT_TERMS_CHOICES, default='due_on_receipt',
        verbose_name='Default Payment Terms',
        help_text='Prints a due date on invoices, and defines what counts as overdue on the dashboard.'
    )

    invoice_prefix = models.CharField(
        max_length=20, blank=True, default='INV-',
        verbose_name='Invoice Number Prefix',
        help_text='e.g. "INV-" or "MLC-2026-". Combined with a running number to give each invoice a '
                  'stable reference. Invoices currently show the raw database ID, which is not sequential.'
    )
    next_invoice_number = models.PositiveIntegerField(
        default=1,
        verbose_name='Next Invoice Number',
        help_text='The number the next invoice will take. Assigned once and then frozen on that order, '
                  'so an invoice reference never changes after it has been sent.'
    )
    invoice_number_padding = models.PositiveSmallIntegerField(
        default=4,
        verbose_name='Number Padding',
        help_text='Zero-pad the running number to this many digits. 4 gives INV-0001.'
    )
    invoice_terms = models.TextField(
        blank=True, default='',
        verbose_name='Invoice Terms & Notes',
        help_text='Printed at the foot of every invoice — deposit policy, inspection terms, '
                  'late-payment conditions. Leave blank to omit the section.'
    )

    # =============================================================================
    # OPERATIONS
    # =============================================================================
    lead_notification_email = models.CharField(
        max_length=500, blank=True, default='',
        verbose_name='Send New Enquiry Alerts To',
        help_text='Comma-separated addresses notified the moment a website enquiry arrives. '
                  'Leave blank to fall back to the Security email sender.'
    )
    quote_validity_days = models.PositiveSmallIntegerField(
        default=14,
        verbose_name='Quote Validity (days)',
        help_text='How long a quotation stays valid. Freight rates move, so an open-ended quote '
                  'can bind you to last season\'s prices.'
    )
    default_deposit_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=30,
        verbose_name='Default Deposit (%)',
        help_text='Deposit normally taken before production starts. Used to suggest a figure on new orders.'
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=0,
        verbose_name='Low Stock Threshold',
        help_text='Flag a product when its quantity falls to or below this. 0 disables the warning.'
    )
    stale_shipment_days = models.PositiveSmallIntegerField(
        default=10,
        verbose_name='Flag shipments with no movement after (days)',
        help_text='A shipment whose status has not changed in this many days is '
                  'listed on the dashboard as needing attention. Sea consolidations '
                  'legitimately sit still for a while, so tune this to how you '
                  'actually ship. 0 turns the warning off.',
    )
    order_cutoff_time = models.CharField(
        max_length=5, blank=True, default='',
        verbose_name='Daily Order Cut-off',
        help_text='24-hour time, e.g. 16:00. Orders placed after it are handled the next working day. '
                  'Leave blank if you do not work to a cut-off.'
    )

    # =============================================================================
    # THIRD-PARTY WIDGETS
    # =============================================================================
    tawk_widget_id = models.CharField(
        max_length=120, blank=True, default='',
        verbose_name='Tawk.to Widget ID',
        help_text='The path from your Tawk.to embed code, e.g. 6a46bc264b956a1d4cbbc178/1jsi4ttv4. '
                  'Leave blank to remove live chat from the site entirely.'
    )

    # og_image is used as the default social sharing image for Meta/Facebook/LinkedIn.
    # Page-specific images can override this in templates.
    og_image = models.ImageField(
        upload_to='og_images/',
        blank=True,
        null=True,
        verbose_name='Default Social Share Image (OG Image)',
        help_text='Recommended size 1200x630 pixels. Used when sharing pages on Facebook, WhatsApp, LinkedIn, etc.'
    )

    class Meta:
        """
        Meta options for the CompanySettings model.
        """
        # Human-readable names for the Django admin interface.
        verbose_name = 'Company Settings'
        verbose_name_plural = 'Company Settings'

    def __str__(self):
        """
        Returns a human-readable identifier for this settings record.

        Returns:
            str: A string like "Settings: My Company" showing this is the company settings row.
        """
        return f"Settings: {self.company_name}"

    @classmethod
    def get_settings(cls):
        """
        Class method that returns the singleton CompanySettings instance, creating it if necessary.

        The @classmethod decorator means this method is called on the class itself, not on an instance:
        CompanySettings.get_settings() instead of settings.get_settings().

        Returns:
            CompanySettings: The single settings record (pk=1).

        Business Logic:
            This is a singleton pattern implementation. The logistics company has exactly one set of settings,
            so there should be exactly one row in this table. get_or_create(pk=1) ensures:
            - If the row exists, it is returned.
            - If it doesn't exist, a new row with default values and pk=1 is created and returned.
            The underscore (_) ignores the boolean flag indicating whether it was created or fetched.

        Why pk=1?
            By convention, the settings row always has primary key 1. This makes it easy to reference
            and ensures there's never confusion about which row to use. Views and templates call
            CompanySettings.get_settings() to get the current configuration without hardcoding IDs.
        """
        # get_or_create() is a Django ORM convenience method. It tries to fetch the object with pk=1.
        # If it doesn't exist, it creates a new one with the default field values.
        # It returns a tuple: (object, created_boolean). We use _ to ignore the boolean.
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    # -------------------------------------------------------------------------
    # Derived helpers
    # -------------------------------------------------------------------------

    @property
    def payment_terms_days(self):
        """
        Number of days the default payment term allows.

        Returns:
            int: 0 for "due on receipt", otherwise the net-N day count.

        Used to print a due date on invoices and to decide what counts as overdue
        on the dashboard — which previously assumed a flat 30 days because there
        was nothing to read.
        """
        if self.default_payment_terms.startswith('net_'):
            try:
                return int(self.default_payment_terms.split('_')[1])
            except (IndexError, ValueError):
                return 0
        return 0

    @property
    def working_days_list(self):
        """Working days as a clean list, for the opening-hours structured data."""
        return [d.strip() for d in (self.working_days or '').split(',') if d.strip()]

    @property
    def languages_list(self):
        """Spoken languages as a clean list of codes."""
        return [c.strip() for c in (self.languages_spoken or '').split(',') if c.strip()]

    @property
    def currency_symbol(self):
        """
        The glyph to print in front of a price — '¥' for RMB, '$' for USD, and so on.

        Templates use this instead of the raw code so that changing the currency in
        Settings changes every price display at once. Unmapped currencies fall back
        to their own code, which reads fine ("SAR 120.00") and never renders blank.
        """
        return CURRENCY_SYMBOLS.get((self.currency or '').upper(), self.currency or '')

    @property
    def currency_code(self):
        """
        The ISO 4217 code for the configured currency.

        Structured data, payment processors and accounting exports all require the
        ISO code — not the symbol, and not a colloquial name. 'RMB' is what this
        project's dropdown calls the Chinese yuan and what people say out loud, but
        the ISO code is 'CNY'; emitting 'RMB' (or worse, '¥') in schema.org markup
        makes Google discard the whole offer.
        """
        code = (self.currency or '').upper()
        return {'RMB': 'CNY'}.get(code, code)

    @property
    def whatsapp_digits(self):
        """
        The WhatsApp number reduced to the digits wa.me expects.

        wa.me refuses anything but a bare international number — no '+', spaces,
        brackets or dashes — so a number stored in a human-readable form has to be
        stripped before it can be used in a link. Falls back to the main company
        phone, matching what the floating WhatsApp button already does.

        Returns:
            str: e.g. '971501234567', or '' when neither number is configured.
        """
        import re as _re
        raw = (self.whatsapp_number or '').strip() or (self.company_phone or '').strip()
        return _re.sub(r'\D', '', raw)

    @property
    def share_preview(self):
        """
        The share message as it will actually look, for the Settings screen.

        Built from the same method the product pages call rather than a
        hand-written example, so the preview cannot describe something the
        buttons do not do.
        """
        return self.build_share_message(
            'Example Product Name',
            f'{self.base_url}/shop/example-product-name/',
        )

    @property
    def share_contact_display(self):
        """
        The number to put in a shared message, or '' when none is configured.

        Falls back the same way ``whatsapp_digits`` does — dedicated field, then
        the WhatsApp number, then the main phone — so a site that never fills in
        the share field still shares something a recipient can reply to.
        """
        return (
            (self.share_contact or '').strip()
            or (self.whatsapp_number or '').strip()
            or (self.company_phone or '').strip()
        )

    def build_share_message(self, product_name, url):
        """
        The text handed to the clipboard or the phone's share sheet.

        Args:
            product_name (str): The product being shared.
            url (str): Its absolute public URL.

        Returns:
            str: e.g.::

                Wireless Car Wash Gun 21V
                Available for Amazon UAE, KSA and USA — shipped direct from China
                WhatsApp: +8617651652712
                https://mudassirllc.com/shop/wireless-car-wash-gun-21v/

        Newline-separated rather than one run-on sentence: WhatsApp, Telegram and
        the iOS share sheet all preserve line breaks, and the URL has to end up on
        its own line or those apps fold trailing punctuation into the link and
        break it.

        Every part is optional and simply drops out when unset, so this degrades
        to just the name and the URL rather than emitting a stray label with
        nothing after it.
        """
        lines = [(product_name or '').strip()]

        pitch = (self.share_pitch or '').strip()
        if pitch:
            lines.append(pitch)

        contact = self.share_contact_display
        if contact:
            lines.append(f'WhatsApp: {contact}')

        if url:
            lines.append(url)

        return '\n'.join(line for line in lines if line)

    @property
    def lead_notification_recipients(self):
        """
        Addresses that should receive a new-enquiry alert.

        Returns:
            list[str]: Configured recipients, or a single fallback sender address.

        Falls back to the security then order-status sender so that alerts still
        arrive on an installation where this was never filled in.
        """
        raw = (self.lead_notification_email or '').strip()
        if raw:
            return [a.strip() for a in raw.replace(';', ',').split(',') if a.strip()]
        fallback = (self.security_email_from_address or '').strip() or (self.email_from_address or '').strip()
        return [fallback] if fallback else []

    @property
    def social_links(self):
        """
        Every configured social/contact URL, with blanks removed.

        Returns:
            list[str]: Non-empty profile URLs, in a stable order.

        Exists to fix a long-standing bug in the Organization structured data. The
        template built the schema.org `sameAs` array with one `{% if %}` per
        network, each emitting a trailing comma — so whenever any of the later
        networks was unset the JSON ended with a dangling comma and was invalid.
        Google discards a malformed block wholesale, which meant the Organization
        entity (and with it the logo and social profiles it links) had never been
        read at all.

        Returning a clean list lets the template loop with `forloop.last` and
        produce valid JSON at every combination of filled and empty fields.
        """
        wa_source = (self.whatsapp_number or self.company_phone or '').strip()
        wa_digits = ''.join(ch for ch in wa_source if ch.isdigit())

        candidates = [
            f'https://wa.me/{wa_digits}' if wa_digits else '',
            self.linkedin_url,
            self.instagram_url,
            self.facebook_url,
            self.twitter_url,
            self.youtube_url,
            self.tiktok_url,
            self.whatsapp_channel_url,
        ]
        return [str(url).strip() for url in candidates if url and str(url).strip()]

    @property
    def base_url(self):
        """The site address with any trailing slash removed, for building links."""
        return (self.site_url or 'https://mudassirllc.com').rstrip('/')

    @property
    def site_host(self):
        """
        Just the hostname from ``site_url`` — no scheme, no path, no trailing slash.

        ``django.contrib.sites`` stores a bare host ('mudassirllc.com'), while
        ``site_url`` is a full address ('https://mudassirllc.com'). This converts
        between the two.
        """
        from urllib.parse import urlparse

        raw = self.base_url
        parsed = urlparse(raw if '//' in raw else f'//{raw}')
        return (parsed.netloc or parsed.path).strip('/')

    def sync_site_framework(self):
        """
        Copy ``site_url`` onto the ``django.contrib.sites`` row that SITE_ID points at.

        sitemap.xml gets its domain from the Sites framework, NOT from site_url. The
        django_site table ships with a single row reading 'example.com', and nothing
        ever updated it — so every <loc> in the sitemap pointed at
        https://example.com/... while canonical tags, Open Graph URLs and robots.txt
        (all built from site_url) correctly said mudassirllc.com.

        A sitemap full of another domain's URLs is worse than no sitemap: Search
        Console rejects the entries as being outside the property, so none of the
        listed pages get the discovery benefit.

        Called from save(), so changing the Website Address in the settings screen
        keeps the sitemap correct without anyone remembering this table exists.
        """
        host = self.site_host
        if not host:
            return
        try:
            from django.conf import settings as django_settings
            from django.contrib.sites.models import Site
        except Exception:
            return  # sites framework not installed — nothing to sync

        site_id = getattr(django_settings, 'SITE_ID', 1)
        Site.objects.update_or_create(
            pk=site_id, defaults={'domain': host, 'name': self.company_name or host},
        )
        # get_current() memoises per SITE_ID; without this the running process keeps
        # serving the old domain until it restarts.
        Site.objects.clear_cache()

    def save(self, *args, **kwargs):
        """Persist the settings, then mirror the address onto the Sites framework."""
        super().save(*args, **kwargs)
        # Never let a sites-table problem block saving the company settings.
        try:
            self.sync_site_framework()
        except Exception:
            pass

    def allocate_invoice_number(self):
        """
        Reserve and return the next invoice reference, e.g. "INV-0042".

        Returns:
            str: The formatted invoice number.

        Concurrency:
            Uses SELECT ... FOR UPDATE on the settings row so two invoices
            generated at the same moment cannot be handed the same number. The
            lock is held only for the increment, which is why the caller should
            wrap this in a transaction it keeps short.

        Invoices previously showed the raw database primary key ("#33"), which is
        neither sequential nor gapless and looks unprofessional on a document a
        customer files for their own accounts.
        """
        from django.db import transaction
        with transaction.atomic():
            current = CompanySettings.objects.select_for_update().get(pk=self.pk)
            number = current.next_invoice_number or 1
            current.next_invoice_number = number + 1
            current.save(update_fields=['next_invoice_number'])
        padding = self.invoice_number_padding or 0
        return f"{self.invoice_prefix or ''}{str(number).zfill(padding)}"

    def get_smtp_profile(self, email_type):
        """
        Returns the SMTP profile dictionary for a given email type.

        Args:
            email_type (str): One of 'order_status', 'security', or 'news'.

        Returns:
            dict: with keys from_address, host, port, user, password, use_tls.

        INHERITANCE IS ALL-OR-NOTHING, AND THAT MATTERS

        A profile with no host of its own uses the order-status server COMPLETE:
        host, port, username, password and TLS together. Only ``from_address``
        stays its own, because that is a label rather than a connection setting
        and per-purpose senders are the whole point of having three profiles.

        This used to inherit field by field, which quietly broke the commonest
        setup of all — one mailbox for everything:

          * ``security_email_smtp_port`` defaults to 587, and a default of 587
            is truthy, so ``or`` never fell through. The profile inherited the
            host but kept port 587.
          * ``use_tls`` had no fallback at all and always used its own value.

        So configuring a single account on port 465 (implicit SSL) gave the
        security and news profiles the right host and credentials on the wrong
        port with the wrong encryption. Every password reset, sign-in code and
        support notification failed — and because ``send_typed_email`` defaults
        to ``fail_silently=True``, failed without a trace.

        Half-inherited connection settings are never valid. A server is a set of
        five values that only work together.
        """
        email_type = str(email_type or 'order_status').lower()

        # Order-status profile uses the legacy email_* fields.
        order_status_profile = {
            'from_address': self.email_from_address or 'order_status@mudassirllc.com',
            'host': self.email_smtp_host or '',
            'port': self.email_smtp_port or 587,
            'user': self.email_smtp_user or '',
            'password': self.email_smtp_password or '',
            'use_tls': self.email_use_tls,
        }

        if email_type == 'order_status':
            return order_status_profile

        prefix = email_type  # 'security' or 'news'
        own_host = (getattr(self, f'{prefix}_email_smtp_host', '') or '').strip()
        from_address = (
            getattr(self, f'{prefix}_email_from_address', '')
            or order_status_profile['from_address']
        )

        if not own_host:
            # No server of its own: take the order-status connection entire, and
            # keep only this profile's sender label.
            return {**order_status_profile, 'from_address': from_address}

        return {
            'from_address': from_address,
            'host': own_host,
            'port': getattr(self, f'{prefix}_email_smtp_port', 0) or 587,
            'user': getattr(self, f'{prefix}_email_smtp_user', '') or '',
            'password': getattr(self, f'{prefix}_email_smtp_password', '') or '',
            'use_tls': getattr(self, f'{prefix}_email_use_tls', True),
        }

    def get_fx_rate(self, target_currency):
        """
        Returns the exchange rate from the base currency to the target currency.

        Args:
            target_currency (str): The ISO currency code (e.g., 'USD', 'EUR').

        Returns:
            Decimal: The exchange rate. Returns 1.00 if target == base currency.
                     Returns 0 if the rate is not found in fx_rates.

        Business Logic:
            In international logistics, customers deal in multiple currencies.
            The base currency is the company's primary operating currency (e.g., AED).
            All prices are stored in the base currency. When displaying to a customer,
            we multiply the base price by the FX rate to show the local equivalent.
        """
        # If the target currency is the same as the base currency, the rate is 1:1.
        if target_currency == self.currency:
            return Decimal('1')
        # Ensure fx_rates is a dictionary (defensive against None or malformed JSON).
        rates = self.fx_rates or {}
        # Look up the target currency in the fx_rates dictionary.
        # If not found, return 0 to indicate "rate unavailable".
        rate_val = rates.get(target_currency)
        if rate_val is not None:
            return Decimal(str(rate_val))
        return Decimal('0')

    def convert_price(self, amount, target_currency):
        """
        Converts a monetary amount from the base currency to the target currency.

        Args:
            amount (Decimal or float or int): The amount in the base currency.
            target_currency (str): The ISO currency code to convert to.

        Returns:
            Decimal: The converted amount, or the original amount if target == base currency.
                     Returns 0 if the FX rate is not available.

        Business Logic:
            This is the primary method for multi-currency display in the portal.
            When a customer browses products or views an order, the system calls
            this method to show an approximate price in their preferred currency.
            Note: The result is rounded to 2 decimal places for currency display.
        """
        # If target is the same as base, no conversion needed.
        if target_currency == self.currency:
            return Decimal(str(amount)) if amount is not None else Decimal('0')
        # Get the FX rate for the target currency.
        rate = self.get_fx_rate(target_currency)
        if rate == 0:
            return Decimal('0')
        # Convert: target_amount = base_amount * rate
        converted = Decimal(str(amount)) * rate if amount is not None else Decimal('0')
        # Round to 2 decimal places for standard currency display.
        return converted.quantize(Decimal('0.01'))

    def get_supported_currencies(self):
        """
        Returns a list of all currencies for which an FX rate is defined.

        Returns:
            list: A list of currency code strings, always including the base currency.

        Business Logic:
            This is used to populate currency selector dropdowns in the portal.
            It combines the base currency with all currencies that have rates in fx_rates.
        """
        rates = self.fx_rates or {}
        currencies = list(rates.keys())
        # Always include the base currency even if it's not in fx_rates.
        if self.currency not in currencies:
            currencies.insert(0, self.currency)
        return currencies


# =============================================================================
# SITE IMAGERY
# =============================================================================


class SiteImage(models.Model):
    """
    An owner-supplied photograph that replaces a stock image in a fixed page slot.

    Why this exists:
        Every photograph on the marketing site was generic stock imagery. For most
        businesses that is merely bland; for this one it actively contradicts the
        sales pitch. The entire proposition is "we are physically in Xuzhou, we
        walk into the factory ourselves, we photograph your goods before they
        ship" — and the page illustrating that claim showed an anonymous stock
        warehouse that could be anywhere on earth. A visitor who has been scammed
        buying from China before reads that instantly.

        Real photographs — your team on a factory floor, an actual inspection in
        progress, your office — are the highest-value trust asset available here,
        and they cost a phone camera rather than money.

    How it works:
        Each row maps a SLOT (a fixed key the templates know about) to an uploaded
        image. Templates render the uploaded photo when a row exists for that slot
        and fall back to the bundled stock image when it does not, so the site
        never looks broken while slots are still empty. Slots can be filled one at
        a time, in any order.

    Attributes:
        slot (str): Which position on the site this fills. See SLOT_CHOICES.
        image (Image): The photograph itself.
        alt_text (str): What the photo shows, for screen readers and image search.
        caption (str): Optional visible caption.
        is_active (bool): Untick to fall back to the stock image without deleting.
    """

    SLOT_HOME_FEATURE = 'home_feature'
    SLOT_ABOUT_MAIN = 'about_main'
    SLOT_ABOUT_TEAM = 'about_team'
    SLOT_ABOUT_FACILITY = 'about_facility'
    SLOT_SERVICE_SOURCING = 'service_sourcing'
    SLOT_SERVICE_VERIFICATION = 'service_verification'
    SLOT_SERVICE_INSPECTION = 'service_inspection'
    SLOT_SERVICE_SHIPPING = 'service_shipping'

    SLOT_CHOICES = [
        (SLOT_HOME_FEATURE, 'Homepage — "We Are on the Ground in China" photo'),
        (SLOT_ABOUT_MAIN, 'About page — main photo'),
        (SLOT_ABOUT_TEAM, 'About page — your team'),
        (SLOT_ABOUT_FACILITY, 'About page — office or warehouse'),
        (SLOT_SERVICE_SOURCING, 'Services — Product Sourcing'),
        (SLOT_SERVICE_VERIFICATION, 'Services — Supplier Verification'),
        (SLOT_SERVICE_INSPECTION, 'Services — Quality Inspection'),
        (SLOT_SERVICE_SHIPPING, 'Services — Shipping Coordination'),
    ]

    slot = models.CharField(
        max_length=40,
        choices=SLOT_CHOICES,
        unique=True,
        help_text='Which image on the site this replaces. One upload per slot.'
    )
    image = models.ImageField(
        upload_to='site_images/',
        help_text='Landscape works best, around 1200x800. A clear phone photo beats a polished stock shot.'
    )
    alt_text = models.CharField(
        max_length=250,
        blank=True,
        default='',
        help_text='Describe what the photo shows, e.g. "Our inspector checking cartons at a Ningbo factory". '
                  'Used by screen readers and Google Images.'
    )
    caption = models.CharField(
        max_length=250,
        blank=True,
        default='',
        help_text='Optional caption shown under the photo. Naming the city and month makes it far more credible.'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Untick to temporarily fall back to the bundled stock image without deleting this upload.'
    )
    uploaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slot']
        verbose_name = 'Site Image'
        verbose_name_plural = 'Site Images'

    def __str__(self):
        return self.get_slot_display()

    @classmethod
    def get_map(cls):
        """
        Returns {slot: SiteImage} for every active image.

        Templates look slots up by key, so a missing slot simply resolves to
        nothing and the template falls through to its stock fallback.
        """
        return {img.slot: img for img in cls.objects.filter(is_active=True)}
