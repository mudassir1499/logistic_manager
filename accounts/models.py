"""
accounts/models.py

This module defines the authentication/authorization layer that unifies every
kind of person who logs into the logistics platform onto Django's built-in
``User`` model.

Historically the project had TWO disconnected login systems:

  1. Staff used Django's ``auth_user`` table (guarded only by ``@login_required``,
     which never actually checked ``is_staff`` or any per-module permission).
  2. Customers used a hand-rolled session login stored on the ``Customer`` model.

We keep Django's default ``User`` as the single source of identity and layer a
``Profile`` (one row per user) on top of it. The Profile answers two questions
that ``User`` alone cannot:

  - WHAT ROLE is this person? (admin / staff / support / customer)
  - For staff, WHICH BACK-OFFICE MODULES may they use? (orders, products, khata…)

The module flags are deliberately plain booleans rather than Django Groups so
that a single ``profile.can('orders')`` call can gate BOTH the view and the
navigation link — a staff member only sees the sections they are allowed to use.

The ``Customer`` table is intentionally left untouched (many other tables have
foreign keys to it); a customer-role Profile simply points at the matching
``Customer`` row via ``customer``.
"""

# Django's ORM base classes for defining database models.
from django.db import models

# The built-in User model. We do NOT swap AUTH_USER_MODEL (that is destructive on
# an existing project); we reference the default User via settings.AUTH_USER_MODEL
# so the code keeps working even if a custom user model is introduced later.
from django.conf import settings


class Profile(models.Model):
    """
    One-to-one companion to Django's ``User`` that stores role and permissions.

    Every ``User`` in the system has exactly one ``Profile``. It is created
    automatically by a post_save signal (see ``accounts/signals.py``) so no code
    path can end up with a User that has no Profile.
    """

    # -------------------------------------------------------------------------
    # ROLES
    # -------------------------------------------------------------------------
    # A role is the coarse identity of the account. Access checks and default
    # redirects branch on this value. Module permissions (below) further refine
    # what a STAFF member specifically may touch.
    # -------------------------------------------------------------------------
    ROLE_ADMIN = 'admin'        # Full access to everything, incl. settings + user management.
    ROLE_STAFF = 'staff'        # Back-office employee, limited to granted modules.
    ROLE_SUPPORT = 'support'    # Handles the support-ticket queue.
    ROLE_CUSTOMER = 'customer'  # External B2B client, portal only.

    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Admin'),
        (ROLE_STAFF, 'Staff / Employee'),
        (ROLE_SUPPORT, 'Support'),
        (ROLE_CUSTOMER, 'Customer'),
    ]

    # The list of back-office modules that can be individually granted to staff.
    # Keep this in sync with the ``perm_*`` fields and MODULE_FIELD_MAP below.
    MODULES = ['orders', 'quotes', 'products', 'customers', 'khata', 'noon_labels', 'support', 'settings']

    # OneToOne link to the actual login account. CASCADE so deleting a User also
    # deletes its Profile (there is no meaningful Profile without a User).
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )

    # Coarse role. Defaults to 'customer' because self-registration (the most
    # common account creation path) always produces customers.
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_CUSTOMER, db_index=True)

    # For customer-role accounts, the business record they represent. NULL for
    # staff/support/admin. OneToOne so a Customer maps to at most one login.
    customer = models.OneToOneField(
        'customers.Customer',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='user_profile',
        help_text='The Customer business record this login represents (customer role only).',
    )

    # -------------------------------------------------------------------------
    # MODULE PERMISSIONS (staff only)
    # -------------------------------------------------------------------------
    # Each flag grants access to one back-office section. Admins bypass these
    # entirely (see ``can``). For staff, an unchecked flag hides the nav link AND
    # returns 403 on the underlying views. Settings is admin-only by policy, but
    # the flag exists so it can be granted deliberately if ever needed.
    # -------------------------------------------------------------------------
    perm_orders = models.BooleanField(default=False)
    # Quotations (the quotes app). Added by migration 0007.
    perm_quotes = models.BooleanField(default=False)
    perm_products = models.BooleanField(default=False)
    perm_customers = models.BooleanField(default=False)
    perm_khata = models.BooleanField(default=False)
    perm_noon_labels = models.BooleanField(default=False)
    perm_support = models.BooleanField(default=False)
    perm_settings = models.BooleanField(default=False)

    # Two-factor authentication via emailed one-time code. Off by default; each
    # user opts in from My Account. When on, login requires a 6-digit code sent
    # to the account email after the password step.
    two_factor_enabled = models.BooleanField(default=False)

    # Whether the account's email address has been confirmed via the emailed
    # verification link. Existing accounts are marked verified by the migration;
    # new self-registrations start unverified and see a gentle banner.
    email_verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Maps a module name -> the attribute that grants it, so ``can`` can look the
    # flag up dynamically instead of a long if/elif chain.
    MODULE_FIELD_MAP = {
        'orders': 'perm_orders',
        'quotes': 'perm_quotes',
        'products': 'perm_products',
        'customers': 'perm_customers',
        'khata': 'perm_khata',
        'noon_labels': 'perm_noon_labels',
        'support': 'perm_support',
        'settings': 'perm_settings',
    }

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f'{self.user.get_username()} ({self.get_role_display()})'

    @classmethod
    def for_user(cls, user):
        """
        Return ``user``'s Profile, creating a default one if it is missing.

        ``user.profile`` raises ``RelatedObjectDoesNotExist`` when no row exists,
        which is a 500 rather than anything the caller can act on. The post_save
        signal in signals.py only fires for newly created Users, so any account
        that predates that signal — the original ``createsuperuser`` account, and
        anyone imported by an early loaddata — has no Profile at all. Those users
        are rejected by every guard in decorators.py and used to crash the user
        editor outright.

        The role default matches the signal's: superusers administer the system,
        everyone else starts as a customer.
        """
        profile, created = cls.objects.get_or_create(
            user=user,
            defaults={'role': cls.ROLE_ADMIN if user.is_superuser else cls.ROLE_CUSTOMER},
        )
        if created and profile.role == cls.ROLE_ADMIN:
            for field in cls.MODULE_FIELD_MAP.values():
                setattr(profile, field, True)
            profile.save()
        return profile

    # -------------------------------------------------------------------------
    # ROLE HELPERS
    # -------------------------------------------------------------------------
    @property
    def is_admin(self):
        """True for the owner/superadmin role — bypasses every module check."""
        return self.role == self.ROLE_ADMIN

    @property
    def is_staff_role(self):
        """True for back-office employees (the 'staff' role specifically)."""
        return self.role == self.ROLE_STAFF

    @property
    def is_support(self):
        """True for support-desk agents."""
        return self.role == self.ROLE_SUPPORT

    @property
    def is_customer(self):
        """True for external customer accounts."""
        return self.role == self.ROLE_CUSTOMER

    @property
    def is_back_office(self):
        """
        True for anyone who belongs in the internal back-office/support side
        (admin, staff, or support) as opposed to the customer portal.
        """
        return self.role in (self.ROLE_ADMIN, self.ROLE_STAFF, self.ROLE_SUPPORT)

    def can(self, module):
        """
        Return True if this account may use the given back-office ``module``.

        Rules:
          - Admins can do everything.
          - Support implicitly has the 'support' module.
          - Everyone else is governed by the matching ``perm_*`` boolean.
          - Customers never have back-office module access.

        Args:
            module (str): One of ``Profile.MODULES``.
        """
        if self.is_admin:
            return True
        if self.is_customer:
            return False
        if module == 'support' and self.is_support:
            return True
        field = self.MODULE_FIELD_MAP.get(module)
        if not field:
            return False
        return bool(getattr(self, field, False))

    def granted_modules(self):
        """Return the list of modules this account can access (for nav rendering)."""
        return [m for m in self.MODULES if self.can(m)]

    def default_landing(self):
        """
        The URL name a user should be sent to right after login, based on role.
        Kept here so both the login view and any redirect logic agree.
        """
        if self.is_customer:
            return 'portal_dashboard'
        if self.is_support:
            return 'support_queue'
        return 'dashboard'


class AuditLog(models.Model):
    """
    A permanent record of who did what, when — for accountability across the
    multi-role team (order/customer/user/settings changes, logins, payments).

    Rows are written via ``accounts.services.log_action`` and are intentionally
    never edited or deleted from the UI. Admin-only viewer at /accounts/audit/.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,                      # NULL = system action or deleted account
        on_delete=models.SET_NULL,
        related_name='audit_entries',
    )
    action = models.CharField(max_length=50, db_index=True)   # e.g. 'login', 'customer.delete'
    target = models.CharField(max_length=200, blank=True, default='')  # e.g. 'Customer #12 (Acme)'
    detail = models.TextField(blank=True, default='')
    ip_address = models.CharField(max_length=45, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Audit Log Entry'
        verbose_name_plural = 'Audit Log'

    def __str__(self):
        who = self.user.get_username() if self.user else 'system'
        return f'{who}: {self.action} {self.target}'.strip()


class ApiToken(models.Model):
    """
    A long-lived bearer token that lets a non-browser client authenticate.

    The 1688 browser extension runs on alibaba.com pages, not on this site, so
    it has no session cookie and cannot use the normal login. It authenticates
    with ``Authorization: Bearer <token>`` instead.

    ONLY THE HASH IS STORED. The plaintext token is shown once, at creation, and
    is unrecoverable afterwards — the same contract as an SSH key or a GitHub
    PAT. A leaked database therefore does not hand an attacker working tokens.

    Every request through a token acts as the token's ``user``, so the existing
    per-module permission checks (``profile.can('products')``) still apply — a
    token can never do more than the person it belongs to.
    """

    # SHA-256 of the plaintext token, hex-encoded (64 chars). Indexed and unique
    # because every authenticated request looks a token up by this column.
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)

    # First 8 characters of the plaintext, stored so the UI can show the user
    # WHICH token a row refers to without being able to reconstruct it.
    prefix = models.CharField(max_length=12, blank=True, default='')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='api_tokens',
    )

    name = models.CharField(
        max_length=100,
        default='Browser extension',
        help_text='What this token is used for, e.g. "Laptop Chrome".',
    )

    # Revocation is a flag rather than a delete so the audit trail survives.
    is_active = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    # Written on every successful authentication so an unused token is easy to
    # spot and revoke. Deliberately not indexed — it is display-only.
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'API Token'

    def __str__(self):
        return f'{self.name} ({self.prefix}…) for {self.user.get_username()}'

    @staticmethod
    def hash_token(raw):
        """
        Hash a plaintext token for storage or lookup.

        Plain SHA-256, deliberately NOT a slow password hash. Tokens are 32
        bytes of cryptographic randomness, so there is no dictionary to attack
        and no need for a work factor — and a slow hash would add that cost to
        every single API request.
        """
        import hashlib
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @classmethod
    def issue(cls, user, name='Browser extension'):
        """
        Create a token for ``user``.

        Returns:
            tuple[ApiToken, str]: the saved row and the PLAINTEXT token. The
            caller must show the plaintext to the user immediately — it cannot
            be recovered from the database afterwards.
        """
        import secrets
        raw = 'mlk_' + secrets.token_urlsafe(32)
        token = cls.objects.create(
            user=user,
            name=name or 'Browser extension',
            token_hash=cls.hash_token(raw),
            prefix=raw[:12],
        )
        return token, raw
