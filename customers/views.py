from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Customer

def customer_list(request):
	customers = Customer.objects.all().order_by('-id')
	return render(request, 'customers/customer_list.html', {'customers': customers})

@csrf_exempt
def add_customer(request):
	if request.method == 'POST':
		name = request.POST.get('name')
		phone = request.POST.get('phone')
		address = request.POST.get('address')
		Customer.objects.create(name=name, phone=phone, address=address)
		return JsonResponse({'success': True, 'message': 'Customer added successfully!'})
	return JsonResponse({'success': False, 'message': 'Invalid request'})

@csrf_exempt
def edit_customer(request):
	if request.method == 'POST':
		customer_id = request.POST.get('customer_id')
		try:
			customer = Customer.objects.get(id=customer_id)
			customer.name = request.POST.get('name', customer.name)
			customer.phone = request.POST.get('phone', customer.phone)
			customer.address = request.POST.get('address', customer.address)
			customer.save()
			return JsonResponse({'success': True, 'message': 'Customer updated successfully!'})
		except Customer.DoesNotExist:
			return JsonResponse({'success': False, 'message': 'Customer not found'})
	return JsonResponse({'success': False, 'message': 'Invalid request'})

@csrf_exempt
def delete_customer(request, customer_id):
	if request.method == 'POST':
		try:
			customer = Customer.objects.get(id=customer_id)
			customer.delete()
			return JsonResponse({'success': True, 'message': 'Customer deleted!'})
		except Customer.DoesNotExist:
			return JsonResponse({'success': False, 'message': 'Customer not found'})
	return JsonResponse({'success': False, 'message': 'Invalid request'})
