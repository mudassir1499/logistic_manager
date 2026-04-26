from django.db import models

class LabelBatch(models.Model):
    label_mark = models.CharField(max_length=100)
    label_mark_2 = models.CharField(max_length=100, blank=True, null=True)
    label_mark_3 = models.CharField(max_length=100, blank=True, null=True)
    carton_mark = models.CharField(max_length=100)
    carton_asn = models.CharField(max_length=100, blank=True, null=True)
    quantity = models.PositiveIntegerField()
    carton_quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Label Batches'

    def __str__(self):
        return f"{self.label_mark} — Qty: {self.quantity}"
