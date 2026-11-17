"""
Move the stored business location from Xuzhou, Jiangsu to Yiwu, Zhejiang.

WHY A DATA MIGRATION IS NEEDED AT ALL

0029 changed the field DEFAULTS, which only applies to rows created after it.
The CompanySettings row on a running site was created long before, so it still
holds whatever the default was on the day it was made - 'Xuzhou' and 'Jiangsu'.

That matters more than the templates do: business_city is rendered into
`addressLocality` in the Organization structured data on every page, so it is
the value Google reads as the company's location. Leaving it would mean the
site says Yiwu everywhere a person can read and Xuzhou everywhere a crawler
can.

WHY IT IS CONDITIONAL

Only rows still holding the exact superseded values are touched. If the owner
has already typed a different city in admin - a second office, a district name,
anything - that is a deliberate choice and this leaves it alone. The reverse
does the same in the other direction, so the migration can be rolled back.
"""

from django.db import migrations

OLD_CITY, NEW_CITY = 'Xuzhou', 'Yiwu'
OLD_REGION, NEW_REGION = 'Jiangsu', 'Zhejiang'


def _move(apps, old_city, new_city, old_region, new_region):
    CompanySettings = apps.get_model('settings_manager', 'CompanySettings')
    CompanySettings.objects.filter(business_city=old_city).update(business_city=new_city)
    CompanySettings.objects.filter(business_region=old_region).update(business_region=new_region)


def forwards(apps, schema_editor):
    _move(apps, OLD_CITY, NEW_CITY, OLD_REGION, NEW_REGION)


def backwards(apps, schema_editor):
    _move(apps, NEW_CITY, OLD_CITY, NEW_REGION, OLD_REGION)


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0029_alter_companysettings_business_city_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
