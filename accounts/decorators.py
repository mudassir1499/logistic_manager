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


def api_token_required(module=None):
    """
    Guard a JSON endpoint that is called by the browser extension.

    The extension runs on 1688.com pages, so it has no session cookie and no CSRF
    token. It authenticates with ``Authorization: Bearer <token>`` instead, where
    the token was issued by ``ApiToken.issue``.

    On success the decorator sets ``request.user`` to the token's owner and
    ``request.api_token`` to the token row, so downstream code can treat the
    request as an ordinary authenticated one.

    Args:
        module (str | None): When given, the token's owner must also hold that
            module permission. This is what stops a customer-role token from
            reaching the product-import endpoint — a token never grants more
            than the person it belongs to already has.

    Returns:
        A decorator. Failures return JSON with 401 (bad/missing token) or 403
        (valid token, insufficient permission) rather than redirecting, because
        the caller is a script and cannot follow a login redirect.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            from django.http import JsonResponse
            from django.utils import timezone

            from .models import ApiToken

            header = request.META.get('HTTP_AUTHORIZATION', '')
            if not header.startswith('Bearer '):
                return JsonResponse(
                    {'success': False, 'error': 'missing_token',
                     'message': 'Authorization: Bearer <token> header required.'},
                    status=401,
                )

            raw = header[len('Bearer '):].strip()
            if not raw:
                return JsonResponse(
                    {'success': False, 'error': 'missing_token',
                     'message': 'Empty bearer token.'},
                    status=401,
                )

            token = (
                ApiToken.objects
                .select_related('user', 'user__profile')
                .filter(token_hash=ApiToken.hash_token(raw), is_active=True)
                .first()
            )
            # Same response for "no such token" and "revoked token" — telling the
            # caller which one it was would confirm that a guessed token exists.
            if token is None or not token.user.is_active:
                return JsonResponse(
                    {'success': False, 'error': 'invalid_token',
                     'message': 'Token is invalid or has been revoked.'},
                    status=401,
                )

            profile = getattr(token.user, 'profile', None)
            if module and (profile is None or not profile.can(module)):
                return JsonResponse(
                    {'success': False, 'error': 'forbidden',
                     'message': f'This account may not use the {module} module.'},
                    status=403,
                )

            # update_fields so this write cannot clobber a concurrent edit to
            # any other column on the row.
            token.last_used_at = timezone.now()
            token.save(update_fields=['last_used_at'])

            request.user = token.user
            request.api_token = token
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
