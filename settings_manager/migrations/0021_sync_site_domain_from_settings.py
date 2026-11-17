"""Point the django.contrib.sites row at the real domain.

The sites table ships with one row containing Django's placeholder 'example.com',
and nothing in this project ever wrote to it. sitemap.xml takes its domain from
that row, so every URL it published read https://example.com/... — while the
canonical tags, Open Graph URLs and robots.txt (all built from
CompanySettings.site_url) correctly said mudassirllc.com.

Search Console rejects sitemap entries whose host is outside the verified
property, so the sitemap was contributing nothing to indexing.

From here on CompanySettings.save() keeps the two in step; this migration fixes
the row that is already in the database.
"""

from urllib.parse import urlparse

from django.conf import settings as django_settings
from django.db import migrations

DEFAULT_URL = 'https://mudassirllc.com'
PLACEHOLDER = 'example.com'


def _host_from(url):
    raw = (url or DEFAULT_URL).rstrip('/')
    parsed = urlparse(raw if '//' in raw else f'//{raw}')
    return (parsed.netloc or parsed.path).strip('/')


def forwards(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')
    CompanySettings = apps.get_model('settings_manager', 'CompanySettings')

    row = CompanySettings.objects.first()
    host = _host_from(getattr(row, 'site_url', '') if row else '')
    name = (getattr(row, 'company_name', '') or host) if row else host
    if not host:
        return

    site_id = getattr(django_settings, 'SITE_ID', 1)
    Site.objects.update_or_create(pk=site_id, defaults={'domain': host, 'name': name})


def backwards(apps, schema_editor):
    """Restore Django's placeholder so the migration is genuinely reversible."""
    Site = apps.get_model('sites', 'Site')
    site_id = getattr(django_settings, 'SITE_ID', 1)
    Site.objects.filter(pk=site_id).update(domain=PLACEHOLDER, name=PLACEHOLDER)


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0020_seed_tawk_widget_id'),
        # The sites table must exist before we can write to it.
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
