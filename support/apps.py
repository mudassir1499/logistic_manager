from django.apps import AppConfig


class SupportConfig(AppConfig):
    # Match the project-wide AutoField convention (see settings.DEFAULT_AUTO_FIELD).
    default_auto_field = 'django.db.models.AutoField'
    name = 'support'
    verbose_name = 'Support Tickets'
