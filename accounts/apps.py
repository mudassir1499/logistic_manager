from django.apps import AppConfig


class AccountsConfig(AppConfig):
    # Match the project-wide convention (settings.DEFAULT_AUTO_FIELD = AutoField)
    # so this app's tables use the same 32-bit primary key as every other table.
    default_auto_field = 'django.db.models.AutoField'
    name = 'accounts'
    verbose_name = 'Accounts & Roles'

    def ready(self):
        # Importing the signals module registers the post_save handler that
        # auto-creates a Profile for every new User. Imported here (not at module
        # top level) so it only runs once the app registry is fully loaded.
        from . import signals  # noqa: F401
