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

import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
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

from . import google_oauth
from .decorators import admin_required
from .models import Profile
from .validators import validate_password_strength

# Google sign-in failures are logged with their cause. The user only ever sees a
# short message, because the detail (a redirect_uri_mismatch, an invalid_grant)
# is a deployment problem for the operator, not something they can act on.
logger = logging.getLogger(__name__)


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


def _complete_login(request, user):
    """
    Finish authentication: start the session, restore legacy session keys,
    audit the event, and redirect by role. Shared by the password-only path and
    the OTP path so both behave identically.
    """
    from .services import log_action
    login(request, user)
    # Legacy compatibility: several public portal views still read
    # session['customer_id'] to personalise pages for a logged-in customer.
    profile = getattr(user, 'profile', None)
    if profile is not None and profile.is_customer and profile.customer_id:
        request.session['customer_id'] = profile.customer_id
    log_action(request, 'login', target=user.get_username())
    return _post_login_redirect(request, user)


# --- Two-factor (emailed one-time code) helpers ------------------------------

OTP_TTL_SECONDS = 600   # a code is valid for 10 minutes
OTP_MAX_ATTEMPTS = 5


def _start_otp(request, user):
    """Generate a 6-digit code, stash the pending login in the session, email it."""
    import secrets
    from django.utils import timezone as tz
    code = f'{secrets.randbelow(1000000):06d}'
    request.session['otp_user_id'] = user.pk
    request.session['otp_code'] = code
    request.session['otp_expires'] = (tz.now() + tz.timedelta(seconds=OTP_TTL_SECONDS)).isoformat()
    request.session['otp_attempts'] = 0
    # Preserve ?next= across the OTP page.
    nxt = _safe_next(request)
    if nxt:
        request.session['otp_next'] = nxt
    settings = CompanySettings.get_settings()
    send_typed_email(
        email_type='security',
        subject=f'Your login code — {settings.company_name}',
        message=(
            f'Your one-time login code is: {code}\n\n'
            f'It expires in 10 minutes. If you did not try to log in, '
            f'change your password immediately.\n\n{settings.company_name}'
        ),
        recipient_list=[user.email or user.get_username()],
        fail_silently=True,
    )


def _clear_otp(request):
    for k in ('otp_user_id', 'otp_code', 'otp_expires', 'otp_attempts', 'otp_next'):
        request.session.pop(k, None)


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

    # Already authenticated with a usable profile? Send them to their home
    # rather than showing the login form.
    #
    # We deliberately only auto-redirect when a profile exists. A "half"
    # session — authenticated but with no Profile row — would otherwise be
    # bounced to the homepage by _post_login_redirect (its profile-is-None
    # fallback), so the user sees a "Customer Login" button, clicks it, and
    # lands right back on the homepage without ever reaching the form. Clearing
    # cookies was the only escape. Falling through to render() lets such a
    # session simply log in again and get a clean session.
    if request.user.is_authenticated and getattr(request.user, 'profile', None) is not None:
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
                _clear_attempts(request)
                profile = getattr(user, 'profile', None)

                # Two-factor step: if the account opted in, do NOT start the
                # session yet — email a one-time code and ask for it first.
                if profile is not None and profile.two_factor_enabled:
                    _start_otp(request, user)
                    return redirect('account_otp')

                return _complete_login(request, user)

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
        # Legacy compatibility: public portal views personalise via this key.
        request.session['customer_id'] = customer.id

        # New accounts start unverified — send the confirmation link. They can
        # use the portal meanwhile; a banner nudges them until verified.
        _send_verification_email(request, user)

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
# 3b. SIGN IN WITH GOOGLE
# =============================================================================
# Two views: one sends the browser to Google, one handles the return trip. The
# protocol itself lives in accounts/google_oauth.py; what is here is the part
# specific to this business - which account the person ends up in.
# =============================================================================

def google_login_start(request):
    """
    Send the browser to Google's consent screen.

    Args:
        request (HttpRequest): may carry ?next= to return to after signing in.

    Returns:
        HttpResponseRedirect: to Google, or back to login if not configured.
    """
    if request.user.is_authenticated:
        return _post_login_redirect(request, request.user)

    if not google_oauth.is_configured():
        messages.error(request, 'Google sign-in is not set up on this site yet.')
        return redirect('account_login')

    return redirect(google_oauth.start(request, _safe_next(request) or ''))


def google_login_callback(request):
    """
    Handle the return from Google: verify, then sign the person in.

    Args:
        request (HttpRequest): carries ?code= and ?state= from Google.

    Returns:
        HttpResponseRedirect: to the post-login landing page, or back to login
        with an error message.
    """
    if not google_oauth.is_configured():
        messages.error(request, 'Google sign-in is not set up on this site yet.')
        return redirect('account_login')

    # The person pressed Cancel, or Google refused. Not an error worth alarming
    # anyone about - put them back on the login page.
    if request.GET.get('error'):
        messages.info(request, 'Google sign-in was cancelled.')
        return redirect('account_login')

    nonce = request.session.pop(google_oauth.SESSION_NONCE, '')
    next_url = request.session.pop(google_oauth.SESSION_NEXT, '') or ''

    try:
        google_oauth.consume_state(request, request.GET.get('state'))
        code = request.GET.get('code')
        if not code:
            raise google_oauth.GoogleAuthError('Google did not return a sign-in code.')
        tokens = google_oauth.exchange_code(request, code)
        identity = google_oauth.decode_id_token(tokens['id_token'], nonce)
    except google_oauth.GoogleAuthError as exc:
        logger.warning('Google sign-in failed: %s', exc, exc_info=True)
        messages.error(request, str(exc))
        return redirect('account_login')

    try:
        user, created = _user_from_google(identity)
    except PermissionDenied as exc:
        messages.error(request, str(exc))
        return redirect('account_login')

    if created:
        _send_google_welcome_email(request, user)

    # _complete_login already handles the session, the legacy customer_id key,
    # the audit entry and the role-based landing page, so the Google path and
    # the password path cannot drift apart.
    # The ?next= target was parked in the session before leaving for Google,
    # because Google controls the callback URL and will not carry it for us.
    # Putting it back on request.GET is what lets _complete_login find it via
    # the same _safe_next() the password path uses - which also means it gets
    # the same host validation, so a tampered session value still cannot
    # redirect anyone off-site.
    if next_url:
        request.GET = request.GET.copy()
        request.GET['next'] = next_url
    return _complete_login(request, user)


def _user_from_google(identity):
    """
    Find or create the User behind a verified Google identity.

    Args:
        identity (dict): validated claims from google_oauth.decode_id_token.

    Returns:
        tuple[User, bool]: the user, and whether this call created them.

    Raises:
        PermissionDenied: when the matched account may not use Google sign-in.

    MATCHING IS BY EMAIL, and that is only safe because the caller has already
    established that Google verified the address. An unverified address is
    rejected before reaching here; without that check this function would let
    anyone claim an existing account by putting its address on a Google profile.

    BACK-OFFICE ACCOUNTS ARE REFUSED. Google sign-in is for customers. An
    admin or staff login is a far more valuable target, and letting it be
    reached through an external identity provider means the security of the
    back office becomes the security of somebody's personal Google account -
    including its recovery options, which we do not control. Staff keep their
    password (and the existing one-time-code step).
    """
    email = identity['email']

    user = (User.objects.filter(username__iexact=email).first()
            or User.objects.filter(email__iexact=email).first())

    if user is not None:
        if not user.is_active:
            raise PermissionDenied('That account has been deactivated. Please contact us.')
        profile = getattr(user, 'profile', None)
        if profile is None or not profile.is_customer:
            raise PermissionDenied(
                'That email belongs to a staff account. Please sign in with your password.'
            )
        # Google has just confirmed the address, so an account still waiting on
        # our own verification email can stop waiting.
        if not profile.email_verified:
            profile.email_verified = True
            profile.save(update_fields=['email_verified'])
        return user, False

    # .get(), not [..]: Google's userinfo response is not guaranteed to carry
    # every name field. `name` is absent on some Workspace accounts, and
    # `family_name` is absent for anyone with a mononym - which is common in
    # Indonesia, parts of India and Brazil, all places this catalogue now has
    # landing pages for.
    display_name = (identity.get('name') or '').strip() or email.split('@')[0]

    with transaction.atomic():
        # An existing Customer with no login happens when the business record was
        # created by staff or imported before the person ever registered. Reuse
        # it rather than colliding with the unique email.
        customer = Customer.objects.filter(email__iexact=email).first()
        if customer is None:
            # phone and address are required for an order but not for an
            # account. Leaving them blank lets the person in now; the portal
            # asks for them at checkout, where they are actually needed.
            customer = Customer.objects.create(
                name=display_name, phone='', address='', email=email, is_active=True,
            )

        # No password is set, so Django stores an unusable one. That is correct:
        # this account has no password to guess. If the person later wants one,
        # the existing password-reset flow gives them a way to set it.
        user = User.objects.create_user(username=email, email=email)
        # A missing given_name used to raise KeyError HERE - after the User and
        # Customer rows were already written. The account survived without its
        # customer link, so the person could neither finish signing up nor try
        # again: the retry found the half-made account and let them in to a
        # portal that immediately refused them for having no Customer attached.
        # Falling back through the display name keeps the row consistent.
        first, _, last = display_name.partition(' ')
        user.first_name = (identity.get('given_name') or first)[:30]
        user.last_name = (identity.get('family_name') or last)[:150]
        user.save(update_fields=['first_name', 'last_name'])

        profile = user.profile          # created by the post_save signal
        profile.role = Profile.ROLE_CUSTOMER
        profile.customer = customer
        profile.email_verified = True   # Google verified it; ours would be noise
        profile.save()

    return user, True


def _send_google_welcome_email(request, user):
    """Send the same welcome mail a password signup gets. Never blocks sign-in."""
    settings_obj = CompanySettings.get_settings()
    name = user.get_full_name() or user.username
    send_typed_email(
        email_type='security',
        subject=f'Welcome to {settings_obj.company_name} — Account Created',
        message=(
            f"Hi {name},\n\n"
            f"Your account has been created on {settings_obj.company_name} "
            f"using your Google account ({user.email}).\n"
            f"You can sign in any time with the 'Continue with Google' button.\n\n"
            f"If you did not create this account, please contact us immediately.\n\n"
            f"Best regards,\n{settings_obj.company_name}"
        ),
        recipient_list=[user.email],
        fail_silently=True,
    )


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
            profile.two_factor_enabled = request.POST.get('two_factor_enabled') == 'on'
            profile.save()

        from .services import log_action
        log_action(request, 'user.create', target=username, detail=f'role={role}')
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
    # Not `target.profile`: that raises RelatedObjectDoesNotExist (a 500) for any
    # account created before accounts/signals.py existed, which is exactly the set
    # of accounts an admin is most likely to open this page to repair.
    profile = Profile.for_user(target)

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
        profile.two_factor_enabled = request.POST.get('two_factor_enabled') == 'on'

        with transaction.atomic():
            target.save()
            profile.save()

        from .services import log_action
        log_action(request, 'user.update', target=target.username, detail=f'role={profile.role}')
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
            from .services import log_action
            log_action(request, 'user.deactivate', target=target.username)
            messages.success(request, f'User "{target.username}" deactivated.')
    return redirect('user_list')


# =============================================================================
# 6. SELF-SERVICE ACCOUNT SETTINGS ("My Account")
# =============================================================================
# Any authenticated user can view their own role/permissions and change their
# own password here — previously only an admin could reset a staff password.

@login_required
def my_account(request):
    """Show the current user's account details and let them change their password."""
    settings = CompanySettings.get_settings()
    profile = getattr(request.user, 'profile', None)

    if request.method == 'POST':
        # --- Two-factor toggle (admin only — policy is set by the administrator,
        #     not self-service, so a compromised account can't switch it off) ---
        if request.POST.get('action') == 'toggle_2fa':
            from .services import log_action
            if profile is None or not profile.is_admin:
                messages.error(request, 'Only an administrator can change two-factor authentication.')
                return redirect('my_account')
            profile.two_factor_enabled = not profile.two_factor_enabled
            profile.save(update_fields=['two_factor_enabled'])
            state = 'enabled' if profile.two_factor_enabled else 'disabled'
            log_action(request, f'2fa.{state}', target=request.user.get_username())
            messages.success(request, f'Two-factor authentication {state}.')
            return redirect('my_account')

        current = request.POST.get('current_password', '')
        new = request.POST.get('new_password', '')
        confirm = request.POST.get('confirm_password', '')

        if not request.user.check_password(current):
            messages.error(request, 'Your current password is incorrect.')
        elif new != confirm:
            messages.error(request, 'The new passwords do not match.')
        else:
            error = validate_password_strength(new)
            if error:
                messages.error(request, error)
            else:
                request.user.set_password(new)
                request.user.save(update_fields=['password'])
                # Mirror to the linked Customer's legacy hash if this is a customer.
                if profile and profile.customer_id:
                    profile.customer.set_password(new)
                    profile.customer.save(update_fields=['password'])
                # Keep the current session valid after the password rotation.
                update_session_auth_hash(request, request.user)
                messages.success(request, 'Your password has been updated.')
        return redirect('my_account')

    return render(request, 'accounts/my_account.html', {
        'settings': settings,
        'profile': profile,
        'granted_modules': profile.granted_modules() if profile else [],
    })


# =============================================================================
# 7. TWO-FACTOR AUTHENTICATION (emailed one-time code)
# =============================================================================

def otp_view(request):
    """
    Second login step for accounts with 2FA enabled: verify the emailed code.

    The pending login lives in the session (set by ``_start_otp``); no Django
    session is started until the code checks out.
    """
    from django.utils import timezone as tz
    from .services import log_action

    user_id = request.session.get('otp_user_id')
    if not user_id:
        return redirect('account_login')
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        _clear_otp(request)
        return redirect('account_login')

    settings = CompanySettings.get_settings()

    if request.method == 'POST':
        if request.POST.get('action') == 'resend':
            _start_otp(request, user)
            messages.success(request, 'A new code has been sent to your email.')
            return redirect('account_otp')

        expires_raw = request.session.get('otp_expires', '')
        attempts = request.session.get('otp_attempts', 0)
        code = request.POST.get('code', '').strip()

        expired = True
        try:
            expired = tz.now() > tz.datetime.fromisoformat(expires_raw)
        except (TypeError, ValueError):
            pass

        if attempts >= OTP_MAX_ATTEMPTS or expired:
            _clear_otp(request)
            messages.error(request, 'That code has expired. Please log in again.')
            return redirect('account_login')

        if code and code == request.session.get('otp_code'):
            # Restore ?next= saved before the OTP step, then finish the login.
            nxt = request.session.get('otp_next')
            _clear_otp(request)
            if nxt:
                request.POST = request.POST.copy()
                request.POST['next'] = nxt
            return _complete_login(request, user)

        request.session['otp_attempts'] = attempts + 1
        log_action(request, '2fa.failed_code', target=user.get_username())
        messages.error(request, 'Incorrect code. Please try again.')

    return render(request, 'accounts/otp.html', {
        'settings': settings,
        'email_hint': (user.email or user.get_username()),
    })


# =============================================================================
# 8. EMAIL VERIFICATION
# =============================================================================

def _send_verification_email(request, user):
    """Email a signed verification link (valid 7 days) to the user."""
    from django.core import signing
    settings = CompanySettings.get_settings()
    token = signing.TimestampSigner(salt='email-verify').sign(str(user.pk))
    url = request.build_absolute_uri(reverse('account_verify_email', kwargs={'token': token}))
    send_typed_email(
        email_type='security',
        subject=f'Verify your email — {settings.company_name}',
        message=(
            f'Hi {user.get_username()},\n\n'
            f'Please confirm your email address by clicking the link below:\n{url}\n\n'
            f'The link is valid for 7 days.\n\n{settings.company_name}'
        ),
        recipient_list=[user.email or user.get_username()],
        fail_silently=True,
    )


def verify_email(request, token):
    """Confirm an email address from the signed link."""
    from django.core import signing
    try:
        user_pk = signing.TimestampSigner(salt='email-verify').unsign(token, max_age=7 * 24 * 3600)
        user = User.objects.get(pk=user_pk)
    except (signing.BadSignature, signing.SignatureExpired, User.DoesNotExist):
        messages.error(request, 'This verification link is invalid or has expired.')
        return redirect('account_login')

    profile = getattr(user, 'profile', None)
    if profile is not None and not profile.email_verified:
        profile.email_verified = True
        profile.save(update_fields=['email_verified'])
    messages.success(request, 'Your email address has been verified. Thank you!')
    if request.user.is_authenticated:
        return redirect('portal_dashboard' if profile and profile.is_customer else 'dashboard')
    return redirect('account_login')


@login_required
def resend_verification(request):
    """Re-send the verification email for the logged-in user."""
    profile = getattr(request.user, 'profile', None)
    if profile is not None and not profile.email_verified:
        _send_verification_email(request, request.user)
        messages.success(request, 'Verification email sent — please check your inbox.')
    return redirect(request.META.get('HTTP_REFERER') or '/')


# =============================================================================
# 9. GLOBAL SEARCH (back-office, Ctrl+K)
# =============================================================================

def global_search(request):
    """
    JSON search across orders, customers, and products for the sidebar search.
    Results respect module permissions: each section appears only if the current
    user may access that module.
    """
    from django.http import JsonResponse
    profile = getattr(request.user, 'profile', None) if request.user.is_authenticated else None
    if profile is None or not profile.is_back_office:
        return JsonResponse({'results': []}, status=403)

    q = request.GET.get('q', '').strip()
    results = []
    if len(q) >= 2:
        if profile.can('orders'):
            from orders.models import Order
            order_qs = Order.objects.select_related('customer')
            digits = q.lstrip('#')
            if digits.isdigit():
                order_qs = order_qs.filter(id=int(digits))
            else:
                order_qs = order_qs.filter(customer__name__icontains=q)
            for o in order_qs.order_by('-date')[:5]:
                results.append({'icon': 'bi-cart-check', 'label': f'Order #{o.id} — {o.customer.name}',
                                'url': f'/orders/?q={o.id}', 'section': 'Orders'})
        if profile.can('customers'):
            from customers.models import Customer as _Customer
            for c in _Customer.objects.filter(name__icontains=q)[:5]:
                results.append({'icon': 'bi-person', 'label': c.name,
                                'url': f'/customers/?q={c.name}', 'section': 'Customers'})
        if profile.can('products'):
            from products.models import Product
            from django.db.models import Q as _Q
            for p in Product.objects.filter(_Q(name__icontains=q) | _Q(sku__icontains=q))[:5]:
                results.append({'icon': 'bi-box-seam', 'label': p.name,
                                'url': f'/products/?q={p.name}', 'section': 'Products'})
    return JsonResponse({'results': results})


# =============================================================================
# 10. AUDIT LOG VIEWER (admin only)
# =============================================================================

@admin_required
def audit_log(request):
    """Paginated, filterable view of the audit trail."""
    from django.core.paginator import Paginator
    from .models import AuditLog

    settings = CompanySettings.get_settings()
    qs = AuditLog.objects.select_related('user')
    action = request.GET.get('action', '').strip()
    q = request.GET.get('q', '').strip()
    if action:
        qs = qs.filter(action=action)
    if q:
        from django.db.models import Q as _Q
        qs = qs.filter(_Q(target__icontains=q) | _Q(detail__icontains=q) | _Q(user__username__icontains=q))

    paginator = Paginator(qs, 40)
    page_obj = paginator.get_page(request.GET.get('page'))
    actions = AuditLog.objects.values_list('action', flat=True).distinct().order_by('action')

    return render(request, 'accounts/audit_log.html', {
        'settings': settings,
        'page_obj': page_obj,
        'entries': page_obj,
        'actions': actions,
        'current_action': action,
        'q': q,
    })


# =============================================================================
# 10. API TOKENS (browser extension access)
# =============================================================================

@login_required
def api_tokens(request):
    """
    Issue and revoke the bearer tokens used by the 1688 browser extension.

    The extension runs on alibaba.com pages and has no session cookie, so it
    authenticates with a token instead. Tokens are shown ONCE, immediately after
    creation — only a SHA-256 hash is stored, so the plaintext cannot be
    recovered or re-displayed later.

    Only users who may use the products module get here: the token's whole
    purpose is importing products, and issuing one to an account that cannot
    import would create a credential with no use and a real leak surface.
    """
    from .models import ApiToken
    from .services import log_action

    profile = getattr(request.user, 'profile', None)
    if profile is None or not profile.can('products'):
        raise PermissionDenied('You do not have access to the products module.')

    # Set only on the request that just created a token, and never stored.
    new_token_plaintext = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create':
            name = (request.POST.get('name') or '').strip() or 'Browser extension'
            token, new_token_plaintext = ApiToken.issue(request.user, name=name)
            log_action(request, 'api_token.create', target=f'{token.name} ({token.prefix}…)')
            messages.success(
                request,
                'Token created. Copy it now — it cannot be shown again.',
            )

        elif action == 'revoke':
            token = ApiToken.objects.filter(
                id=request.POST.get('token_id'),
                user=request.user,      # scoped to the owner: no revoking someone else's
            ).first()
            if token:
                token.is_active = False
                token.save(update_fields=['is_active'])
                log_action(request, 'api_token.revoke', target=f'{token.name} ({token.prefix}…)')
                messages.success(request, f'Token “{token.name}” revoked.')
            else:
                messages.error(request, 'That token no longer exists.')
            # Redirect after a plain revoke so a refresh does not repost it.
            return redirect('api_tokens')

    return render(request, 'accounts/api_tokens.html', {
        'settings': CompanySettings.get_settings(),
        'tokens': ApiToken.objects.filter(user=request.user),
        'new_token_plaintext': new_token_plaintext,
    })
