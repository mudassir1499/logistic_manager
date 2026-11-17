"""
Adds branding, site identity, business profile, invoicing, operations and
third-party widget settings to CompanySettings.

Motivation, briefly:
  * The invoice template printed only company name/address/phone/currency — not a
    valid UAE tax invoice, and it gave the customer no way to pay.
  * The site domain was hardcoded in 99 places across templates and Python.
  * Opening hours, city and languages were hardcoded inside the JSON-LD Google
    reads, so changing them required a template edit.
  * The Tawk.to chat widget ID was hardcoded while every other third-party ID
    (Meta Pixel, GA4) was already a setting.

Hand-written rather than generated: `makemigrations` on this project also emits
phantom BigAutoField alterations for unrelated models.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0018_site_images_and_credibility_stats'),
    ]

    operations = [
        # --- Branding -------------------------------------------------------
        migrations.AddField(
            model_name='companysettings',
            name='logo',
            field=models.ImageField(blank=True, help_text='Recommended 512×512 px (square), PNG with a transparent background, under 200 KB. Used in the website header and footer, on invoices and packing lists, and as the logo Google shows beside your search listing. Leave empty to use the built-in mark.', null=True, upload_to='branding/', verbose_name='Company Logo'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='logo_wide',
            field=models.ImageField(blank=True, help_text='Recommended 600×160 px, PNG with a transparent background. A horizontal logo-plus-name lockup for document headers. Falls back to the square logo.', null=True, upload_to='branding/', verbose_name='Wide Logo (optional)'),
        ),

        # --- Site identity --------------------------------------------------
        migrations.AddField(
            model_name='companysettings',
            name='site_url',
            field=models.CharField(blank=True, default='https://mudassirllc.com', help_text='Full public address with https:// and NO trailing slash, e.g. https://mudassirllc.com. Used to build canonical links, sitemap entries and social share URLs.', max_length=255, verbose_name='Website Address'),
        ),

        # --- Business profile (structured data) ------------------------------
        migrations.AddField(
            model_name='companysettings',
            name='business_city',
            field=models.CharField(blank=True, default='Xuzhou', help_text='City your office is in. Shown to Google as your business location.', max_length=100, verbose_name='City'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='business_region',
            field=models.CharField(blank=True, default='Jiangsu', max_length=100, verbose_name='Province / State'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='business_country',
            field=models.CharField(blank=True, default='CN', help_text='Two-letter country code, e.g. CN for China, AE for the UAE.', max_length=2, verbose_name='Country Code'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='opening_time',
            field=models.CharField(blank=True, default='09:00', help_text='24-hour format, e.g. 09:00.', max_length=5, verbose_name='Opening Time'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='closing_time',
            field=models.CharField(blank=True, default='18:00', help_text='24-hour format, e.g. 18:00.', max_length=5, verbose_name='Closing Time'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='working_days',
            field=models.CharField(blank=True, default='Monday,Tuesday,Wednesday,Thursday,Friday,Saturday', help_text='Comma-separated English day names. Only these are published to Google.', max_length=120, verbose_name='Working Days'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='languages_spoken',
            field=models.CharField(blank=True, default='en,ar,ur,zh', help_text='Comma-separated two-letter codes, e.g. en,ar,ur,zh. Tells Google which languages your team can serve customers in.', max_length=120, verbose_name='Languages Spoken'),
        ),

        # --- Invoicing ------------------------------------------------------
        migrations.AddField(
            model_name='companysettings',
            name='tax_registration_number',
            field=models.CharField(blank=True, default='', help_text='Your UAE TRN. A tax invoice must show it for a VAT-registered customer to reclaim input tax. Leave blank if you are not VAT-registered — it is then hidden.', max_length=50, verbose_name='Tax Registration Number (TRN)'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='vat_percentage',
            field=models.DecimalField(decimal_places=2, default=0, help_text='e.g. 5.00 for the UAE standard rate. Leave at 0 to omit VAT from invoices entirely.', max_digits=5, verbose_name='VAT Percentage'),
        ),
        migrations.AddField(model_name='companysettings', name='bank_name',
                            field=models.CharField(blank=True, default='', max_length=150, verbose_name='Bank Name')),
        migrations.AddField(model_name='companysettings', name='bank_account_name',
                            field=models.CharField(blank=True, default='', help_text='Must match the name on the account exactly, or transfers get rejected.', max_length=150, verbose_name='Account Holder Name')),
        migrations.AddField(model_name='companysettings', name='bank_account_number',
                            field=models.CharField(blank=True, default='', max_length=64, verbose_name='Account Number')),
        migrations.AddField(model_name='companysettings', name='bank_iban',
                            field=models.CharField(blank=True, default='', max_length=64, verbose_name='IBAN')),
        migrations.AddField(model_name='companysettings', name='bank_swift',
                            field=models.CharField(blank=True, default='', max_length=32, verbose_name='SWIFT / BIC')),
        migrations.AddField(model_name='companysettings', name='bank_branch',
                            field=models.CharField(blank=True, default='', max_length=150, verbose_name='Branch')),
        migrations.AddField(
            model_name='companysettings',
            name='default_payment_terms',
            field=models.CharField(choices=[('due_on_receipt', 'Due on receipt'), ('net_7', 'Net 7 days'), ('net_15', 'Net 15 days'), ('net_30', 'Net 30 days'), ('net_45', 'Net 45 days'), ('net_60', 'Net 60 days')], default='due_on_receipt', help_text='Prints a due date on invoices, and defines what counts as overdue on the dashboard.', max_length=20, verbose_name='Default Payment Terms'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='invoice_prefix',
            field=models.CharField(blank=True, default='INV-', help_text='e.g. "INV-" or "MLC-2026-". Combined with a running number to give each invoice a stable reference. Invoices currently show the raw database ID, which is not sequential.', max_length=20, verbose_name='Invoice Number Prefix'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='next_invoice_number',
            field=models.PositiveIntegerField(default=1, help_text='The number the next invoice will take. Assigned once and then frozen on that order, so an invoice reference never changes after it has been sent.', verbose_name='Next Invoice Number'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='invoice_number_padding',
            field=models.PositiveSmallIntegerField(default=4, help_text='Zero-pad the running number to this many digits. 4 gives INV-0001.', verbose_name='Number Padding'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='invoice_terms',
            field=models.TextField(blank=True, default='', help_text='Printed at the foot of every invoice — deposit policy, inspection terms, late-payment conditions. Leave blank to omit the section.', verbose_name='Invoice Terms & Notes'),
        ),

        # --- Operations -----------------------------------------------------
        migrations.AddField(
            model_name='companysettings',
            name='lead_notification_email',
            field=models.CharField(blank=True, default='', help_text='Comma-separated addresses notified the moment a website enquiry arrives. Leave blank to fall back to the Security email sender.', max_length=500, verbose_name='Send New Enquiry Alerts To'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='quote_validity_days',
            field=models.PositiveSmallIntegerField(default=14, help_text="How long a quotation stays valid. Freight rates move, so an open-ended quote can bind you to last season's prices.", verbose_name='Quote Validity (days)'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='default_deposit_percentage',
            field=models.DecimalField(decimal_places=2, default=30, help_text='Deposit normally taken before production starts. Used to suggest a figure on new orders.', max_digits=5, verbose_name='Default Deposit (%)'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='low_stock_threshold',
            field=models.PositiveIntegerField(default=0, help_text='Flag a product when its quantity falls to or below this. 0 disables the warning.', verbose_name='Low Stock Threshold'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='order_cutoff_time',
            field=models.CharField(blank=True, default='', help_text='24-hour time, e.g. 16:00. Orders placed after it are handled the next working day. Leave blank if you do not work to a cut-off.', max_length=5, verbose_name='Daily Order Cut-off'),
        ),

        # --- Third-party widgets ---------------------------------------------
        migrations.AddField(
            model_name='companysettings',
            name='tawk_widget_id',
            field=models.CharField(blank=True, default='', help_text='The path from your Tawk.to embed code, e.g. 6a46bc264b956a1d4cbbc178/1jsi4ttv4. Leave blank to remove live chat from the site entirely.', max_length=120, verbose_name='Tawk.to Widget ID'),
        ),
    ]
