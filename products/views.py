from django.shortcuts import render, redirect
from .models import Product, ProductImage
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

def product_list(request):
	products = Product.objects.all()
	return render(request, 'products/product_list.html', {'products': products})

@csrf_exempt
def add_product(request):
	if request.method == 'POST':
		name = request.POST.get('name')
		price = request.POST.get('price')
		moq = request.POST.get('moq')
		images = request.FILES.getlist('images')
		product = Product.objects.create(name=name, price=price, moq=moq)
		for img in images[:3]:
			ProductImage.objects.create(product=product, image=img)
		return JsonResponse({'success': True, 'message': 'Product added successfully!'})
	return render(request, 'products/add_product.html')
