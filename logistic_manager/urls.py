"""
URL configuration for logistic_manager project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import render

from products.models import Product
from customers.models import Customer
from orders.models import Order
from khata.models import LedgerEntry


def dashboard(request):
    context = {
        'product_count': Product.objects.count(),
        'customer_count': Customer.objects.count(),
        'order_count': Order.objects.count(),
        'ledger_count': LedgerEntry.objects.count(),
        'recent_orders': Order.objects.select_related('customer').order_by('-date')[:5],
    }
    return render(request, 'dashboard.html', context)


urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('products/', include('products.urls')),
    path('customers/', include('customers.urls')),
    path('orders/', include('orders.urls')),
    path('khata/', include('khata.urls')),
    path('noon-labels/', include('noon_labels.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
