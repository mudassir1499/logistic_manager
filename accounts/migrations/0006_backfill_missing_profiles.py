"""
Give a Profile to every User that has not got one.

WHY THIS IS NEEDED AFTER 0002 ALREADY SEEDED PROFILES

0002 backfilled the Users that existed when it ran. Two paths create Users that
still end up without a Profile afterwards:

  * ``loaddata`` and any other raw fixture load. The post_save signal in
    accounts/signals.py deliberately returns early when ``raw=True``, because a
    fixture is expected to carry its own related rows - so a database restored
    or seeded from a dump gets Users and no Profiles.

  * Anything that writes Users without sending post_save, such as bulk_create.

The consequence is not cosmetic. Every back-office guard calls
``_profile(request.user)`` and redirects to login when it is None, so an account
in this state cannot reach any page it is entitled to - including a superuser,
who is then locked out of the admin area entirely while appearing perfectly
normal in the user list. Found on a real database: 4 of 11 Users, one of them a
superuser, had no Profile.

Idempotent: it only touches Users that have no Profile, so running it again does
nothing.
"""

from django.db import migrations

ROLE_ADMIN = 'admin'
ROLE_CUSTOMER = 'customer'

# Mirrors accounts/signals.py: a new superuser gets every module.
MODULE_FIELDS = [
    'perm_orders', 'perm_products', 'perm_customers', 'perm_khata',
    'perm_noon_labels', 'perm_support', 'perm_settings',
]


def backfill(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Profile = apps.get_model('accounts', 'Profile')
    Customer = apps.get_model('customers', 'Customer')

    have = set(Profile.objects.values_list('user_id', flat=True))

    # Profile.customer is a OneToOneField, so a Customer already attached to a
    # Profile cannot be attached to a second one. Two Users sharing an email
    # (an old duplicate account, say) would otherwise make this migration die
    # with "Duplicate entry for key 'customer_id'" halfway through, leaving some
    # accounts fixed and some not.
    taken_customers = set(
        Profile.objects.exclude(customer__isnull=True).values_list('customer_id', flat=True)
    )

    for user in User.objects.exclude(id__in=have).iterator():
        if user.is_superuser:
            # Same rule the signal applies: a superuser is an admin with every
            # module. Anything less would leave them unable to use the site they
            # already have full database access to.
            profile = Profile(user=user, role=ROLE_ADMIN)
            for field in MODULE_FIELDS:
                if hasattr(profile, field):
                    setattr(profile, field, True)
        else:
            # Default to customer, and attach the Customer record with the same
            # email if one exists - otherwise the account logs in and the portal
            # has no business record to show it.
            profile = Profile(user=user, role=ROLE_CUSTOMER)
            email = (user.email or user.username or '').strip()
            if email:
                match = (Customer.objects
                         .filter(email__iexact=email)
                         .exclude(id__in=taken_customers)
                         .first())
                if match is not None:
                    profile.customer = match
                    taken_customers.add(match.id)
        profile.save()


def noop(apps, schema_editor):
    """
    Not reversed.

    Deleting these Profiles would re-break the accounts this fixed, and there is
    no way to tell a Profile created here from one created any other way.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_apitoken'),
        ('customers', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
