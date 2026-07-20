"""
accounts/decorators.py

Access-control decorators built on top of the unified ``Profile`` roles. These
replace the two old, weaker guards:

  - the back-office's blanket ``@login_required`` (which let ANY logged-in account
    into every module), and
  - the portal's hand-rolled ``customer_login_required`` (a separate session hack).

Everything now flows through Django's auth (``request.user``) plus the role and
per-module permissions stored on ``request.user.profile``.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def _profile(user):
    """Safely fetch a user's Profile, or None if missing/anonymous."""
    if not user or not user.is_authenticated:
        return None
    return getattr(user, 'profile', None)


def module_required(module):
    """
    Guard a back-office view so only users allowed to use ``module`` may enter.

    Behaviour:
      - Anonymous users are redirected to the login page (with ``?next=``).
      - Logged-in users who lack the permission get a 403 (PermissionDenied).
      - Admins always pass; support passes for the 'support' module; staff pass
        when their matching ``perm_<module>`` flag is set.

    Args:
        module (str): One of ``Profile.MODULES`` (e.g. 'orders', 'khata').
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            profile = _profile(request.user)
            if profile is None:
                return redirect_to_login(request.get_full_path())
            if not profile.can(module):
                raise PermissionDenied(
                    f'Your account does not have access to the {module} section.'
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def staff_required(view_func):
    """
    Allow any internal back-office account (admin, staff, or support) through.

    Use this for pages that every internal user may see regardless of module
    grants (e.g. a shared landing page). Customers are rejected with a 403;
    anonymous users are sent to login.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        profile = _profile(request.user)
        if profile is None:
            return redirect_to_login(request.get_full_path())
        if not profile.is_back_office:
            raise PermissionDenied('This area is for staff only.')
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    """Restrict a view to the admin (owner) role only — e.g. settings, user mgmt."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        profile = _profile(request.user)
        if profile is None:
            return redirect_to_login(request.get_full_path())
        if not profile.is_admin:
            raise PermissionDenied('This area is restricted to administrators.')
        return view_func(request, *args, **kwargs)
    return wrapper


def customer_required(view_func):
    """
    Guard a customer-portal view.

    Ensures the user is logged in AND holds the ``customer`` role, then attaches
    the linked ``Customer`` record to ``request.customer`` so existing portal
    views keep working unchanged (they already read ``request.customer``).
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        profile = _profile(request.user)
        if profile is None:
            return redirect_to_login(request.get_full_path())
        if not profile.is_customer or profile.customer is None:
            raise PermissionDenied('This area is for customers only.')
        # Mirror the old decorator's contract: the Customer is on the request.
        request.customer = profile.customer
        return view_func(request, *args, **kwargs)
    return wrapper
