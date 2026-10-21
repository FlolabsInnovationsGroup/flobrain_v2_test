from django.apps import AppConfig


class EinvoiceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "einvoice"
    verbose_name = "E-invoicing for Saudi Arabia (ZATCA) and Egypt (ETA), data residency"

    def ready(self):
        from einvoice.tools import register

        register()
