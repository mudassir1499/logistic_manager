"""
accounts/views.py

The single, unified authentication surface for the whole platform. Every human —
admin, staff, support, customer — logs in here through Django's auth framework.

Sections:
  1. Helpers (login lookup, cache-based rate limiting)
  2. Login / Logout
  3. Self-registration (creates a Customer + User + Profile)
  4. Password reset (Django token generator, emailed via the DB-configured SMTP)
  5. Admin user & role management (create staff/support, toggle module permissions)
"""

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import (
    url_has_allowed_host_and_scheme,
    urlsafe_base64_encode,
    urlsafe_base64_decode,
)

from customers.models import Customer
from settings_manager.models import CompanySettings
from utils.email_utils import send_typed_email

from .decorators import admin_required
from .models import Profile
from .validators import validate_password_strength


# =============================================================================
# 1. HELPERS
# =============================================================================

# Rate-limit configuration for login. Cache-backed (the project already uses a
# DatabaseCache), keyed by client IP, so it survives cookie clearing — unlike the
# old session-based counter it replaces.
LOGIN_MAX_ATTEMPTS = 8
LOGIN_LOCKOUT_SECONDS = 900  # 15 minutes


def _client_ip(request):
    """Best-effort client IP, honouring the proxy header cPanel/Apache forwards."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


def _attempts_key(request):
    return f'login_attempts:{_client_ip(request)}'


def _get_attempts(request):
    """Read the failed-attempt counter, tolerating an unavailable cache backend.

    Rate limiting is defense-in-depth; if the cache table is missing or the
    backend is down it must never block a legitimate login, so we fail open.
    """
    try:
        return cache.get(_attempts_key(request), 0)
    except Exception:
        return 0


def _set_attempts(request, value):
    """Store the failed-attempt counter, ignoring cache-backend errors."""
    try:
        cache.set(_attempts_key(request), value, LOGIN_LOCKOUT_SECONDS)
    except Exception:
        pass


def _clear_attempts(request):
    """Reset the failed-attempt counter, ignoring cache-backend errors."""
    try:
        cache.delete(_attempts_key(request))
    except Exception:
        pass


def _find_user(identifier):
    """
    Look up a User by username OR email (customers log in with their email, which
    is also their username, but staff may use a plain username).
    """
    identifier = (identifier or '').strip()
    if not identifier:
        return None
    user = User.objects.filter(username__iexact=identifier).first()
    if user is None:
        user = User.objects.filter(email__iexact=identifier).first()
    return user


def _safe_next(request):
    """Return a safe ?next= redirect target, or None."""
    nxt = request.POST.get('next') or request.GET.get('next')
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return None


def _post_login_redirect(request, user):
    """Where to send a user right after a successful login."""
    nxt = _safe_next(request)
    if nxt:
        return redirect(nxt)
    profile = getattr(user, 'profile', None)
    if profile is not None:
        return redirect(reverse(profile.default_landing()))
    return redirect('/')


# =============================================================================
# 2. LOGIN / LOGOUT
# =============================================================================

def login_view(request):
    """
    Unified login for all roles.

    GET  -> render the login card.
    POST -> validate credentials with rate limiting; on success start a Django
            session and redirect by role (?next wins if safe).
    """
    settings = CompanySettings.get_settings()

    # Already authenticated? Send them to their home rather than showing login.
    if request.user.is_authenticated:
        return _post_login_redirect(request, request.user)

    attempts = _get_attempts(request)
    is_locked = attempts >= LOGIN_MAX_ATTEMPTS

    if request.method == 'POST':
        if is_locked:
            messages.error(request, 'Too many failed attempts. Please try again in a few minutes.')
        else:
            identifier = request.POST.get('username', '').strip()
            password = request.POST.get('password', '')
            user_obj = _find_user(identifier)
            user = None
            if user_obj is not None:
                user = authenticate(request, username=user_obj.username, password=password)

            if user is not None and user.is_active:
                login(request, user)
                _clear_attempts(request)
                return _post_login_redirect(request, user)

            # Failed: bump the attempt counter (generic message avoids enumeration).
            _set_attempts(request, attempts + 1)
            messages.error(request, 'Invalid credentials. Please check your email/username and password.')

    return render(request, 'accounts/login.html', {
        'settings': settings,
        'next': request.GET.get('next', ''),
        'is_locked': is_locked,
    })


def logout_view(request):
    """Log the current user out and return to the public homepage."""
    logout(request)
    return redirect('front_page')


# =============================================================================
# 3. SELF-REGISTRATION (customer accounts)
# =============================================================================

def register_view(request):
    """
    Public self-registration. Creates a Customer business record, a Django User
    login, and a customer-role Profile linking them — all in one transaction.
    """
    settings = CompanySettings.get_settings()

    if request.user.is_authenticated:
        return _post_login_redirect(request, request.user)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        address = request.POST.get('address', '').strip()

        error = None
        if not all([name, phone, email, password]):
            error = 'Please fill in all required fields.'
        else:
            error = validate_password_strength(password)
        if error is None and (Customer.objects.filter(email=email).exists()
                              or User.objects.filter(username__iexact=email).exists()):
            error = 'An account with this email already exists.'

        if error:
            messages.error(request, error)
            return render(request, 'accounts/register.html', {
                'settings': settings,
                'form_data': {'name': name, 'phone': phone, 'email': email, 'address': address},
            })

        with transaction.atomic():
            customer = Customer.objects.create(
                name=name, phone=phone, email=email, address=address, is_active=True,
            )
            # Keep the legacy Customer.password hash in sync (mirror) so any code
            # still reading it during the transition keeps working.
            customer.set_password(password)
            customer.save(update_fields=['password'])

            user = User.objects.create_user(username=email, email=email, password=password)
            # The post_save signal created a default (customer) Profile; point it
            # at this Customer.
            profile = user.profile
            profile.role = Profile.ROLE_CUSTOMER
            profile.customer = customer
            profile.save()

        login(request, user)

        send_typed_email(
            email_type='security',
            subject=f'Welcome to {settings.company_name} — Account Created',
            message=(
                f"Hi {customer.name},\n\n"
                f"Your account has been created successfully on {settings.company_name}.\n"
                f"You can now log in to the portal at any time.\n\n"
                f"If you did not create this account, please contact us immediately.\n\n"
                f"Best regards,\n{settings.company_name}"
            ),
            recipient_list=[customer.email],
            fail_silently=True,
        )
        return redirect('portal_dashboard')

    return render(request, 'accounts/register.html', {'settings': settings, 'form_data': {}})


# =============================================================================
# 4. PASSWORD RESET (token-based, emailed via the security SMTP profile)
# =============================================================================

def password_reset_request(request):
    """
    Step 1: the user submits their email. If a matching active account exists we
    email a signed reset link. The response is identical either way so the
    endpoint cannot be used to enumerate registered emails.
    """
    settings = CompanySettings.get_settings()

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        user = _find_user(email)
        if user is not None and user.is_active:
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = request.build_absolute_uri(
                reverse('account_password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token})
            )
            send_typed_email(
                email_type='security',
                subject=f'Password Reset — {settings.company_name}',
                message=(
                    f"Hi {user.get_username()},\n\n"
                    f"You requested to reset your password.\n\n"
                    f"Click the link below to choose a new one:\n{reset_url}\n\n"
                    f"If you did not request this, you can safely ignore this email.\n\n"
                    f"Best regards,\n{settings.company_name}"
                ),
                recipient_list=[user.email or email],
                fail_silently=True,
            )
        messages.success(
            request,
            'If an account with that email exists, we have sent password reset instructions.'
        )
        return redirect('account_login')

    return render(request, 'accounts/password_reset.html', {'settings': settings})


def password_reset_confirm(request, uidb64, token):
    """
    Step 2: validate the signed link and let the user set a new password. On
    success the new password is written to the User and mirrored to the linked
    Customer (legacy field) so both stay consistent.
    """
    settings = CompanySettings.get_settings()

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    valid = user is not None and default_token_generator.check_token(user, token)
    if not valid:
        messages.error(request, 'This password reset link is invalid or has expired. Please request a new one.')
        return redirect('account_password_reset')

    if request.method == 'POST':
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')
        error = None
        if password != confirm:
            error = 'The two passwords do not match.'
        else:
            error = validate_password_strength(password)

        if error:
            messages.error(request, error)
            return render(request, 'accounts/password_reset_confirm.html', {'settings': settings, 'valid': True})

        user.set_password(password)
        user.save(update_fields=['password'])
        # Mirror to the linked Customer's legacy password field.
        profile = getattr(user, 'profile', None)
        if profile and profile.customer_id:
            profile.customer.set_password(password)
            profile.customer.save(update_fields=['password'])

        messages.success(request, 'Your password has been reset. Please log in with your new password.')
        return redirect('account_login')

    return render(request, 'accounts/password_reset_confirm.html', {'settings': settings, 'valid': True})


# =============================================================================
# 5. ADMIN USER & ROLE MANAGEMENT
# =============================================================================
# Admin-only pages to create and manage internal (staff/support/admin) accounts
# and their per-module permissions. Customer logins are managed from the existing
# customer-management screens; these pages focus on the internal team.

STAFF_ROLES = (Profile.ROLE_ADMIN, Profile.ROLE_STAFF, Profile.ROLE_SUPPORT)


@admin_required
def user_list(request):
    """List internal users (admin/staff/support) with their role."""
    settings = CompanySettings.get_settings()
    profiles = (Profile.objects.filter(role__in=STAFF_ROLES)
                .select_related('user').order_by('role', 'user__username'))
    return render(request, 'accounts/user_list.html', {
        'profiles': profiles,
        'settings': settings,
    })


def _apply_profile_perms(profile, request):
    """Read the module-permission checkboxes off the POST and store them."""
    for module, field in Profile.MODULE_FIELD_MAP.items():
        setattr(profile, field, request.POST.get(f'perm_{module}') == 'on')


@admin_required
def user_create(request):
    """Create a new internal (staff/support/admin) account."""
    settings = CompanySettings.get_settings()

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        role = request.POST.get('role', Profile.ROLE_STAFF)

        error = None
        if not username or not password:
            error = 'Username and password are required.'
        elif role not in STAFF_ROLES:
            error = 'Please choose a valid role.'
        elif User.objects.filter(username__iexact=username).exists():
            error = 'A user with that username already exists.'
        else:
            error = validate_password_strength(password)

        if error:
            messages.error(request, error)
            return render(request, 'accounts/user_form.html', {
                'settings': settings, 'roles': Profile.ROLE_CHOICES, 'modules': Profile.MODULES,
                'target': None, 'form_data': {'username': username, 'email': email, 'role': role},
            })

        with transaction.atomic():
            user = User.objects.create_user(username=username, email=email, password=password)
            # Only the admin (owner) role gets Django-admin access. Staff and
            # support reach everything they need through the role-gated portal,
            # so we keep /admin/ owner-only and avoid an is_staff side-door.
            user.is_superuser = (role == Profile.ROLE_ADMIN)
            user.is_staff = user.is_superuser
            user.save(update_fields=['is_staff', 'is_superuser'])

            profile = user.profile
            profile.role = role
            profile.customer = None
            _apply_profile_perms(profile, request)
            profile.save()

        messages.success(request, f'User "{username}" created.')
        return redirect('user_list')

    return render(request, 'accounts/user_form.html', {
        'settings': settings, 'roles': Profile.ROLE_CHOICES, 'modules': Profile.MODULES,
        'target': None, 'form_data': {},
    })


@admin_required
def user_edit(request, user_id):
    """Edit an internal user's role, module permissions, active state, password."""
    settings = CompanySettings.get_settings()
    target = get_object_or_404(User, id=user_id)
    profile = target.profile

    if request.method == 'POST':
        role = request.POST.get('role', profile.role)
        if role in STAFF_ROLES:
            profile.role = role
        target.email = request.POST.get('email', '').strip().lower()
        target.is_active = request.POST.get('is_active') == 'on'
        # Django-admin access (is_staff) is reserved for the admin role only.
        target.is_superuser = (profile.role == Profile.ROLE_ADMIN)
        target.is_staff = target.is_superuser

        new_password = request.POST.get('password', '').strip()
        if new_password:
            strength_error = validate_password_strength(new_password)
            if strength_error:
                messages.error(request, strength_error)
                return redirect('user_edit', user_id=target.id)
            target.set_password(new_password)

        _apply_profile_perms(profile, request)

        with transaction.atomic():
            target.save()
            profile.save()

        messages.success(request, f'User "{target.username}" updated.')
        return redirect('user_list')

    return render(request, 'accounts/user_form.html', {
        'settings': settings, 'roles': Profile.ROLE_CHOICES, 'modules': Profile.MODULES,
        'target': target, 'profile': profile, 'form_data': {
            'username': target.username, 'email': target.email, 'role': profile.role,
        },
    })


@admin_required
def user_delete(request, user_id):
    """Deactivate (soft-delete) an internal user. Never delete yourself."""
    target = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        if target.id == request.user.id:
            messages.error(request, 'You cannot deactivate your own account.')
        else:
            target.is_active = False
            target.save(update_fields=['is_active'])
            messages.success(request, f'User "{target.username}" deactivated.')
    return redirect('user_list')
