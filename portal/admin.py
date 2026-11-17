from django.contrib import admin
from .models import (
    ProductRequest, ProductRequestImage, PortfolioItem, PasswordResetRequest,
    CartItem, ContactMessage, BlogCategory, BlogPost,
)


@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    """Admin for blog topic groupings."""
    list_display = ('name', 'slug', 'display_order', 'post_count')
    list_editable = ('display_order',)
    search_fields = ('name', 'description')
    # Typing a category name fills the slug automatically, which stops
    # inconsistent hand-typed URLs creeping in.
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='Published posts')
    def post_count(self, obj):
        return obj.posts.filter(is_published=True).count()


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    """
    Admin for writing and editing blog articles.

    The fieldsets separate what the author writes from the SEO overrides, which are
    collapsed because they are optional — a blank meta title/description falls back
    to the article title and excerpt.
    """
    list_display = ('title', 'category', 'is_published', 'is_featured', 'published_at', 'reading_minutes')
    list_filter = ('is_published', 'is_featured', 'category', 'published_at')
    search_fields = ('title', 'excerpt', 'body', 'keywords')
    list_editable = ('is_published', 'is_featured')
    date_hierarchy = 'published_at'
    ordering = ('-published_at',)

    # NOTE: the slug is prepopulated for NEW posts only. Django's admin disables
    # prepopulation once an object exists, which is exactly what we want — editing
    # a published post's slug breaks every inbound link to it.
    prepopulated_fields = {'slug': ('title',)}

    readonly_fields = ('created_at', 'updated_at', 'reading_minutes')

    fieldsets = (
        ('Article', {
            'fields': ('title', 'slug', 'category', 'excerpt', 'body', 'author_name'),
        }),
        ('Header image', {
            'fields': ('hero_image', 'hero_image_alt'),
            'description': 'Optional. Also used as the preview image when the article is shared on WhatsApp or LinkedIn.',
        }),
        ('Publishing', {
            'fields': ('is_published', 'is_featured', 'published_at'),
        }),
        ('Search engine settings (optional)', {
            'classes': ('collapse',),
            'fields': ('meta_title', 'meta_description', 'keywords'),
            'description': 'Leave blank to use the article title and excerpt automatically.',
        }),
        ('System', {
            'classes': ('collapse',),
            'fields': ('reading_minutes', 'created_at', 'updated_at'),
        }),
    )


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
