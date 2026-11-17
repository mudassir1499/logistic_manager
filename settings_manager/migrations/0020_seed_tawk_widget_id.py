"""
Moves the Tawk.to live-chat widget ID out of the template and into settings.

The ID was hardcoded in portal/templates/portal/base.html. Seeding it here means
chat keeps working after the template starts reading from the database — without
this, deploying the template change would silently switch live chat off.

Only fills a blank value, so it can never overwrite an ID an admin has set.
"""

from django.db import migrations


# The widget path from the embed code previously hardcoded in portal/base.html.
TAWK_WIDGET_ID = '6a46bc264b956a1d4cbbc178/1jsi4ttv4'


def seed_tawk_id(apps, schema_editor):
    CompanySettings = apps.get_model('settings_manager', 'CompanySettings')
    CompanySettings.objects.filter(tawk_widget_id='').update(tawk_widget_id=TAWK_WIDGET_ID)


def clear_tawk_id(apps, schema_editor):
    CompanySettings = apps.get_model('settings_manager', 'CompanySettings')
    CompanySettings.objects.filter(tawk_widget_id=TAWK_WIDGET_ID).update(tawk_widget_id='')


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0019_branding_invoicing_and_operations'),
    ]

    operations = [
        migrations.RunPython(seed_tawk_id, clear_tawk_id),
    ]
