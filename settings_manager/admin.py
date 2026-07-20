from django.contrib import admin
from .models import CompanySettings

@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Company Information', {
            'fields': ('company_name', 'company_phone', 'whatsapp_number', 'company_address'),
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
