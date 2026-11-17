from django.apps import AppConfig


class SettingsManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'settings_manager'
    verbose_name = 'Settings'

    def ready(self):
        """
        Register the deployment checks.

        Imported here rather than at module level because the checks read
        ``django.conf.settings``, which is not safe to touch until the app
        registry is populated.
        """
        from . import checks  # noqa: F401  (registration happens on import)
