from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'scheduling'
    verbose_name = "Jadval"

    def ready(self):
        from . import audit
        audit.connect_all()