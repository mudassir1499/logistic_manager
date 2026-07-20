import os           # Python standard library for filesystem paths and environment variables
import sys          # Python standard library for modifying the module search path

# =============================================================================
# cPanel Passenger WSGI Entry Point
# =============================================================================
# This file is a custom WSGI entry point specifically for cPanel hosting with
# Phusion Passenger. cPanel shared hosting uses Passenger to run Python apps
# (similar to how WSGI works on Apache, but Passenger manages the process
# lifecycle automatically).
#
# Place this file in the project root (next to manage.py).
# Point cPanel's Passenger to this file so it knows how to start your app.
#
# Why this file is needed (instead of just wsgi.py):
#   1. cPanel may not activate the virtual environment automatically.
#   2. The project root might not be in Python's module search path (sys.path).
#   3. Passenger needs explicit setup before it can find Django's WSGI app.
# =============================================================================

# -------------------------------------------------------------------------
# PROJECT ROOT PATH
# -------------------------------------------------------------------------
# os.path.dirname(os.path.abspath(__file__)) gets the directory containing
# this file (passenger_wsgi.py). Since this file is in the project root,
# PROJECT_ROOT is the full path to the project root folder. We use this
# to build paths to the virtual environment and to add the project to sys.path.
# -------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# -------------------------------------------------------------------------
# VIRTUAL ENVIRONMENT ACTIVATION
# -------------------------------------------------------------------------
# cPanel's Passenger does not automatically activate Python virtual environments.
# We manually add the virtual environment's site-packages directory to the
# beginning of sys.path so Python can find Django and all other installed packages.
#
# sys.path is a list of directories Python searches when importing modules.
# sys.path.insert(0, ...) adds the directory at the FRONT of the list, giving it
# the highest priority. This ensures our installed packages are found BEFORE
# any system-wide Python packages that might have conflicting versions.
#
# The path .venv/lib/python3.12/site-packages is the standard location for
# a virtual environment created with `python -m venv .venv` on Python 3.12.
# -------------------------------------------------------------------------
VENV_PATH = os.path.join(PROJECT_ROOT, '.venv', 'lib', 'python3.12', 'site-packages')
if VENV_PATH not in sys.path:
    # Only add if not already present (prevents duplicates on reloads)
    sys.path.insert(0, VENV_PATH)

# -------------------------------------------------------------------------
# ADD PROJECT ROOT TO PYTHON PATH
# -------------------------------------------------------------------------
# When Passenger runs this file, the project root directory might not be in
# Python's module search path. We add it so that imports like:
#   from logistic_manager import settings
# or
#   from products.models import Product
# work correctly. Without this, Django would fail to find the project modules.
# -------------------------------------------------------------------------
if PROJECT_ROOT not in sys.path:
    # Only add if not already present (prevents duplicates on reloads)
    sys.path.insert(0, PROJECT_ROOT)

# -------------------------------------------------------------------------
# SET DJANGO SETTINGS MODULE
# -------------------------------------------------------------------------
# Same as in wsgi.py and manage.py: we must tell Django which settings file
# to load before importing any Django code. os.environ.setdefault() sets the
# environment variable only if it doesn't already exist, allowing overrides.
# -------------------------------------------------------------------------
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'logistic_manager.settings')

# -------------------------------------------------------------------------
# IMPORT AND CREATE THE WSGI APPLICATION
# -------------------------------------------------------------------------
# Now that sys.path is correctly configured, we can safely import Django.
# get_wsgi_application() loads the settings, sets up the Django framework,
# and returns the WSGI application callable that Passenger will use to
# handle every HTTP request.
#
# The variable MUST be named 'application' — this is the convention that
# Passenger and most WSGI servers expect to find.
# -------------------------------------------------------------------------
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
