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
    MODULES = ['orders', 'products', 'customers', 'khata', 'noon_labels', 'support', 'settings']

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
    perm_products = models.BooleanField(default=False)
    perm_customers = models.BooleanField(default=False)
    perm_khata = models.BooleanField(default=False)
    perm_noon_labels = models.BooleanField(default=False)
    perm_support = models.BooleanField(default=False)
    perm_settings = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Maps a module name -> the attribute that grants it, so ``can`` can look the
    # flag up dynamically instead of a long if/elif chain.
    MODULE_FIELD_MAP = {
        'orders': 'perm_orders',
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
