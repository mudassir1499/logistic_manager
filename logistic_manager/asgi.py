"""
ASGI config for the logistic_manager project.

ASGI stands for Asynchronous Server Gateway Interface. It is the modern
Python standard for running asynchronous web applications. While WSGI
(for which see wsgi.py) is synchronous (one request at a time per worker),
ASGI supports asynchronous (non-blocking) operations, making it ideal for:
  - WebSockets (real-time bidirectional communication)
  - Long-polling and Server-Sent Events (SSE)
  - Handling many concurrent connections efficiently
  - Channels (Django's real-time framework)

For a standard logistics management application, ASGI is included by default
in modern Django projects. If you later add real-time features (like live
shipment tracking notifications), you would use ASGI instead of WSGI.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see:
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os  # Python standard library for interacting with the operating system

# Import the Django helper that creates the ASGI application object.
# get_asgi_application() works similarly to get_wsgi_application() but
# returns an ASGI-compatible application callable instead of a WSGI one.
# ASGI applications are async/await based and can handle multiple
# requests concurrently without blocking.
from django.core.asgi import get_asgi_application

# -------------------------------------------------------------------------
# SET THE DJANGO SETTINGS MODULE ENVIRONMENT VARIABLE
# -------------------------------------------------------------------------
# os.environ.setdefault() sets the environment variable only if it doesn't
# already exist. This variable tells Django WHERE to find its settings file.
# The value 'logistic_manager.settings' is a Python module path: Django
# will import logistic_manager/settings.py and read all configuration variables.
#
# This is the CRITICAL connection point. Without it, Django doesn't know
# which settings file to use, and the application won't start.
#
# Note: Both WSGI and ASGI use the same settings file. The only difference
# is the protocol (HTTP 1.1 via WSGI vs HTTP/2 or WebSocket via ASGI).
# -------------------------------------------------------------------------
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'logistic_manager.settings')

# -------------------------------------------------------------------------
# CREATE THE ASGI APPLICATION OBJECT
# -------------------------------------------------------------------------
# get_asgi_application() returns an ASGI-compatible application callable.
# An ASGI application is an async function (or callable) that accepts:
#   1. scope - a dictionary describing the connection (type, headers, path, etc.)
#   2. receive - an async function to read incoming messages from the client
#   3. send - an async function to send outgoing messages back to the client
# The application uses async/await to handle requests without blocking.
#
# To use ASGI in production, you would configure a server like Daphne,
# Hypercorn, or Uvicorn to point to this module and the 'application' variable.
# -------------------------------------------------------------------------
application = get_asgi_application()
