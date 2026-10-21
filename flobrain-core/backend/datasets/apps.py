from django.apps import AppConfig


class DatasetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "datasets"
    verbose_name = "Data buddy: datasets, questions in plain language, charts and scheduled reports"

    def ready(self):
        from datasets.tools import register

        register()
