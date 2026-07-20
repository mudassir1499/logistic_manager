"""
WSGI config for the logistic_manager project.

WSGI stands for Web Server Gateway Interface. It is the Python standard
specification that defines how a web server (like Apache or Nginx) talks
to a Python web application. This file is the bridge between your web server
and your Django project.

It exposes the WSGI callable as a module-level variable named ``application``.
When the web server receives an HTTP request, it calls this ``application``
object with the request data, and Django processes it and returns a response.

For more information on this file, see:
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os  # Python standard library for interacting with the operating system

# Import the Django helper that creates the WSGI application object.
# get_wsgi_application() reads the DJANGO_SETTINGS_MODULE environment variable,
# loads the settings, sets up the Django framework, and returns a callable
# that the web server can use to process HTTP requests.
from django.core.wsgi import get_wsgi_application

# -------------------------------------------------------------------------
# SET THE DJANGO SETTINGS MODULE ENVIRONMENT VARIABLE
# -------------------------------------------------------------------------
# os.environ.setdefault() sets the environment variable only if it doesn't
# already exist. This variable tells Django WHERE to find its settings.
# The value 'logistic_manager.settings' is a Python module path, meaning
# Django will import logistic_manager/settings.py and read all the variables.
#
# This is the CRITICAL connection point. Without it, Django doesn't know
# which settings file to use, and the application won't start.
# -------------------------------------------------------------------------
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'logistic_manager.settings')

# -------------------------------------------------------------------------
# CREATE THE WSGI APPLICATION OBJECT
# -------------------------------------------------------------------------
# get_wsgi_application() returns a callable (a function-like object) that
# the web server invokes for every HTTP request. The web server passes:
#   1. environ - a dictionary of CGI-style environment variables (headers, method, path, etc.)
#   2. start_response - a callback function the app calls to send the HTTP status and headers
# The application returns an iterable of response body bytes (usually the HTML page).
#
# The web server configuration (e.g., Apache's mod_wsgi or Passenger) points
# to this module and expects to find the 'application' variable.
# -------------------------------------------------------------------------
application = get_wsgi_application()
