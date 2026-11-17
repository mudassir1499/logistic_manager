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
        # This branch can pick up a User that already existed before this app added
        # Profiles, in which case `user.profile` raises RelatedObjectDoesNotExist and
        # saving the customer 500s. for_user() creates the missing row instead.
        profile = Profile.for_user(user)
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


def delete_customer_user(customer):
    """
    Remove the Django ``User`` login linked to a ``Customer`` before the customer
    itself is deleted.

    Deleting a Customer cascades to its Profile (``Profile.customer`` is
    CASCADE), but the ``User`` row would survive as an orphaned login that can
    still authenticate. Call this first so the login disappears with the
    customer. Safe to call when no linked user exists.
    """
    profile = Profile.objects.filter(customer=customer).select_related('user').first()
    if profile is not None:
        # Deleting the User cascades to the Profile as well.
        profile.user.delete()


def log_action(request, action, target='', detail=''):
    """
    Write one AuditLog row. Never raises — auditing must not break the action
    being audited.

    Args:
        request: the current HttpRequest (user + IP are read off it); may be None.
        action (str): short dotted verb, e.g. 'login', 'customer.delete'.
        target (str): human-readable object reference, e.g. 'Customer #12 (Acme)'.
        detail (str): optional free text with extra context.
    """
    from .models import AuditLog
    try:
        user = None
        ip = ''
        if request is not None:
            if getattr(request, 'user', None) is not None and request.user.is_authenticated:
                user = request.user
            forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
            ip = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
        AuditLog.objects.create(user=user, action=action, target=target[:200], detail=detail, ip_address=ip[:45])
    except Exception:
        pass


def notify_customer(customer, message, notification_type='system', order=None):
    """
    Create an in-portal notification for a customer (reuses orders.Notification).
    Never raises — a failed notification must not break the triggering action.
    """
    try:
        from orders.models import Notification
        Notification.objects.create(
            customer=customer, message=message,
            notification_type=notification_type, order=order,
        )
    except Exception:
        pass
