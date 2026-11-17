"""
accounts/context_processors.py

Exposes the current user's role and module permissions to every template, so the
back-office navigation can show only the sections a user is allowed to use.

Django templates cannot call ``profile.can('orders')`` with an argument, so we
pre-compute a plain dict of booleans (``nav_perms.orders`` etc.) here.
"""

from . import google_oauth
from .models import Profile


def _blank_perms():
    """Every module denied — used for anonymous or customer users."""
    return {m: False for m in Profile.MODULES}


def role_permissions(request):
    """
    Context processor adding:
      - ``current_profile``: the Profile instance or None.
      - ``portal_role``: the role string ('admin'/'staff'/'support'/'customer') or ''.
      - ``is_back_office_user``: True for admin/staff/support.
      - ``nav_perms``: dict {module: bool} for template nav gating.
      - ``open_ticket_count``: number of unresolved tickets (support/admin nav badge).
    """
    user = getattr(request, 'user', None)
    profile = getattr(user, 'profile', None) if (user and user.is_authenticated) else None

    # Whether to offer the "Continue with Google" button. Read from settings on
    # every render, which costs nothing, and lives here rather than in each auth
    # view so that no login or registration template can forget it and show a
    # button that leads nowhere.
    google_login_enabled = google_oauth.is_configured()

    # Which HALF is missing, for the status panel in Settings. Booleans only —
    # never the values. The client secret is a password; a template that could
    # render it would put it in the page source of an ordinary admin screen.
    #
    # This exists because hiding the button silently gave no way to tell a
    # misconfiguration from a deliberate switch-off: the only symptom was
    # "the Google button isn't appearing".
    from django.conf import settings as _dj_settings
    google_client_id_set = bool(_dj_settings.GOOGLE_OAUTH_CLIENT_ID)
    google_client_secret_set = bool(_dj_settings.GOOGLE_OAUTH_CLIENT_SECRET)

    if profile is None:
        return {
            'current_profile': None,
            'portal_role': '',
            'is_back_office_user': False,
            'portal_customer': None,
            'nav_perms': _blank_perms(),
            'open_ticket_count': 0,
            'customer_open_tickets': 0,
            'customer_unread_notifications': 0,
            'customer_cart_count': 0,
            'google_login_enabled': google_login_enabled,
            'google_client_id_set': google_client_id_set,
            'google_client_secret_set': google_client_secret_set,
        }

    nav_perms = {m: profile.can(m) for m in Profile.MODULES}

    # Ticket badges. Imported lazily to avoid a hard import cycle at app-load time.
    open_ticket_count = 0        # unresolved tickets across the desk (support/admin nav)
    customer_open_tickets = 0    # this customer's active tickets (portal nav)
    customer_unread_notifications = 0  # portal bell badge
    customer_cart_count = 0      # portal sidebar cart badge
    if profile.can('support'):
        from support.models import Ticket
        open_ticket_count = Ticket.objects.filter(status__in=Ticket.OPEN_STATUSES).count()
    elif profile.is_customer and profile.customer_id:
        from support.models import Ticket
        from orders.models import Notification
        from portal.models import CartItem
        customer_open_tickets = Ticket.objects.filter(
            customer_id=profile.customer_id, status__in=Ticket.OPEN_STATUSES
        ).count()
        customer_unread_notifications = Notification.objects.filter(
            customer_id=profile.customer_id, is_read=False
        ).count()
        # The cart badge used to be filled in only by the add-to-cart AJAX handler,
        # so it rendered empty on every fresh page load — a customer with items
        # waiting saw no badge until they added another one. Counted here instead.
        customer_cart_count = CartItem.objects.filter(
            customer_id=profile.customer_id
        ).count()

    return {
        'current_profile': profile,
        'portal_role': profile.role,
        'is_back_office_user': profile.is_back_office,
        # The linked Customer for customer-role users, so the portal navbar can
        # recognise a logged-in customer on any page (public or private) without
        # relying on the retired session['customer_id'] key.
        'portal_customer': profile.customer if profile.is_customer else None,
        'nav_perms': nav_perms,
        'open_ticket_count': open_ticket_count,
        'customer_open_tickets': customer_open_tickets,
        'customer_unread_notifications': customer_unread_notifications,
        'customer_cart_count': customer_cart_count,
        'google_login_enabled': google_login_enabled,
        'google_client_id_set': google_client_id_set,
        'google_client_secret_set': google_client_secret_set,
    }
