"""Django-admin registration. The day-to-day screens are in views.py."""

from django.contrib import admin

from .models import Quotation, QuotationItem, QuotationSequence


class QuotationItemInline(admin.TabularInline):
    model = QuotationItem
    extra = 0
    # raw_id_fields, not autocomplete_fields: autocomplete requires the target
    # ModelAdmin to declare search_fields, which the Product admin does not.
    raw_id_fields = ['product']


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ['number', 'customer', 'status', 'item_count', 'subtotal',
                    'valid_until', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['number', 'customer__name', 'items__description']
    # `number` is assigned on save and is what the customer quotes back; it is
    # not editable here for the same reason the model marks it editable=False.
    readonly_fields = ['number', 'sent_at', 'decided_at', 'created_at', 'updated_at']
    inlines = [QuotationItemInline]
    date_hierarchy = 'created_at'


@admin.register(QuotationSequence)
class QuotationSequenceAdmin(admin.ModelAdmin):
    """Visible but not editable: the counter must only ever be advanced by
    issuing a quotation, never typed down to a number already used."""
    list_display = ['year', 'last_number']
    readonly_fields = ['year', 'last_number']

    def has_add_permission(self, request):
        return False
