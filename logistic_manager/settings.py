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
# without a code change. Defaults to True for local development.
# Set DJANGO_DEBUG=0 on the production server (see .env.example).
DEBUG = env_bool('DJANGO_DEBUG', True)

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
    # admin      - The Django admin panel at /admin/ for managing database records
    # auth       - User authentication: login, logout, password management, groups
    # contenttypes - Content type framework that allows generic relationships
    # sessions   - Session management (stores user session data server-side)
    # messages   - One-time flash messages ("Order saved successfully!")
    # staticfiles - Collects static files (CSS, JS, images) into one folder
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
    # PROJECT CUSTOM APPS (our business logic)
    # -------------------------------------------------------------------------
    # Each app handles one domain of the logistics business:
    # products        - Product catalog, supplier quotes, bulk uploads
    # customers       - Customer directory, assignments, quotations
    # orders          - Order creation, invoices, packing lists, payments
    # khata           - Ledger/accounting system ("Khata" = account book in Urdu/Hindi)
    # noon_labels     - Shipping label generation for Noon marketplace
    # settings_manager - Company settings, shipping calculators, shipping companies
    # portal          - Public website pages + customer login portal
    # accounts        - Unified auth: roles (admin/staff/support/customer) + module permissions
    # support         - Support-ticket system (customer requests + support-desk queue)
    # -------------------------------------------------------------------------
    'accounts',
    'products',
    'customers',
    'orders',
    'khata',
    'noon_labels',
    'settings_manager',
    'portal',
    'support',
]

# =============================================================================
# MIDDLEWARE
# =============================================================================
# Middleware is a pipeline of processing hooks that Django runs for EVERY
# request and response. Each middleware class can modify the request on the way
# IN to the view, and modify the response on the way OUT. They run in order
# for requests, and in REVERSE order for responses.
#
# SecurityMiddleware      - Adds HTTPS redirects, HSTS headers, XSS filters
# SessionMiddleware       - Attaches session data to every request (via cookie)
# CommonMiddleware        - URL rewriting, appending slashes, handling ETags
# CsrfViewMiddleware      - Validates CSRF tokens on POST/PUT/DELETE requests
# AuthenticationMiddleware - Attaches the user object to the request
# MessageMiddleware       - Adds flash messages to the response context
# XFrameOptionsMiddleware - Prevents clickjacking by setting X-Frame-Options
# =============================================================================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise serves collected static files directly from the Python app with
    # correct caching headers. It must sit immediately after SecurityMiddleware.
    # This is a safety net: Apache normally serves /static/ from public_html via
    # .htaccess, but if that rewrite is wrong the CSS still loads instead of 404ing.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# =============================================================================
# URL CONFIGURATION
# =============================================================================
# ROOT_URLCONF tells Django where to find the root URL routing table.
# When a request comes in, Django loads this module and looks for the
# `urlpatterns` list inside it. The value is a Python module path string.
# =============================================================================
ROOT_URLCONF = 'logistic_manager.urls'

# =============================================================================
# TEMPLATE CONFIGURATION
# =============================================================================
# Django uses a template engine to render HTML files with dynamic data.
# The context dictionary from views is injected into the template, and
# template tags (like {{ variable }} or {% for item in list %}) produce
# the final HTML. DjangoTemplates is the built-in engine (Jinja2-like syntax).
# =============================================================================
TEMPLATES = [
    {
        # BACKEND: Which template engine to use. DjangoTemplates is the default.
        'BACKEND': 'django.template.backends.django.DjangoTemplates',

        # DIRS: List of directories where Django looks for templates, OUTSIDE of apps.
        # BASE_DIR / 'templates' means: look in the project_root/templates/ folder.
        # App-level templates are found automatically because APP_DIRS=True.
        'DIRS': [BASE_DIR / 'templates'],

        # APP_DIRS: If True, Django also looks inside each app's templates/ folder.
        # This lets each app bundle its own templates (e.g., products/templates/)
        'APP_DIRS': True,

        # OPTIONS: Extra configuration for the template engine.
        'OPTIONS': {
            # context_processors are functions that automatically add data to
            # every template's context. They save you from repeating common data
            # in every view function.
            'context_processors': [
                # request processor: makes the HttpRequest object available in templates
                'django.template.context_processors.request',
                # auth processor: makes user, is_authenticated, etc. available in templates
                'django.contrib.auth.context_processors.auth',
                # messages processor: makes flash messages available in templates
                'django.contrib.messages.context_processors.messages',
                # role/permission processor: exposes the current user's role and
                # per-module permission flags (nav_perms) so the back-office nav
                # can show only the sections a user is allowed to use.
                'accounts.context_processors.role_permissions',
            ],
        },
    },
]

# =============================================================================
# WSGI APPLICATION ENTRY POINT
# =============================================================================
# WSGI (Web Server Gateway Interface) is the Python standard for connecting
# web servers to Python web applications. When a web server (Apache, Nginx,
# Gunicorn) receives an HTTP request, it passes it to the WSGI application.
# This setting points to the module that exposes the `application` callable.
# See logistic_manager/wsgi.py for the actual implementation.
# =============================================================================
WSGI_APPLICATION = 'logistic_manager.wsgi.application'


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
# Django supports multiple database backends: SQLite, PostgreSQL, MySQL, Oracle.
# For production on cPanel, we use MySQL because it is robust, scalable,
# and supported by cPanel hosting providers.
#
# ENGINE: The Django database backend module to use.
# NAME:    The database name created in cPanel MySQL.
# USER:    The MySQL username.
# PASSWORD: The MySQL password (should ideally come from environment variables).
# HOST:    'localhost' means the database runs on the same server as the app.
# PORT:    '3306' is the standard MySQL port.
# OPTIONS: Extra MySQL-specific settings.
# =============================================================================
# If DB_NAME is set we connect to MySQL (production on cPanel); otherwise we fall
# back to the local SQLite file so development needs no configuration at all.
DB_NAME = os.environ.get('DB_NAME', '').strip()

if DB_NAME:
    DATABASES = {
        'default': {
            # PyMySQL is installed as MySQLdb at the top of this file, so Django's
            # standard mysql backend works without the mysqlclient C extension
            # (which frequently fails to build on cPanel shared hosting).
            'ENGINE': 'django.db.backends.mysql',
            'NAME': DB_NAME,
            'USER': os.environ.get('DB_USER', '').strip(),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            # Some cPanel hosts route 'localhost' through a unix socket that the
            # Python app cannot see; if connections fail, try '127.0.0.1'.
            'HOST': os.environ.get('DB_HOST', 'localhost').strip(),
            'PORT': os.environ.get('DB_PORT', '3306').strip(),
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
            'OPTIONS': {
                # utf8mb4 is REQUIRED, not optional, for this project. MySQL's
                # legacy 'utf8' is only 3 bytes per character and cannot store
                # 4-byte characters. Ledger descriptions in this system contain
                # Chinese text and emoji pasted from WhatsApp; on a 3-byte utf8
                # column those raise an error or are silently truncated.
                # The database and its tables must also be utf8mb4 — see DEPLOY.md.
                'charset': 'utf8mb4',
                # STRICT_TRANS_TABLES makes MySQL reject bad values instead of
                # silently coercing them (e.g. truncating an over-long field).
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
            'ENGINE': 'django.db.backends.sqlite3',   # Local development default
            'NAME': BASE_DIR / 'db.sqlite3',          # Local SQLite database file
        }
    }


# =============================================================================
# PASSWORD VALIDATION
# =============================================================================
# These validators run when a user sets or changes their password. Django
# checks the password against ALL validators in this list. They protect against
# weak passwords that attackers could guess or brute-force.
#
# UserAttributeSimilarityValidator - Prevents passwords similar to username/email
# MinimumLengthValidator           - Requires at least 8 characters
# CommonPasswordValidator          - Rejects commonly used passwords (e.g., "password123")
# NumericPasswordValidator         - Rejects purely numeric passwords (e.g., "12345678")
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
# Django can translate content into multiple languages. These settings control
# the default language, timezone, and whether translation is enabled.
# =============================================================================

# LANGUAGE_CODE: The default language for the project. 'en-us' = US English.
# Django uses this for automatic translations, date formats, and number formatting.
LANGUAGE_CODE = 'en-us'

# TIME_ZONE: The default timezone for date/time display. 'UTC' is the safest
# default because it avoids daylight saving time confusion. In production,
# you might set this to the company's local timezone (e.g., 'Asia/Dubai').
TIME_ZONE = 'UTC'

# USE_I18N: Enable Django's internationalization framework. If True, Django
# will look for translation files (.po/.mo) and can serve content in different
# languages based on user preferences.
USE_I18N = True

# USE_TZ: Enable timezone-aware datetime handling. If True, Django stores all
# datetimes in UTC in the database and converts them to the local timezone
# when displaying. This is the modern, recommended approach.
USE_TZ = True


# =============================================================================
# STATIC FILES (CSS, JavaScript, Images)
# =============================================================================
# Static files are files that don't change per request: CSS stylesheets,
# JavaScript files, images, fonts. Django collects them from all apps and
# puts them into a single folder for efficient serving.
#
# STATIC_URL: The URL prefix that browsers use to request static files.
#             Example: /static/css/style.css maps to the filesystem.
# STATICFILES_DIRS: Additional directories to search for static files, besides
#                   each app's static/ folder. Here we add the project-level static/.
# STATIC_ROOT: The absolute filesystem path where `python manage.py collectstatic`
#              copies all static files. For cPanel, this points to public_html/static
#              so the web server can serve them directly.
# =============================================================================
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']     # Project-level static folder

# Where `collectstatic` writes. On cPanel this points into public_html so Apache
# can serve the files directly; override with DJANGO_STATIC_ROOT if your host
# uses a different document root.
STATIC_ROOT = Path(os.environ.get('DJANGO_STATIC_ROOT', BASE_DIR / 'public_html/static'))

# WhiteNoise storage: appends a content hash to each filename and compresses it,
# so browsers cache aggressively but pick up changes immediately after a deploy.
# Plain StorageClass in DEBUG to avoid needing collectstatic during development.
if not DEBUG:
    STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
    }

# =============================================================================
# MEDIA FILES (User Uploads)
# =============================================================================
# Media files are user-uploaded content: product images, PDFs, invoices.
# Unlike static files, these are uploaded at runtime and stored on disk.
# They should NEVER be inside the project code folder.
#
# MEDIA_URL: The URL prefix for uploaded files. In templates, you use
#             {{ object.image.url }} to get a URL like /media/products/photo.jpg.
# MEDIA_ROOT: The absolute filesystem path where uploaded files are stored.
#             For cPanel, this is in public_html so the web server can serve them.
# =============================================================================
MEDIA_URL = '/media/'
# Product images and uploaded labels. On cPanel point this at public_html/media
# via DJANGO_MEDIA_ROOT so Apache serves uploads without going through Django.
MEDIA_ROOT = Path(os.environ.get('DJANGO_MEDIA_ROOT', BASE_DIR / 'media'))


# =============================================================================
# SECURITY SETTINGS FOR PRODUCTION
# =============================================================================
# These settings harden the application against common web attacks.
# They are essential when DEBUG=False and the site is publicly accessible.
# =============================================================================

# -------------------------------------------------------------------------
# HTTPS / COOKIE SECURITY
# -------------------------------------------------------------------------
# These switch on automatically once DEBUG is False, so a production deploy is
# secure by default rather than depending on someone remembering to uncomment
# lines. If SSL is not active on the domain yet, set DJANGO_SECURE_SSL=0 in .env
# to postpone the HTTPS redirect — but turn it back on as soon as the
# certificate is installed.
# -------------------------------------------------------------------------
USE_HTTPS = env_bool('DJANGO_SECURE_SSL', not DEBUG)

# Only transmit session and CSRF cookies over HTTPS.
SESSION_COOKIE_SECURE = USE_HTTPS
CSRF_COOKIE_SECURE = USE_HTTPS

# Redirect any plain-HTTP request to HTTPS.
SECURE_SSL_REDIRECT = USE_HTTPS

# cPanel/Apache terminates SSL and forwards the original scheme in this header.
# Without it Django sees plain HTTP behind the proxy and would redirect forever.
if USE_HTTPS:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    # HSTS tells browsers to only ever use HTTPS for this domain. Start with a
    # short max-age; raise it once you are confident SSL is stable, because
    # browsers cache this and it cannot be easily undone.
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '3600'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_HSTS_SUBDOMAINS', False)
    SECURE_HSTS_PRELOAD = False

# Block JavaScript from reading the session cookie (defends against XSS theft).
SESSION_COOKIE_HTTPONLY = True

# Don't send the full URL as a referrer to other sites.
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# SECURE_BROWSER_XSS_FILTER: Adds the X-XSS-Protection header to tell browsers
# to enable their built-in XSS filter. This is a defense-in-depth measure.
SECURE_BROWSER_XSS_FILTER = True

# SECURE_CONTENT_TYPE_NOSNIFF: Adds the X-Content-Type-Options: nosniff header.
# This prevents browsers from MIME-sniffing a response away from the declared
# content type. For example, it stops a browser from treating a JS file as HTML.
SECURE_CONTENT_TYPE_NOSNIFF = True

# X_FRAME_OPTIONS: Controls whether this site can be displayed inside an iframe.
# 'DENY' means the site CANNOT be embedded in ANY iframe. This prevents
# clickjacking attacks where a malicious site tricks users into clicking
# hidden elements on your page.
X_FRAME_OPTIONS = 'DENY'

# =============================================================================
# CACHING CONFIGURATION
# =============================================================================
# Django's caching framework stores expensive-to-compute data in fast temporary
# storage so it doesn't need to be recalculated on every request. This improves
# page load times and reduces database load.
#
# We use the database cache backend because it works on all hosting environments
# (including cPanel shared hosting) without requiring Redis or Memcached daemons.
# The cache table is created with: python manage.py createcachetable
# =============================================================================
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache_table',
        'TIMEOUT': 300,  # Default cache expiration: 5 minutes (300 seconds)
        'OPTIONS': {
            'MAX_ENTRIES': 1000,  # Maximum number of cache entries before pruning
            'CULL_FREQUENCY': 3,  # When pruning, remove 1/3 of the oldest entries
        },
    }
}

# =============================================================================
# DEFAULT PRIMARY KEY FIELD TYPE
# =============================================================================
# All existing tables were created with the classic 32-bit AutoField primary
# key. Declaring it explicitly silences Django's models.W042 warnings and
# prevents makemigrations from generating unwanted BigAutoField migrations
# for every model. New projects would normally use BigAutoField, but changing
# it here would require migrating every existing table.
# =============================================================================
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# =============================================================================
# LOGIN REDIRECT URL
# =============================================================================
# LOGIN_URL is the URL that the auth guards redirect to when a user tries to
# access a protected page without being logged in. It points at the single
# unified login (accounts app), which then redirects each user to the right home
# based on their role (admin/staff → dashboard, support → queue, customer → portal).
# LOGIN_REDIRECT_URL / LOGOUT_REDIRECT_URL are fallbacks; the login view computes
# a role-aware destination itself.
# =============================================================================
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# =============================================================================
# SITES FRAMEWORK
# =============================================================================
# SITE_ID is used by django.contrib.sites to identify the current site.
# The sitemap framework uses this to generate absolute URLs.
# =============================================================================
SITE_ID = 1

# =============================================================================
# EMAIL CONFIGURATION
# =============================================================================
# Django supports multiple email backends: console (development), SMTP (production),
# file-based (testing), and third-party services. The backend is loaded dynamically
# from the CompanySettings model at runtime so the admin can configure it without
# editing code or restarting the server.
#
# For local development, the console backend prints emails to the terminal instead
# of sending them over the network. This is safe and requires no external setup.
# For production, the admin sets the SMTP host, port, username, and password in
# the Settings page, and the system switches to the SMTP backend automatically.
# =============================================================================

# Default email backend: console for development, safe fallback.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Default "From" email address. If the admin hasn't configured a from address
# in CompanySettings, this fallback is used.
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'orders@mudassirllc.com')

# Email timeout in seconds. Prevents the application from hanging if the SMTP
# server is slow or unreachable.
EMAIL_TIMEOUT = 15

