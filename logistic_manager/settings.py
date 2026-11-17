"""
Django production settings for the logistic_manager project.

This file contains ALL configuration that controls how the Django project
behaves: database connections, installed apps, security settings, static
files, and more. For cPanel deployment on mudassirllc.com.

IMPORTANT CONCEPT:
    Django settings are just a Python module. Every setting is a variable
    with a specific name that Django expects. You can import Python code,
    use environment variables, and compute values dynamically.

For a full reference of all settings:
    https://docs.djangoproject.com/en/4.2/ref/settings/
"""

import os                # Python standard library for interacting with the OS
from pathlib import Path  # Modern Python way to handle filesystem paths (cross-platform)

from django.core.exceptions import ImproperlyConfigured

import pymysql

# -------------------------------------------------------------------------
# MySQLdb Compatibility Layer
# -------------------------------------------------------------------------
# pymysql.install_as_MySQLdb() tells Python to use PyMySQL as a drop-in
# replacement for MySQLdb. MySQLdb is the traditional Python MySQL driver
# but it requires C extensions and is harder to install. PyMySQL is a pure
# Python implementation that works everywhere. Django's MySQL backend looks
# for "MySQLdb", so this shim makes it use PyMySQL instead.
# -------------------------------------------------------------------------
pymysql.install_as_MySQLdb()


# -------------------------------------------------------------------------
# BASE DIRECTORY
# -------------------------------------------------------------------------
# Path(__file__) gets the path to this settings.py file.
# .resolve() turns it into an absolute path and resolves any symlinks.
# .parent.parent goes up two levels: settings.py -> logistic_manager/ -> project root/
# This gives us the root folder of the entire Django project, so we can
# build paths to templates, static files, and other resources consistently.
# -------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent


# -------------------------------------------------------------------------
# ENVIRONMENT VARIABLES (.env)
# -------------------------------------------------------------------------
# All deployment-specific values (secret key, database credentials, allowed
# hosts) are read from environment variables so that nothing sensitive lives
# in this file or in version control.
#
# Locally and on cPanel we load them from a .env file sitting next to
# manage.py. Copy .env.example to .env and fill in the real values; .env is
# listed in .gitignore and must never be committed.
#
# Real environment variables always win over the .env file, so cPanel's
# "Setup Python App" environment variable panel can override anything here.
# -------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env', override=False)
except ImportError:
    # python-dotenv is optional; real environment variables still work without it.
    pass


def env_bool(name, default=False):
    """Read a boolean from the environment ('1', 'true', 'yes' are all True)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=None):
    """Read a comma-separated list from the environment."""
    raw = os.environ.get(name, '')
    if not raw.strip():
        return list(default or [])
    return [item.strip() for item in raw.split(',') if item.strip()]


# -------------------------------------------------------------------------
# SECURITY SETTINGS
# -------------------------------------------------------------------------
# SECRET_KEY is used by Django for cryptographic signing: session cookies,
# CSRF tokens, password reset links, and more. If an attacker gets this key,
# they can forge authentication tokens and take over user sessions.
#
# In production, this should come from an environment variable (os.environ)
# so it is never committed to version control. The fallback value is only
# safe for local development. Generate a new secure key with:
#   python -c "import secrets; print(secrets.token_urlsafe(50))"
# -------------------------------------------------------------------------
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '').strip()

# -------------------------------------------------------------------------
# DEBUG MODE
# -------------------------------------------------------------------------
# DEBUG=True shows detailed error pages with stack traces and SQL queries.
# This is invaluable for development but DANGEROUS in production because
# it exposes internal code paths and database queries to attackers.
# Always set DEBUG=False before deploying to a live server.
# -------------------------------------------------------------------------
# Read from the DJANGO_DEBUG environment variable so production can disable it
# without a code change. Set DJANGO_DEBUG=1 in your local .env for development.
#
# This used to read `DEBUG = True`, hard-coded, directly under a comment claiming
# it came from the environment. The server's .env has said DJANGO_DEBUG=0 the
# whole time and was being ignored, so production ran in debug mode: full stack
# traces and SQL on any error page, ALLOWED_HOSTS unenforced, and — because the
# three flags further down derive from `not DEBUG` — the secure-cookie and
# SSL-redirect settings all silently off.
#
# The default is False, not True. A missing or misspelled environment variable
# should fail safe (a developer notices a missing debug page immediately; nobody
# notices a production site quietly running in debug).
DEBUG = env_bool('DJANGO_DEBUG', False)

# -------------------------------------------------------------------------
# SECRET_KEY enforcement
# -------------------------------------------------------------------------
# In production the key MUST come from the environment. Failing loudly here is
# deliberate: a missing key used to silently fall back to a value committed in
# this file, which anyone reading the repository could use to forge session
# cookies and password-reset links.
#
# Generate one with:
#   python -c "import secrets; print(secrets.token_urlsafe(50))"
# -------------------------------------------------------------------------
if not SECRET_KEY:
    if DEBUG:
        # Local development only. This key is not used when DEBUG=False.
        SECRET_KEY = 'django-insecure-local-development-key-do-not-use-in-production'
    else:
        raise ImproperlyConfigured(
            'DJANGO_SECRET_KEY environment variable is required when DEBUG is False. '
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(50))"'
        )

# -------------------------------------------------------------------------
# ALLOWED HOSTS
# -------------------------------------------------------------------------
# When DEBUG=False, Django refuses to serve requests unless the Host header
# matches one of these domains. This prevents HTTP Host header attacks where
# a malicious request tricks your server into serving content for a fake domain.
# List all domains that point to this server: the production domain, www variant,
# and localhost/127.0.0.1 for local testing with DEBUG=False.
# -------------------------------------------------------------------------
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', [
    'mudassirllc.com',      # Primary production domain
    'www.mudassirllc.com',  # www subdomain (some users type this)
    'localhost',            # For local development testing
    '127.0.0.1',            # Local loopback IP address
])

# -------------------------------------------------------------------------
# CSRF TRUSTED ORIGINS
# -------------------------------------------------------------------------
# CSRF (Cross-Site Request Forgery) protection checks that POST requests
# come from trusted domains. Django 4.0+ requires explicit listing of
# trusted origins when running behind HTTPS or when the Referer header
# needs validation. We include both http and https variants because the
# site may be accessed over either protocol during setup.
# -------------------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', [
    'https://mudassirllc.com',
    'https://www.mudassirllc.com',
    'http://mudassirllc.com',
    'http://www.mudassirllc.com',
])


# =============================================================================
# APPLICATION DEFINITION
# =============================================================================
# Django is built on a "app" architecture. Each app is a self-contained module
# that handles one business area. INSTALLED_APPS tells Django which apps
# to load and make available. The order matters: some apps depend on others
# being loaded first (e.g., auth before custom apps that use auth models).
# =============================================================================

INSTALLED_APPS = [
    # -------------------------------------------------------------------------
    # DJANGO BUILT-IN APPS (required for core functionality)
    # -------------------------------------------------------------------------
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',      # Django sites framework (required for sitemaps)
    'django.contrib.sitemaps',   # Django sitemap framework for SEO
    'django.contrib.humanize',   # Template filters like intcomma for money formatting

    # -------------------------------------------------------------------------
    # THIRD-PARTY
    # -------------------------------------------------------------------------
    # Django REST Framework powers /api/v1/. It is listed before the project
    # apps because its app registry supplies the templates for the browsable
    # API, and a project template of the same name should win over it.
    'rest_framework',
    'django_filters',
    'drf_spectacular',

    # -------------------------------------------------------------------------
    # PROJECT CUSTOM APPS (our business logic)
    # -------------------------------------------------------------------------
    'api',
    'accounts',
    'products',
    'customers',
    'orders',
    'khata',
    'noon_labels',
    'settings_manager',
    'portal',
    'support',
    'quotes',
]

# =============================================================================
# SITES FRAMEWORK
# =============================================================================
# django.contrib.sites is installed above, but SITE_ID was never set. Without it
# Django resolves the current Site from the request's Host header — so a request
# arriving with a hostname that has no matching Site row (e.g. www.mudassirllc.com
# when only mudassirllc.com is registered, or a health check hitting the server IP)
# raises Site.DoesNotExist and returns a 500 from /sitemap.xml. Google retries a
# failing sitemap only a limited number of times before it stops trusting it.
#
# Pinning SITE_ID to the single configured row (mudassirllc.com) makes sitemap
# generation deterministic and host-independent.
# =============================================================================
SITE_ID = 1

# =============================================================================
# MIDDLEWARE
# =============================================================================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise serves collected static files directly from the Python app with
    # correct caching headers. It must sit immediately after SecurityMiddleware.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # Sits high so a CORS preflight is answered before CommonMiddleware can
    # redirect it (APPEND_SLASH turns a preflight into a 301, which a browser
    # reports as a CORS failure) and before any view can 405 it.
    'api.middleware.ApiCorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# =============================================================================
# URL CONFIGURATION
# =============================================================================
ROOT_URLCONF = 'logistic_manager.urls'

# =============================================================================
# TEMPLATE CONFIGURATION
# =============================================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.role_permissions',
                # Makes the singleton CompanySettings row available as `settings`
                # in every template. base.html builds the whole SEO head (meta
                # tags, JSON-LD, GA4 tag, Search Console verification) from it,
                # so it must never be missing. Lazily evaluated — no query unless
                # a template actually uses it.
                'portal.context_processors.site_settings',
                # Owner-uploaded photographs, keyed by page slot. Templates fall
                # back to bundled stock imagery for any slot not yet filled.
                'portal.context_processors.site_images',
            ],
        },
    },
]

# =============================================================================
# WSGI APPLICATION ENTRY POINT
# =============================================================================
WSGI_APPLICATION = 'logistic_manager.wsgi.application'


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
DB_NAME = os.environ.get('DB_NAME', '').strip()

if DB_NAME:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': DB_NAME,
            'USER': os.environ.get('DB_USER', '').strip(),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost').strip(),
            'PORT': os.environ.get('DB_PORT', '3306').strip(),
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
            'TEST': {
                'CHARSET': 'utf8mb4',
                'COLLATION': 'utf8mb4_unicode_ci',
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# =============================================================================
# PASSWORD VALIDATION
# =============================================================================
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# =============================================================================
# INTERNATIONALIZATION (i18n) SETTINGS
# =============================================================================
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# =============================================================================
# STATIC FILES (CSS, JavaScript, Images)
# =============================================================================
STATIC_URL = '/static/'

STATICFILES_DIRS = [BASE_DIR / 'static']

# -------------------------------------------------------------------------
# STATIC_ROOT — where `collectstatic` writes the built files.
# -------------------------------------------------------------------------
# This MUST point at the directory Apache actually serves /static/ from, which
# on this cPanel account is the document root:
#
#     DJANGO_STATIC_ROOT=/home/mudassirllc/public_html/static
#
# That matters because public_html/.htaccess serves any file that exists on disk
# directly, before the request ever reaches Django:
#
#     RewriteCond %{REQUEST_FILENAME} !-f
#     RewriteRule ^(.*)$ /passenger_wsgi.py/$1 [L]
#
# So /static/style.css is answered by public_html/static/style.css and never
# touches Django or WhiteNoise. This line previously read:
#
#     STATIC_ROOT = BASE_DIR / 'staticfiles'   # "bypass the cPanel env variable"
#
# which sent collectstatic to ~/logistic_manager/staticfiles — a directory Apache
# never reads. The result was that public_html/static kept whatever build was
# copied there by hand, and no amount of collectstatic could update the live CSS.
# Three stale generations had accumulated there.
#
# The default below is only for local development, where nothing serves the
# directory and the value is unimportant.
STATIC_ROOT = Path(os.environ.get('DJANGO_STATIC_ROOT', BASE_DIR / 'staticfiles'))

_resolved_static_dirs = [Path(p).resolve() for p in STATICFILES_DIRS]
for _dir in _resolved_static_dirs:
    if STATIC_ROOT == _dir or STATIC_ROOT in _dir.parents or _dir in STATIC_ROOT.parents:
        raise ImproperlyConfigured(
            f"STATIC_ROOT ({STATIC_ROOT}) overlaps with a STATICFILES_DIRS "
            f"entry ({_dir}). They must point to completely separate "
            f"directories."
        )

if not DEBUG:
    STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
    }

# =============================================================================
# MEDIA FILES (User Uploads)
# =============================================================================
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.environ.get('DJANGO_MEDIA_ROOT', BASE_DIR / 'media'))


# =============================================================================
# SECURITY SETTINGS FOR PRODUCTION
# =============================================================================
USE_HTTPS = env_bool('DJANGO_SECURE_SSL', not DEBUG)

SESSION_COOKIE_SECURE = USE_HTTPS
CSRF_COOKIE_SECURE = USE_HTTPS
SECURE_SSL_REDIRECT = USE_HTTPS

if USE_HTTPS:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '3600'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_HSTS_SUBDOMAINS', False)
    SECURE_HSTS_PRELOAD = False

SESSION_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# =============================================================================
# CACHING CONFIGURATION
# =============================================================================
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache_table',
        'TIMEOUT': 300,  
        'OPTIONS': {
            'MAX_ENTRIES': 1000, 
            'CULL_FREQUENCY': 3, 
        },
    }
}

# =============================================================================
# DEFAULT PRIMARY KEY FIELD TYPE
# =============================================================================
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# =============================================================================
# LOGIN REDIRECT URL
# =============================================================================
# LOGIN_URL is the URL that the auth guards redirect to when a user tries to
# access a protected page without being logged in. It points at the single
# unified login (accounts app), which then redirects each user to the right home
# based on their role (admin/staff → dashboard, support → queue, customer → portal).
# =============================================================================
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'


# =============================================================================
# REQUEST BODY SIZE
# =============================================================================
# Django's default is 2.5 MB, and it applies to the whole JSON body — this is
# not the file-upload limit, which is separate.
#
# The extension's import endpoint posts product photos as base64 INSIDE the JSON
# body, so 2.5 MB is exceeded by a handful of listings and the batch is rejected
# with RequestDataTooBig before any of the import code runs.
#
# The extension downscales every photo to at most 1400px before sending, which
# keeps a typical batch comfortably inside this. The ceiling is raised, not
# removed: an unbounded body on shared hosting is a memory-exhaustion button,
# and every endpoint that accepts one here is behind a bearer token.
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024      # 20 MB

# Unrelated to the above but easy to confuse with it: this is the point at which
# an uploaded FILE stops being held in memory and is streamed to a temp file.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024       # 5 MB


# =============================================================================
# REST API (/api/v1/)
# =============================================================================
REST_FRAMEWORK = {
    # Bearer tokens first, because that is what a script or mobile app sends.
    # SessionAuthentication is kept second so a staff user who is already logged
    # into the site gets the browsable API without minting a token - it is a
    # genuinely useful way to explore the endpoints. It is second, not first, so
    # a request carrying BOTH a session cookie and a bearer token is judged by
    # the token, which is the narrower credential.
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'api.authentication.ApiTokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    # Deny by default. Every endpoint then opts into being more open, so a view
    # added later without a permission_classes line is locked rather than public
    # - the failure mode is a support request, not a data leak.
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'api.pagination.StandardPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # Rate limiting. The API is reachable from anywhere with a token, and the
    # import endpoints do real work per call (image downloads, price rewrites).
    # These are deliberately generous - they exist to stop a runaway script, not
    # to ration normal use.
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'read': '600/min',
        'write': '120/min',
        'auth': '20/min',
    },
    # ISO-8601 in, ISO-8601 out. Locale-dependent formats in an API are a
    # standing bug: 03/04/2026 means two different days depending on the reader.
    'DATETIME_FORMAT': 'iso-8601',
    'DATE_FORMAT': 'iso-8601',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Mudassir LLC API',
    'DESCRIPTION': (
        'JSON API for the sourcing and logistics platform: catalogue, orders, '
        'customers, ledger and support. Authenticate with '
        '`Authorization: Bearer <token>`; tokens are issued at /accounts/api-tokens/ '
        'and carry exactly the permissions of the account that owns them.'
    ),
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SORT_OPERATIONS': False,
    # Four different models have a "status" field with four different choice
    # sets. Left to resolve the collision itself, the generator invents names
    # like "StatusAceEnum" - and client code generated from this schema inherits
    # them as type names, which nobody can read. Naming them explicitly here is
    # what makes the generated SDK legible.
    'ENUM_NAME_OVERRIDES': {
        'OrderStatusEnum': 'orders.models.Order.STATUS_CHOICES',
        'ShipmentStatusEnum': 'orders.models.ShipmentStatus.STATUS_CHOICES',
        'TicketStatusEnum': 'support.models.Ticket.STATUS_CHOICES',
        'ProductRequestStatusEnum': 'portal.models.ProductRequest.STATUS_CHOICES',
    },
}


# =============================================================================
# GOOGLE SIGN-IN
# =============================================================================
# Credentials for the OAuth 2.0 client created in the Google Cloud console.
#
# These live in the environment, never in this file. The client secret is a
# password: anything holding it can mint sign-ins as this application, and a
# secret committed to git has to be treated as burned even after it is removed,
# because the history keeps it.
#
# Leave them unset and Google sign-in simply does not appear - the button is
# hidden and password login is unaffected. That is what makes it safe to deploy
# this code before the console side is configured.
#
# The authorised redirect URI to register in the console is:
#     https://<your domain>/accounts/google/callback/
# It must match exactly, including the trailing slash.
# =============================================================================
# Browser origins allowed to call /api/v1/ cross-origin. Empty by default:
# a native mobile app does not need this, and turning it on should be a
# deliberate act naming a specific site. See api/middleware.py.
API_CORS_ORIGINS = env_list('DJANGO_API_CORS_ORIGINS', [])

GOOGLE_OAUTH_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '').strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '').strip()


# Django tags an error message 'error', and every template here renders alerts
# as `alert-{{ m.tags }}` - but Bootstrap's class is .alert-danger, so
# `alert-error` matched no rule and errors rendered as unstyled text while
# success and warning looked correct. Mapping the tag fixes every one of those
# templates at once rather than editing the class in each.
from django.contrib.messages import constants as _message_constants

MESSAGE_TAGS = {
    _message_constants.ERROR: 'danger',
}
