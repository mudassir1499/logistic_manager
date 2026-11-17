"""
URL map for /api/v1/.

VERSIONED FROM THE START. The version lives in the path rather than a header
because consumers here will be a mobile app and third-party scripts, and a path
version is the one people can see in a log, curl by hand, and pin without
reading documentation. /api/v1/ can keep working unchanged the day /api/v2/
appears, which is the whole point of putting it there before there is anything
to break.
"""

from django.urls import include, path
from drf_spectacular.views import (SpectacularAPIView, SpectacularRedocView,
                                   SpectacularSwaggerView)
from rest_framework.routers import DefaultRouter

from . import admin_views, catalogue_views, auth_views, cart_views, content_views, password_views, views

router = DefaultRouter()

# --- Catalogue and commerce ------------------------------------------------
router.register('categories', views.CategoryViewSet, basename='category')
router.register('products', views.ProductViewSet, basename='product')
router.register('tags', admin_views.ProductTagViewSet, basename='tag')
# Photos and variations. Both are filtered by ?product=<id> - see
# catalogue_views for why listing them catalogue-wide is not offered.
router.register('product-images', catalogue_views.ProductImageViewSet,
                basename='product-image')
router.register('product-variants', catalogue_views.ProductVariantViewSet,
                basename='product-variant')
router.register('cart', cart_views.CartViewSet, basename='cart')
router.register('orders', views.OrderViewSet, basename='order')
router.register('order-admin', content_views.OrderAdminViewSet, basename='order-admin')
router.register('shipments', content_views.ShipmentStatusViewSet, basename='shipment')

# --- Customer relationship -------------------------------------------------
router.register('customers', views.CustomerViewSet, basename='customer')
router.register('ledger', views.LedgerEntryViewSet, basename='ledger')
router.register('tickets', views.TicketViewSet, basename='ticket')
router.register('product-requests', content_views.ProductRequestViewSet,
                basename='product-request')
router.register('notifications', content_views.NotificationViewSet,
                basename='notification')

# --- Public content --------------------------------------------------------
router.register('blog', content_views.BlogPostViewSet, basename='blog')
router.register('portfolio', content_views.PortfolioViewSet, basename='portfolio')

# --- Staff-only records ----------------------------------------------------
router.register('price-adjustments', content_views.PriceAdjustmentViewSet,
                basename='price-adjustment')
router.register('audit-log', content_views.AuditLogViewSet, basename='audit-log')
router.register('label-batches', content_views.LabelBatchViewSet, basename='label-batch')
router.register('shipping-companies', content_views.ShippingCompanyViewSet,
                basename='shipping-company')

urlpatterns = [
    # The schema is generated from the code, so it cannot describe an endpoint
    # that does not exist or miss one that does - the usual failure of
    # hand-written API documentation.
    path('schema/', SpectacularAPIView.as_view(), name='api_schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api_schema'), name='api_docs'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api_schema'), name='api_redoc'),

    # --- Auth --------------------------------------------------------------
    # These are what let a mobile app exist: without them the only way to get a
    # token is to open the website and mint one by hand.
    path('auth/register/', auth_views.RegisterView.as_view(), name='api_register'),
    path('auth/login/', auth_views.LoginView.as_view(), name='api_login'),

    # Staff sign-in for the admin app. Separate from auth/login/ above, which
    # serves customers and refuses staff - see StaffLoginView for why the two
    # are kept apart rather than merged behind a role check.
    path('auth/staff-login/', auth_views.StaffLoginView.as_view(), name='api_staff_login'),
    path('auth/logout/', auth_views.LogoutView.as_view(), name='api_logout'),
    path('auth/password-reset/', password_views.PasswordResetRequestView.as_view(),
         name='api_password_reset'),
    path('auth/password-change/', password_views.PasswordChangeView.as_view(),
         name='api_password_change'),

    path('me/', views.MeView.as_view(), name='api_me'),

    # Back-office home screen in one request.
    #
    # Not a router entry because there is no dashboard table - registering it as
    # a viewset would invite filtering and pagination onto a single computed
    # snapshot. Blocks are omitted where the caller lacks the module, so a
    # coordinator with only `orders` gets orders and nothing else.
    path('dashboard/', admin_views.DashboardView.as_view(), name='api_dashboard'),

    # --- Cart and checkout -------------------------------------------------
    path('cart/summary/', cart_views.CartSummaryView.as_view(), name='api_cart_summary'),
    path('checkout/', cart_views.CheckoutView.as_view(), name='api_checkout'),

    # --- Public ------------------------------------------------------------
    path('company/', content_views.CompanyInfoView.as_view(), name='api_company'),
    path('contact/', content_views.ContactMessageView.as_view(), name='api_contact'),

    path('', include(router.urls)),
]
