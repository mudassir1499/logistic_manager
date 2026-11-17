"""
Adds owner-editable homepage credibility figures and the SiteImage model.

The stat_* fields replace eight statistics that were hardcoded into the homepage
template ("500+ Products Sourced", "98% Quality Pass Rate", "4.8/5 Client
Rating"...) and were not backed by any data. They all default to EMPTY on
purpose, and the template renders each figure only when it has been filled in —
so the site ships with no unverified claims, and the owner supplies real numbers
from /settings/ when they have them.

SiteImage lets the owner replace stock photography with real photographs of their
own team and the factories they visit, one slot at a time.

Hand-written rather than generated: `makemigrations` on this project also emits
phantom BigAutoField -> AutoField alterations for unrelated models.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0017_seed_google_analytics_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='companysettings',
            name='stat_years_in_china',
            field=models.CharField(blank=True, default='', help_text='e.g. "7+". Leave blank to hide this figure from the homepage.', max_length=20, verbose_name='Years operating in China'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='stat_products_sourced',
            field=models.CharField(blank=True, default='', help_text='e.g. "500+". Only enter a number you could evidence if a client asked. Blank hides it.', max_length=20, verbose_name='Products sourced'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='stat_verified_suppliers',
            field=models.CharField(blank=True, default='', help_text='e.g. "200+". Factories you have actually visited and vetted. Blank hides it.', max_length=20, verbose_name='Verified suppliers'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='stat_active_clients',
            field=models.CharField(blank=True, default='', help_text='e.g. "150+". Businesses currently ordering through you. Blank hides it.', max_length=20, verbose_name='Active clients'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='stat_response_time',
            field=models.CharField(blank=True, default='24 hours', help_text='e.g. "24 hours". This is a promise you make, so keep it one you can keep. Blank hides it.', max_length=40, verbose_name='Quote response time'),
        ),
        migrations.CreateModel(
            name='SiteImage',
            fields=[
                # BigAutoField, because SettingsManagerConfig in
                # settings_manager/apps.py sets default_auto_field = BigAutoField,
                # overriding the project-wide DEFAULT_AUTO_FIELD = AutoField.
                # Declaring AutoField here would leave the model and the migration
                # state permanently out of sync and `makemigrations` would propose
                # an AlterField on every run.
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                # max_length 40 keeps the unique index comfortably inside the
                # 767-byte InnoDB prefix limit under utf8mb4 (40 x 4 = 160 bytes).
                ('slot', models.CharField(choices=[('home_feature', 'Homepage — "We Are on the Ground in China" photo'), ('about_main', 'About page — main photo'), ('about_team', 'About page — your team'), ('about_facility', 'About page — office or warehouse'), ('service_sourcing', 'Services — Product Sourcing'), ('service_verification', 'Services — Supplier Verification'), ('service_inspection', 'Services — Quality Inspection'), ('service_shipping', 'Services — Shipping Coordination')], help_text='Which image on the site this replaces. One upload per slot.', max_length=40, unique=True)),
                ('image', models.ImageField(help_text='Landscape works best, around 1200x800. A clear phone photo beats a polished stock shot.', upload_to='site_images/')),
                ('alt_text', models.CharField(blank=True, default='', help_text='Describe what the photo shows, e.g. "Our inspector checking cartons at a Ningbo factory". Used by screen readers and Google Images.', max_length=250)),
                ('caption', models.CharField(blank=True, default='', help_text='Optional caption shown under the photo. Naming the city and month makes it far more credible.', max_length=250)),
                ('is_active', models.BooleanField(default=True, help_text='Untick to temporarily fall back to the bundled stock image without deleting this upload.')),
                ('uploaded_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Site Image',
                'verbose_name_plural': 'Site Images',
                'ordering': ['slot'],
            },
        ),
    ]
