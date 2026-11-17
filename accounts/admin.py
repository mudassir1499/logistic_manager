"""
accounts/admin.py

Surfaces the Profile in Django's admin as an inline on the User change page, so
an admin can set a user's role and module permissions in the same place they
manage the login account itself.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import Profile, AuditLog


class ProfileInline(admin.StackedInline):
    """Edit a user's role + module permissions directly on the User page."""
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profile (role & permissions)'
    fk_name = 'user'
    fields = (
        'role', 'customer',
        'perm_orders', 'perm_products', 'perm_customers',
        'perm_khata', 'perm_noon_labels', 'perm_support', 'perm_settings',
        'two_factor_enabled', 'email_verified',
    )
    raw_id_fields = ('customer',)


class UserAdmin(BaseUserAdmin):
    """Extends the stock UserAdmin to show the role inline and in the list."""
    inlines = (ProfileInline,)
    list_display = BaseUserAdmin.list_display + ('get_role',)

    @admin.display(description='Role')
    def get_role(self, obj):
        # Guard against a User that somehow has no Profile yet.
        return getattr(getattr(obj, 'profile', None), 'role', '—')


# Re-register User with our extended admin.
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """A standalone Profile list, handy for filtering people by role."""
    list_display = ('user', 'role', 'customer', 'updated_at')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__email', 'customer__name')
    raw_id_fields = ('user', 'customer')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only audit trail in Django admin."""
    list_display = ('created_at', 'user', 'action', 'target', 'ip_address')
    list_filter = ('action',)
    search_fields = ('target', 'detail', 'user__username')
    readonly_fields = ('user', 'action', 'target', 'detail', 'ip_address', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
