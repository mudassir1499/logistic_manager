from django.urls import path
from . import views

urlpatterns = [
    path('', views.order_list, name='order_list'),
    path('add/', views.add_order, name='add_order'),
    path('detail/<int:order_id>/', views.order_detail, name='order_detail'),
    path('delete/<int:order_id>/', views.delete_order, name='delete_order'),
]
