from django.contrib import admin
from django.utils.html import format_html

from .models import (CargoType, ShippingCompany, ShippingDestination,
                     ShippingRate, ShippingRateSheet, SiteImage, TeamMember)


@admin.register(SiteImage)
class SiteImageAdmin(admin.ModelAdmin):
    """
    Upload real photographs to replace the bundled stock imagery.

    Each slot corresponds to one fixed position on the public site. Uploading a
    photo swaps it in immediately; deleting the row (or unticking `is_active`)
    reverts to the stock image, so this is always safe to experiment with.
    """
    list_display = ('preview', 'slot', 'alt_text', 'is_active', 'uploaded_at')
    list_filter = ('is_active',)
    list_editable = ('is_active',)
    readonly_fields = ('preview_large', 'uploaded_at')

    fieldsets = (
        (None, {
            'fields': ('slot', 'image', 'preview_large'),
            'description': 'One photograph per slot. Landscape, around 1200x800. '
                           'A real phone photo of your own team or a factory you visited '
                           'is worth more here than any stock image.',
        }),
        ('Description', {
            'fields': ('alt_text', 'caption'),
            'description': 'alt_text is read aloud by screen readers and indexed by Google Images — '
                           'describe what is actually happening in the photo.',
        }),
        ('Visibility', {
            'fields': ('is_active', 'uploaded_at'),
        }),
    )

    @admin.display(description='Preview')
    def preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="height:44px;border-radius:4px;">', obj.image.url)
        return '—'

    @admin.display(description='Current image')
    def preview_large(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-width:420px;border-radius:8px;">', obj.image.url)
        return 'Nothing uploaded yet — the site is showing the bundled stock image for this slot.'
from .models import CompanySettings

@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Company Information', {
            'fields': ('company_name', 'company_phone', 'whatsapp_number', 'company_address'),
        }),
        ('Product Sharing', {
            'fields': ('share_pitch', 'share_contact'),
            'description': 'The two lines added between the product name and its link '
                           'when someone uses Share on a product page.',
        }),
        ('Social Media Links', {
            'fields': ('facebook_url', 'instagram_url', 'linkedin_url', 'twitter_url',
                       'youtube_url', 'tiktok_url', 'whatsapp_channel_url'),
        }),
        ('Commission & Currency', {
            'fields': ('commission_percentage', 'currency'),
        }),
        ('Shipping Rates (UAE)', {
            'fields': ('air_shipping_rate', 'sea_shipping_rate'),
        }),
        ('Shipping Rates (KSA)', {
            'fields': ('ksa_shipping_rate', 'ksa_air_shipping_rate', 'ksa_sea_shipping_rate'),
        }),
        ('No Brand Battery Rates (UAE)', {
            'fields': ('no_brand_battery_air_shipping_rate', 'no_brand_battery_sea_shipping_rate'),
        }),
        ('No Brand Battery Rates (KSA)', {
            'fields': ('no_brand_battery_ksa_air_shipping_rate', 'no_brand_battery_ksa_sea_shipping_rate'),
        }),
        ('Volumetric Rule & Minimum Charges', {
            'fields': ('volumetric_divisor', 'min_chargeable_kg', 'min_cbm'),
            'description': (
                'The rates above are per KG and per CBM. These decide WHICH kilograms '
                'and cubic metres get charged. Air freight bills the greater of actual '
                'weight and volumetric weight (L&times;W&times;H in cm, divided by the '
                'divisor), so the divisor is as much a part of the price as the rate is. '
                'Individual shipping companies can override all three.'
            ),
        }),
        ('Exchange Rate', {
            'fields': ('exchange_rate_enabled', 'exchange_rate_from', 'exchange_rate_to', 'exchange_rate'),
        }),
        ('Email Configuration', {
            'fields': (
                'email_from_address', 'email_smtp_host', 'email_smtp_port',
                'email_smtp_user', 'email_smtp_password', 'email_use_tls',
                'security_email_from_address', 'security_email_smtp_host', 'security_email_smtp_port',
                'security_email_smtp_user', 'security_email_smtp_password', 'security_email_use_tls',
                'news_email_from_address', 'news_email_smtp_host', 'news_email_smtp_port',
                'news_email_smtp_user', 'news_email_smtp_password', 'news_email_use_tls',
            ),
        }),
    )


# =============================================================================
# FREIGHT RATES
# =============================================================================
# Rates used to be eight columns on ShippingCompany, which could express exactly
# two countries and two cargo types. They are now rows, so adding Oman or a
# "fragile" category is data entry here rather than a schema migration.
# =============================================================================


class ShippingRateInline(admin.TabularInline):
    """
    Every lane a forwarder prices, edited on the forwarder's own page.

    An inline rather than a separate screen because a rate has no meaning apart
    from its company - you review a forwarder's pricing as one sheet, the same
    way it arrives from them.
    """
    model = ShippingRate
    extra = 0
    fields = ('destination', 'cargo_type', 'method', 'rate', 'minimum',
              'volumetric_divisor', 'transit_days', 'notes')
    autocomplete_fields = ('destination', 'cargo_type')
    ordering = ('destination', 'method', 'cargo_type')


@admin.register(ShippingDestination)
class ShippingDestinationAdmin(admin.ModelAdmin):
    """Countries you quote to. Adding one here makes it available everywhere."""
    list_display = ('name', 'code', 'is_active', 'sort_order', 'rate_count')
    list_editable = ('is_active', 'sort_order')
    search_fields = ('name', 'code')
    ordering = ('sort_order', 'name')

    @admin.display(description='Rates on file')
    def rate_count(self, obj):
        return obj.rates.count()


@admin.register(CargoType)
class CargoTypeAdmin(admin.ModelAdmin):
    """
    The categories forwarders price separately.

    `slug` is what rate sheets are matched on when they come back, so renaming a
    category is safe but changing its slug orphans its rates.
    """
    list_display = ('name', 'slug', 'is_active', 'customer_selectable',
                    'sort_order', 'rate_count')
    list_editable = ('is_active', 'customer_selectable', 'sort_order')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('sort_order', 'name')

    @admin.display(description='Rates on file')
    def rate_count(self, obj):
        return obj.rates.count()


@admin.register(ShippingCompany)
class ShippingCompanyAdmin(admin.ModelAdmin):
    """
    A freight forwarder and everything it quotes.

    The eight legacy rate columns are deliberately NOT editable here. They are
    mirrored from the rate rows below (see sync_legacy_rate_columns) so that the
    order screen keeps working, and letting someone type into both would create
    two answers to the same question.
    """
    list_display = ('name', 'website', 'lane_count', 'volumetric_divisor')
    search_fields = ('name',)
    inlines = [ShippingRateInline]

    fieldsets = (
        (None, {
            'fields': ('name', 'website', 'shipping_rate_sheet'),
        }),
        ('Defaults for this company', {
            'fields': ('volumetric_divisor', 'min_chargeable_kg', 'min_cbm'),
            'description': 'Applied to every lane below that does not set its own. '
                           'Leave at 0 to inherit the global defaults from Company Settings.',
        }),
    )

    @admin.display(description='Lanes priced')
    def lane_count(self, obj):
        return obj.rates.filter(rate__gt=0).count()


@admin.register(ShippingRate)
class ShippingRateAdmin(admin.ModelAdmin):
    """
    Every rate, across every forwarder — the answer to "who is cheapest to X?".

    The inline on the company page is for entering rates. This is for comparing
    them, which is why it defaults to ordering by lane rather than by company.
    """
    list_display = ('company', 'destination', 'cargo_type', 'method', 'rate',
                    'minimum', 'volumetric_divisor', 'transit_days', 'updated_at')
    list_filter = ('method', 'destination', 'cargo_type', 'company')
    search_fields = ('company__name', 'destination__name', 'cargo_type__name')
    autocomplete_fields = ('company', 'destination', 'cargo_type')
    ordering = ('destination', 'method', 'cargo_type', 'rate')


@admin.register(ShippingRateSheet)
class ShippingRateSheetAdmin(admin.ModelAdmin):
    """
    A record of which rate request went to whom, and when.

    Read-only on purpose: this is a log. A forwarder returning a sheet weeks
    later may be filling in a version issued before a cargo type was added, and
    that is only diagnosable if the record of what was sent cannot be edited.
    """
    list_display = ('company', 'method', 'generated_at', 'imported_at')
    list_filter = ('method', 'company')
    readonly_fields = ('company', 'method', 'workbook', 'generated_at', 'imported_at')

    def has_add_permission(self, request):
        return False


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    """
    The people shown in "Meet Our Team" on the About page.

    Also editable from Settings, which is where the owner will normally do it.
    This exists for bulk reordering and for fixing a photo without hunting for
    the right card.
    """
    list_display = ('thumb', 'name', 'role', 'is_active', 'sort_order')
    list_editable = ('is_active', 'sort_order')
    list_display_links = ('thumb', 'name')
    search_fields = ('name', 'role')
    list_filter = ('is_active',)
    ordering = ('sort_order', 'id')

    fieldsets = (
        (None, {
            'fields': ('name', 'role', 'photo', 'bio'),
            'description': 'Use a real photograph. Anyone deciding whether to trust '
                           'a sourcing agent will reverse image search this page, and '
                           'a stock portrait ends the conversation.',
        }),
        ('Optional links', {
            'fields': ('email', 'linkedin_url'),
        }),
        ('Display', {
            'fields': ('sort_order', 'is_active'),
        }),
    )

    @admin.display(description='Photo')
    def thumb(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="height:40px;width:40px;border-radius:50%;object-fit:cover;">',
                obj.photo.url)
        return format_html(
            '<span style="display:inline-grid;place-items:center;height:40px;width:40px;'
            'border-radius:50%;background:#eee;font-weight:700;font-size:12px;">{}</span>',
            obj.initials)
