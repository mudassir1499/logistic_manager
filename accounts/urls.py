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

    # -------------------------------------------------------------------------
    # SIGN IN WITH GOOGLE
    # -------------------------------------------------------------------------
    # /accounts/google/           -> bounce the browser to Google's consent screen
    # /accounts/google/callback/  -> where Google sends them back
    #
    # The callback path is the value that must be registered as an authorised
    # redirect URI in the Google Cloud console, as an absolute URL:
    #     https://mudassirllc.com/accounts/google/callback/
    # Changing this path means changing it there too, or sign-in stops working
    # with redirect_uri_mismatch.
    # -------------------------------------------------------------------------
    path('google/', views.google_login_start, name='account_google_start'),
    path('google/callback/', views.google_login_callback, name='account_google_callback'),

    # --- Password reset (token-based, emailed) ---
    path('password-reset/', views.password_reset_request, name='account_password_reset'),
    path('password-reset/<uidb64>/<token>/', views.password_reset_confirm,
         name='account_password_reset_confirm'),

    # --- Two-factor authentication (second login step) ---
    path('otp/', views.otp_view, name='account_otp'),

    # --- Email verification ---
    path('verify-email/resend/', views.resend_verification, name='account_resend_verification'),
    path('verify-email/<str:token>/', views.verify_email, name='account_verify_email'),

    # --- Global back-office search (Ctrl+K) ---
    path('search/', views.global_search, name='global_search'),

    # --- Audit log (admin only) ---
    path('audit/', views.audit_log, name='audit_log'),

    # --- Self-service account settings (any logged-in user) ---
    path('me/', views.my_account, name='my_account'),

    # API TOKENS: issue/revoke the bearer tokens the 1688 browser extension uses.
    path('api-tokens/', views.api_tokens, name='api_tokens'),

    # --- Admin: internal user & role management (admin role only) ---
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.user_create, name='user_create'),
    path('users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:user_id>/delete/', views.user_delete, name='user_delete'),
]
