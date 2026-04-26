from django.contrib import admin
from .models import LabelBatch

@admin.register(LabelBatch)
class LabelBatchAdmin(admin.ModelAdmin):
    list_display = ('label_mark', 'carton_mark', 'quantity', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('label_mark', 'carton_mark')
