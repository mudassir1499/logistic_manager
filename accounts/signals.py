"""
accounts/signals.py

Guarantees that every ``User`` has exactly one ``Profile``. Without this, code
that creates a User (Django admin, ``createsuperuser``, our registration view,
the data migration) could otherwise leave a User with no Profile, which would
break every ``request.user.profile`` access downstream.
"""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_profile(sender, instance, created, **kwargs):
    """
    Create a Profile the first time a User is saved.

    New Users default to the ``customer`` role because self-registration is the
    most common creation path. Superusers created via ``createsuperuser`` are an
    exception: they should administer the whole system, so we promote them to the
    ``admin`` role immediately.

    We use ``get_or_create`` rather than ``create`` so this is safe even if a
    Profile was already created explicitly (e.g. inside the data migration).
    """
    if not created:
        return

    role = Profile.ROLE_ADMIN if instance.is_superuser else Profile.ROLE_CUSTOMER
    profile, was_created = Profile.objects.get_or_create(
        user=instance,
        defaults={'role': role},
    )

    # A brand-new superuser (created after this app existed) should get every
    # module permission so the owner is never locked out of their own tools.
    if was_created and role == Profile.ROLE_ADMIN:
        for field in Profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, True)
        profile.save()
