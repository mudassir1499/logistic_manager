from django.db import models
from customers.models import Customer

class LedgerEntry(models.Model):
	CREDIT = 'credit'
	DEBIT = 'debit'
	ENTRY_TYPE_CHOICES = [
		(CREDIT, 'Credit'),
		(DEBIT, 'Debit'),
	]

	customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
	entry_type = models.CharField(max_length=6, choices=ENTRY_TYPE_CHOICES)
	amount = models.DecimalField(max_digits=10, decimal_places=2)
	date = models.DateTimeField(auto_now_add=True)
	description = models.CharField(max_length=255, blank=True)

	def __str__(self):
		return f"{self.customer.name} - {self.entry_type} - {self.amount}"
