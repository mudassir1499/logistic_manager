"""support/admin.py — expose tickets in Django admin for oversight."""

from django.contrib import admin

from .models import Ticket, TicketMessage, TicketAttachment


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0
    fields = ('author', 'body', 'is_internal', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject', 'customer', 'status', 'priority', 'assigned_to', 'updated_at')
    list_filter = ('status', 'priority', 'category')
    search_fields = ('subject', 'customer__name', 'created_by__username')
    raw_id_fields = ('created_by', 'customer', 'assigned_to')
    inlines = (TicketMessageInline,)


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'ticket', 'author', 'is_internal', 'created_at')
    list_filter = ('is_internal',)
    raw_id_fields = ('ticket', 'author')


admin.site.register(TicketAttachment)
