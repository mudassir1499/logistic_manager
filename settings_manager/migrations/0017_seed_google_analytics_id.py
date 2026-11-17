"""
Seeds the GA4 Measurement ID for mudassirllc.com.

The ID lives in the database rather than in a template, so on a fresh deploy the
settings row would otherwise come up blank and the site would ship with analytics
silently switched off. Seeding it here means `manage.py migrate` is all that is
needed to turn tracking on for the live server.

Hand-written (not generated) — `makemigrations` on this project also emits phantom
BigAutoField -> AutoField alterations for unrelated models.
"""

from django.db import migrations


# The GA4 Measurement ID for the mudassirllc.com web data stream.
GA4_MEASUREMENT_ID = 'G-8LK08485FL'


def seed_ga4_id(apps, schema_editor):
    """Write the Measurement ID onto the singleton settings row."""
    CompanySettings = apps.get_model('settings_manager', 'CompanySettings')
    # Only fill a blank. If an admin has already set an ID (or deliberately
    # cleared it to pause tracking), leave their choice alone.
    CompanySettings.objects.filter(google_analytics_id='').update(
        google_analytics_id=GA4_MEASUREMENT_ID
    )


def clear_ga4_id(apps, schema_editor):
    """Reverse step: remove the seeded ID so the migration is cleanly undoable."""
    CompanySettings = apps.get_model('settings_manager', 'CompanySettings')
    CompanySettings.objects.filter(google_analytics_id=GA4_MEASUREMENT_ID).update(
        google_analytics_id=''
    )


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0016_companysettings_google_analytics_id_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_ga4_id, clear_ga4_id),
    ]
