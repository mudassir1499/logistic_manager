"""
Data migration: bring existing accounts onto the unified auth model.

Two things need backfilling the first time this app is deployed:

  1. Every pre-existing Django ``User`` (created before the Profile model
     existed) needs a Profile. Superusers become ``admin``; any other existing
     staff login becomes ``staff`` with ALL module permissions granted — those
     accounts could already reach every back-office view via the old blanket
     ``@login_required``, so we must not silently take access away.

  2. Every ``Customer`` that had portal credentials (email + password) needs a
     real ``User`` login so they can authenticate through Django's auth stack.
     Crucially, ``Customer.password`` is ALREADY a Django PBKDF2 hash (it was set
     with ``make_password``), so we copy the hash straight across — customers
     keep their existing password and never need a reset.

Email collisions (a customer whose email already belongs to a staff login) are
skipped rather than merged, to avoid a customer inheriting staff access. Reverse
is intentionally a no-op: we must never auto-delete real login accounts.
"""

from django.db import migrations


def seed(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Customer = apps.get_model('customers', 'Customer')
    Profile = apps.get_model('accounts', 'Profile')

    ROLE_ADMIN, ROLE_STAFF, ROLE_CUSTOMER = 'admin', 'staff', 'customer'
    PERM_FIELDS = [
        'perm_orders', 'perm_products', 'perm_customers',
        'perm_khata', 'perm_noon_labels', 'perm_support', 'perm_settings',
    ]

    # ---- 1. Backfill Profiles for existing Django users --------------------
    for user in User.objects.all():
        if Profile.objects.filter(user=user).exists():
            continue
        role = ROLE_ADMIN if user.is_superuser else ROLE_STAFF
        # Existing back-office users keep full module access (that was the
        # effective behaviour under the old blanket @login_required guard).
        perms = {f: True for f in PERM_FIELDS}
        Profile.objects.create(user=user, role=role, **perms)

    # Set of identifiers already taken by non-customer logins, so we can detect
    # collisions before creating customer users.
    taken_usernames = set(u.lower() for u in User.objects.values_list('username', flat=True))

    skipped_collisions = []

    # ---- 2. Create User logins for customers with portal credentials -------
    customers = Customer.objects.exclude(email__isnull=True).exclude(email='').exclude(
        password__isnull=True).exclude(password='')
    for customer in customers:
        email = (customer.email or '').strip().lower()
        if not email:
            continue

        # If this customer already has a linked login, leave it alone.
        if Profile.objects.filter(customer=customer).exists():
            continue

        # Collision: the email is already a login that is NOT this customer's.
        # Skip and report rather than risk granting a customer someone else's
        # (possibly staff) account.
        if email in taken_usernames:
            existing = User.objects.filter(username__iexact=email).first()
            if existing and not Profile.objects.filter(user=existing, customer=customer).exists():
                skipped_collisions.append(email)
                continue

        user = User.objects.create(
            username=email,
            email=email,
            is_active=bool(customer.is_active),
            is_staff=False,
            is_superuser=False,
        )
        # Copy the already-hashed password verbatim (no re-hashing, no reset).
        user.password = customer.password
        user.save(update_fields=['password'])

        Profile.objects.create(user=user, role=ROLE_CUSTOMER, customer=customer)
        taken_usernames.add(email)

    if skipped_collisions:
        # Surface collisions in the migrate output so the operator can resolve
        # them by hand (e.g. change the customer's email or merge accounts).
        print('\n[accounts] Skipped customer logins due to email collisions with '
              'existing users: ' + ', '.join(skipped_collisions))


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('customers', '0006_alter_customer_id_alter_customerproduct_id'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
