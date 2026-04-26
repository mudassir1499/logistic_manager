from django.urls import path
from . import views

urlpatterns = [
    path('', views.label_form, name='label_form'),
    path('generate/', views.generate_labels_pdf, name='generate_labels_pdf'),
    path('generate-carton/', views.generate_carton_pdf, name='generate_carton_pdf'),
]
