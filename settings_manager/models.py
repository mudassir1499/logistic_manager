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

    def get_smtp_profile(self, email_type):
        """
        Returns the SMTP profile dictionary for a given email type.

        Args:
            email_type (str): One of 'order_status', 'security', or 'news'.

        Returns:
            dict: Dictionary with keys: from_address, host, port, user, password, use_tls.
              If the requested profile does not have its own host, falls back to the
              order-status profile so a single SMTP server can be shared.
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
        profile = {
            'from_address': getattr(self, f'{prefix}_email_from_address', '') or order_status_profile['from_address'],
            'host': getattr(self, f'{prefix}_email_smtp_host', '') or order_status_profile['host'],
            'port': getattr(self, f'{prefix}_email_smtp_port', 0) or order_status_profile['port'],
            'user': getattr(self, f'{prefix}_email_smtp_user', '') or order_status_profile['user'],
            'password': getattr(self, f'{prefix}_email_smtp_password', '') or order_status_profile['password'],
            'use_tls': getattr(self, f'{prefix}_email_use_tls', True),
        }
        return profile

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
