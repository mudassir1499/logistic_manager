#!/usr/bin/env python
"""
Django's command-line utility for administrative tasks.

This file is the entry point for ALL Django management commands. When you run:
    python manage.py runserver
    python manage.py migrate
    python manage.py collectstatic
    python manage.py createsuperuser
...you are actually executing this script. It sets up the environment, imports
Django, and passes your command-line arguments to Django's management framework.

Think of manage.py as the "control panel" for your Django project. It is not
used in production (the web server calls wsgi.py directly), but it is
essential for development, deployment preparation, and maintenance.
"""

import os      # Python standard library for OS interactions (environment variables, paths)
import sys     # Python standard library for system-specific parameters (command-line args)


def main():
    """
    Run administrative tasks by delegating to Django's command-line framework.

    This function is called every time you run a management command. It performs
    three critical steps:
      1. Sets the DJANGO_SETTINGS_MODULE environment variable so Django knows
         which settings file to load.
      2. Imports Django's execute_from_command_line function.
      3. Passes all command-line arguments (sys.argv) to Django, which then
         routes them to the correct management command (e.g., runserver, migrate).

    Args:
        None (reads from sys.argv automatically).

    Returns:
        None (may raise SystemExit on error).

    Business Logic:
        Management commands are how developers and admins interact with the
        Django project outside of normal web requests. This includes:
        - Creating database tables (migrate)
        - Starting the development server (runserver)
        - Collecting static files for production (collectstatic)
        - Creating an admin user (createsuperuser)
        - Running the interactive Python shell (shell)
        - Running custom app-defined commands (e.g., import data, send reports)
    """
    # -------------------------------------------------------------------------
    # STEP 1: Set the Django settings module environment variable
    # -------------------------------------------------------------------------
    # os.environ.setdefault() sets the variable ONLY if it is not already set.
    # This allows advanced users to override the settings file by setting the
    # environment variable before running the command. For example:
    #   export DJANGO_SETTINGS_MODULE=logistic_manager.production_settings
    #   python manage.py runserver
    # -------------------------------------------------------------------------
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'logistic_manager.settings')

    # -------------------------------------------------------------------------
    # STEP 2: Import Django's command-line executor
    # -------------------------------------------------------------------------
    # execute_from_command_line() is the heart of Django's management system.
    # It reads sys.argv (the list of command-line arguments), parses the first
    # argument as the command name, finds the corresponding command class, and
    # runs it. For example, "python manage.py migrate" becomes sys.argv like:
    # ['manage.py', 'migrate'] and Django runs the MigrateCommand.
    #
    # The import is inside try/except so that if Django is not installed or
    # not on PYTHONPATH, the user gets a helpful error message instead of a
    # confusing ImportError traceback.
    # -------------------------------------------------------------------------
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        # -------------------------------------------------------------------------
        # HELPFUL ERROR HANDLING FOR BEGINNERS
        # -------------------------------------------------------------------------
        # If Django cannot be imported, it usually means one of three things:
        # 1. Django is not installed (pip install django)
        # 2. The virtual environment is not activated
        # 3. The current directory is not in PYTHONPATH
        # We raise a new ImportError with a clear, actionable message.
        # -------------------------------------------------------------------------
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # -------------------------------------------------------------------------
    # STEP 3: Execute the command
    # -------------------------------------------------------------------------
    # sys.argv is a list where the first item is the script name (manage.py)
    # and the remaining items are the command and its arguments.
    # Example: ['manage.py', 'runserver', '0.0.0.0:8000']
    # execute_from_command_line parses this and runs the appropriate command.
    # -------------------------------------------------------------------------
    execute_from_command_line(sys.argv)


# -------------------------------------------------------------------------
# MAIN ENTRY POINT
# -------------------------------------------------------------------------
# __name__ == '__main__' is a Python idiom that checks whether this script
# is being run directly (not imported as a module). When you run:
#   python manage.py runserver
# Python sets __name__ to '__main__', so main() is called.
# If another file imports manage.py (which is rare), __name__ would be 'manage',
# and main() would NOT run automatically.
# -------------------------------------------------------------------------
if __name__ == '__main__':
    main()
