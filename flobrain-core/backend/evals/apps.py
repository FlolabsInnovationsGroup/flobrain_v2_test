from django.apps import AppConfig


class EvalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "evals"
    verbose_name = "Evaluation sets and quality gates for buddies"

    def ready(self):
        from jobs.queue import register

        from evals import runner

        register(runner.JOB)(runner.run_job)
