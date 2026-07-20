from django.contrib import admin
from .models import ProductRequest, ProductRequestImage, PortfolioItem, PasswordResetRequest, CartItem, ContactMessage


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    """
    Admin interface for contact form submissions.

    Allows staff to browse, search, and mark messages as read. Unread messages
    appear first by default so admins can quickly see new inbound leads.
    """
    list_display = ('name', 'email', 'phone', 'subject', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('name', 'email', 'phone', 'subject', 'message')
    readonly_fields = ('name', 'email', 'phone', 'subject', 'message', 'created_at')
    list_editable = ('is_read',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    actions = ['mark_as_read']

    @admin.action(description='Mark selected messages as read')
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True)


@admin.register(ProductRequest)
class ProductRequestAdmin(admin.ModelAdmin):
    list_display = ('name', 'customer', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'description', 'customer__name', 'customer__email')
    list_editable = ('status',)


@admin.register(PortfolioItem)
class PortfolioItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_active', 'display_order', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('title', 'description')


@admin.register(PasswordResetRequest)
class PasswordResetRequestAdmin(admin.ModelAdmin):
    list_display = ('email', 'is_used', 'created_at', 'is_expired')
    list_filter = ('is_used', 'created_at')
    search_fields = ('email', 'token')


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('product', 'customer', 'quantity', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('product__name', 'customer__name', 'customer__email')
    readonly_fields = ('created_at', 'updated_at')


admin.site.register(ProductRequestImage)
