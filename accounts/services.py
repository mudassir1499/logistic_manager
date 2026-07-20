"""
accounts/services.py

Helpers that keep a ``Customer`` business record and its Django ``User`` login in
sync. Used wherever a customer is created or edited outside of self-registration
(admin customer management, profile edits), so every customer with portal
credentials always has a matching unified-auth login.
"""

from django.contrib.auth.models import User

from .models import Profile


def sync_customer_user(customer, raw_password=None):
    """
    Ensure a ``Customer`` with an email has a linked Django ``User`` + Profile,
    and optionally (re)set its password and active state.

    - No email -> nothing to do (the customer cannot log in without one).
    - Creates the User/Profile on first call; updates them on subsequent calls.
    - ``raw_password`` (if given) is hashed onto the User.
    - The User's ``is_active`` and ``email`` mirror the Customer.

    Returns the User, or None if the customer has no email.
    """
    email = (customer.email or '').strip().lower()
    if not email:
        return None

    # Prefer an already-linked profile; otherwise match by username/email.
    profile = Profile.objects.filter(customer=customer).select_related('user').first()
    if profile is not None:
        user = profile.user
    else:
        user = User.objects.filter(username__iexact=email).first()
        if user is None:
            user = User.objects.create(username=email, email=email)
        profile = user.profile
        profile.role = Profile.ROLE_CUSTOMER
        profile.customer = customer
        profile.save()

    user.email = email
    user.is_active = bool(customer.is_active)
    if raw_password:
        user.set_password(raw_password)
    elif customer.password and not user.has_usable_password():
        # Mirror the customer's existing hash if the User somehow has none.
        user.password = customer.password
    user.save()
    return user
