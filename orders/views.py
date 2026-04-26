from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Order, OrderItem
from customers.models import Customer
from products.models import Product

def order_list(request):
	orders = Order.objects.select_related('customer').prefetch_related('items__product').all().order_by('-date')
	customers = Customer.objects.all()
	products = Product.objects.all()
	return render(request, 'orders/order_list.html', {
		'orders': orders,
		'customers': customers,
		'products': products,
	})

@csrf_exempt
def add_order(request):
	if request.method == 'POST':
		customer_id = request.POST.get('customer_id')
		product_ids = request.POST.getlist('product_id')
		quantities = request.POST.getlist('quantity')

		try:
			customer = Customer.objects.get(id=customer_id)
		except Customer.DoesNotExist:
			return JsonResponse({'success': False, 'message': 'Customer not found'})

		order = Order.objects.create(customer=customer, total=0)
		total = 0

		for pid, qty in zip(product_ids, quantities):
			try:
				product = Product.objects.get(id=pid)
				quantity = int(qty)
				price = product.price
				OrderItem.objects.create(order=order, product=product, quantity=quantity, price=price)
				total += price * quantity
			except (Product.DoesNotExist, ValueError):
				continue

		order.total = total
		order.save()

		return JsonResponse({'success': True, 'message': f'Order #{order.id} created! Total: AED {total}'})
	return JsonResponse({'success': False, 'message': 'Invalid request'})

def order_detail(request, order_id):
	try:
		order = Order.objects.select_related('customer').prefetch_related('items__product').get(id=order_id)
		items = []
		for item in order.items.all():
			items.append({
				'product': item.product.name,
				'quantity': item.quantity,
				'price': str(item.price),
				'subtotal': str(item.price * item.quantity),
			})
		return JsonResponse({
			'customer': order.customer.name,
			'date': order.date.strftime('%b %d, %Y %H:%M'),
			'total': str(order.total),
			'items': items,
		})
	except Order.DoesNotExist:
		return JsonResponse({'error': 'Order not found'}, status=404)

@csrf_exempt
def delete_order(request, order_id):
	if request.method == 'POST':
		try:
			order = Order.objects.get(id=order_id)
			order.delete()
			return JsonResponse({'success': True, 'message': 'Order deleted!'})
		except Order.DoesNotExist:
			return JsonResponse({'success': False, 'message': 'Order not found'})
	return JsonResponse({'success': False, 'message': 'Invalid request'})
