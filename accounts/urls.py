"""
accounts/urls.py

Routes for the unified authentication surface, mounted at /accounts/ by the
project urls.py. URL *names* here (``account_login`` etc.) are the canonical ones;
the project keeps the old ``admin_login`` / ``portal_login`` names as aliases that
point back to these views, so existing templates keep working.
"""

from django.urls import path

from . import views

urlpatterns = [
    # --- Authentication ---
    path('login/', views.login_view, name='account_login'),
    path('logout/', views.logout_view, name='account_logout'),
    path('register/', views.register_view, name='account_register'),

    # --- Password reset (token-based, emailed) ---
    path('password-reset/', views.password_reset_request, name='account_password_reset'),
    path('password-reset/<uidb64>/<token>/', views.password_reset_confirm,
         name='account_password_reset_confirm'),

    # --- Admin: internal user & role management (admin role only) ---
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.user_create, name='user_create'),
    path('users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:user_id>/delete/', views.user_delete, name='user_delete'),
]
