from django.apps import AppConfig


class ApiConfig(AppConfig):
    """The versioned JSON API. Holds no models of its own - it exposes the rest."""

    default_auto_field = 'django.db.models.AutoField'
    name = 'api'
    verbose_name = 'JSON API'

    def ready(self):
        """
        Import the schema extensions for their registration side effect.

        drf-spectacular discovers OpenApiAuthenticationExtension subclasses by
        import, so a module nothing references is a module that never runs.
        """
        from . import schema  # noqa: F401
