"""
Data migration: grandfather existing accounts as email-verified.

Email verification was introduced after these accounts were created; forcing
every live customer to re-verify would be hostile. Only accounts registered
after this feature ships start unverified.
"""

from django.db import migrations


def mark_verified(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    Profile.objects.update(email_verified=True)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_profile_email_verified_profile_two_factor_enabled_and_more'),
    ]

    operations = [
        migrations.RunPython(mark_verified, migrations.RunPython.noop),
    ]
