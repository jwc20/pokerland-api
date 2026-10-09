from django.apps import AppConfig


class HandsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hands"

    def ready(self):
        from hands import signals  # noqa: F401  connects the receivers that keep hands.results up to date
