"""
Permission classes mapping the API onto the roles this project already has.

THE RULE THAT SHAPES ALL OF THESE

A token never grants more than the person it belongs to already has. Permission
is decided by the owner's Profile - the same ``Profile.can(module)`` that gates
the back-office screens - so there is exactly one answer to "may this account
touch products", and the API and the web UI cannot drift apart.

The practical consequence: issuing a token to a customer account produces a
customer-scoped token. There is no separate "API permission" to forget to
tighten.
"""

from rest_framework import permissions

from accounts.models import Profile


def profile_of(request):
    """The Profile behind a request, or None for anonymous/profile-less users."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return None
    return getattr(user, 'profile', None)


class HasModule(permissions.BasePermission):
    """
    Require a back-office module permission, e.g. HasModule('products').

    Use as ``permission_classes = [HasModule.for_module('products')]``.

    Read/write asymmetry is deliberate and lives in ``ReadOnlyOrModule`` below
    rather than here: this class is the strict one, used where even reading is
    privileged (the ledger, the audit log, other customers' orders).
    """

    module = None
    message = 'Your account does not have access to this section.'

    @classmethod
    def for_module(cls, module):
        """Build a subclass bound to one module, for use in permission_classes."""
        return type(
            f'HasModule_{module}',
            (cls,),
            {'module': module, 'message': f'Your account does not have access to {module}.'},
        )

    def has_permission(self, request, view):
        profile = profile_of(request)
        if profile is None:
            return False
        return profile.can(self.module or getattr(view, 'required_module', ''))


class IsBackOffice(permissions.BasePermission):
    """Any internal account: admin, staff or support. Customers are refused."""

    message = 'This endpoint is for staff accounts.'

    def has_permission(self, request, view):
        profile = profile_of(request)
        return profile is not None and profile.is_back_office


class IsCustomer(permissions.BasePermission):
    """
    A customer account with a linked Customer record.

    The ``customer_id`` requirement is not pedantry: every customer endpoint
    scopes its queryset by it, and a customer-role Profile with no Customer
    attached would otherwise scope to None and quietly return everyone's rows.
    """

    message = 'This endpoint is for customer accounts.'

    def has_permission(self, request, view):
        profile = profile_of(request)
        return (
            profile is not None
            and profile.role == Profile.ROLE_CUSTOMER
            and profile.customer_id is not None
        )


class ReadOnlyOrModule(HasModule):
    """
    Anyone authenticated may read; writing needs the module permission.

    This is the right shape for the catalogue: a customer's app has to list
    products, but only someone who can already edit products in the back office
    may change one through the API.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return profile_of(request) is not None
        return super().has_permission(request, view)


class PublicRead(permissions.BasePermission):
    """
    Unauthenticated reads allowed; writes need the module permission.

    For the public catalogue only. The site already publishes those products to
    anonymous visitors for search indexing, so requiring a token to read them
    through the API would protect nothing that is not already public - while
    still keeping every write behind a real permission.
    """

    module = None
    message = 'Changing the catalogue requires a staff token.'

    @classmethod
    def for_module(cls, module):
        return type(f'PublicRead_{module}', (cls,), {'module': module})

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        profile = profile_of(request)
        return profile is not None and profile.can(self.module or '')
