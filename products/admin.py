"""
products/admin.py

Django admin registration for the product taxonomy.

Products themselves are managed through the custom screens under /products/,
not the Django admin, so Product is deliberately not registered here. The
taxonomy is different: categories change rarely and have no bespoke UI, so the
stock admin is the right place to rename a category, reorder the filter bar, or
retire one without a deploy.
"""

from django.contrib import admin
from django.db.models import Count

from .models import Category, ProductTag, SubCategory


class SubCategoryInline(admin.TabularInline):
    """
    Edit subcategories directly on their parent category's page.

    Managing them inline rather than as a separate top-level screen keeps the
    parent relationship obvious — a subcategory has no meaning on its own.
    """

    model = SubCategory
    extra = 1
    prepopulated_fields = {'slug': ('name',)}
    fields = ('name', 'slug', 'ordering', 'is_active')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'ordering', 'is_active', 'product_count')
    list_editable = ('ordering', 'is_active')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [SubCategoryInline]

    def get_queryset(self, request):
        # Without this the product_count column would fire one COUNT query per
        # row rendered on the changelist.
        return super().get_queryset(request).prefetch_related('products')

    @admin.display(description='Products')
    def product_count(self, obj):
        return obj.products.count()


@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    """
    A top-level screen for subcategories as well as the inline above.

    The inline is the natural way in, but this list makes it possible to search
    every subcategory at once and to filter by parent — useful once the
    taxonomy grows past a couple of screens.
    """

    list_display = ('name', 'category', 'slug', 'ordering', 'is_active', 'product_count')
    list_editable = ('ordering', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'slug', 'category__name')
    prepopulated_fields = {'slug': ('name',)}

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category').prefetch_related('products')

    @admin.display(description='Products')
    def product_count(self, obj):
        return obj.products.count()


@admin.register(ProductTag)
class ProductTagAdmin(admin.ModelAdmin):
    """
    Tags are normally created and edited from the product list itself, where
    they are actually used. This is here for the same reason CategoryAdmin is:
    somewhere to see the whole set at once, and to fix one without hunting for
    a product that carries it.
    """

    list_display = ('name', 'slug', 'colour', 'product_count', 'created_at')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}

    def get_queryset(self, request):
        # Without this the product_count column fires one COUNT per row.
        return super().get_queryset(request).annotate(_n=Count('products'))

    @admin.display(description='Products', ordering='_n')
    def product_count(self, obj):
        return obj._n
