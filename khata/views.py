from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Sum, Q
from .models import LedgerEntry
from customers.models import Customer
from decimal import Decimal

def ledger_view(request):
	customers = Customer.objects.all()
	selected_customer = None
	entries = LedgerEntry.objects.select_related('customer').all().order_by('-date')

	customer_id = request.GET.get('customer')
	if customer_id:
		try:
			selected_customer = Customer.objects.get(id=customer_id)
			entries = entries.filter(customer=selected_customer)
		except Customer.DoesNotExist:
			pass

	# Calculate running balance
	if selected_customer:
		credit_sum = entries.filter(entry_type='credit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
		debit_sum = entries.filter(entry_type='debit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
	else:
		credit_sum = LedgerEntry.objects.filter(entry_type='credit').aggregate(s=Sum('amount'))['s'] or Decimal('0')
		debit_sum = LedgerEntry.objects.filter(entry_type='debit').aggregate(s=Sum('amount'))['s'] or Decimal('0')

	balance = credit_sum - debit_sum

	return render(request, 'khata/ledger.html', {
		'customers': customers,
		'selected_customer': selected_customer,
		'entries': entries,
		'balance': balance,
	})

@csrf_exempt
def add_entry(request):
	if request.method == 'POST':
		customer_id = request.POST.get('customer_id')
		entry_type = request.POST.get('entry_type')
		amount = request.POST.get('amount')
		description = request.POST.get('description', '')

		try:
			customer = Customer.objects.get(id=customer_id)
		except Customer.DoesNotExist:
			return JsonResponse({'success': False, 'message': 'Customer not found'})

		LedgerEntry.objects.create(
			customer=customer,
			entry_type=entry_type,
			amount=amount,
			description=description,
		)
		return JsonResponse({'success': True, 'message': f'{entry_type.capitalize()} entry added!'})
	return JsonResponse({'success': False, 'message': 'Invalid request'})

@csrf_exempt
def delete_entry(request, entry_id):
	if request.method == 'POST':
		try:
			entry = LedgerEntry.objects.get(id=entry_id)
			entry.delete()
			return JsonResponse({'success': True, 'message': 'Entry deleted!'})
		except LedgerEntry.DoesNotExist:
			return JsonResponse({'success': False, 'message': 'Entry not found'})
	return JsonResponse({'success': False, 'message': 'Invalid request'})
