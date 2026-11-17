from django.contrib import admin
from django.utils.html import format_html
from .models import Order, OrderItem, OrderExtraCost, OrderNote, Notification


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'price', 'subtotal', 'label_mark', 'carton_mark', 'carton_asn', 'carton_quantity')
    fields = readonly_fields + ('shipping_label', 'carton_label')
    show_change_link = True


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'status', 'payment_status', 'total', 'is_placed', 'date')
    list_filter = ('status', 'payment_status', 'date')
    search_fields = ('id', 'customer__name', 'customer__email')
    inlines = [OrderItemInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'quantity', 'price', 'label_mark', 'carton_mark', 'carton_asn')
    list_filter = ('order__status',)
    search_fields = ('order__id', 'product__name', 'label_mark', 'carton_mark', 'carton_asn')


@admin.register(OrderExtraCost)
class OrderExtraCostAdmin(admin.ModelAdmin):
    list_display = ('order', 'amount', 'reason')


admin.site.register(OrderNote)
admin.site.register(Notification)


from .models import ShipmentStatus


@admin.register(ShipmentStatus)
class ShipmentStatusAdmin(admin.ModelAdmin):
    list_display = ('order', 'shipment_no', 'status', 'updated_at')
    list_filter = ('status',)
    raw_id_fields = ('order',)
