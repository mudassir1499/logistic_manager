"""
support/urls.py

Internal support-desk routes, mounted at /support/. ``support_queue`` is the name
used as the default landing page for support-role users after login.
"""

from django.urls import path

from . import views

urlpatterns = [
    path('', views.queue, name='support_queue'),
    path('tickets/<int:ticket_id>/', views.ticket_detail, name='support_ticket_detail'),
]
