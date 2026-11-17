"""URL routes for quotations."""

from django.urls import path

from . import views

urlpatterns = [
    path('', views.quotation_list, name='quotation_list'),
    path('new/', views.quotation_create, name='quotation_create'),
    path('<int:quotation_id>/', views.quotation_detail, name='quotation_detail'),
    path('<int:quotation_id>/items/add/', views.quotation_add_item, name='quotation_add_item'),
    path('<int:quotation_id>/items/<int:item_id>/delete/', views.quotation_delete_item,
         name='quotation_delete_item'),
    path('<int:quotation_id>/action/', views.quotation_action, name='quotation_action'),
    path('<int:quotation_id>/convert/', views.quotation_convert, name='quotation_convert'),
]
