"""
accounts/context_processors.py

Exposes the current user's role and module permissions to every template, so the
back-office navigation can show only the sections a user is allowed to use.

Django templates cannot call ``profile.can('orders')`` with an argument, so we
pre-compute a plain dict of booleans (``nav_perms.orders`` etc.) here.
"""

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

    if profile is None:
        return {
            'current_profile': None,
            'portal_role': '',
            'is_back_office_user': False,
            'portal_customer': None,
            'nav_perms': _blank_perms(),
            'open_ticket_count': 0,
        }

    nav_perms = {m: profile.can(m) for m in Profile.MODULES}

    # Only compute the ticket badge for people who can see the support queue.
    open_ticket_count = 0
    if profile.can('support'):
        # Imported lazily to avoid a hard import cycle at app-load time.
        from support.models import Ticket
        open_ticket_count = Ticket.objects.filter(status__in=Ticket.OPEN_STATUSES).count()

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
    }
