from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = "users"

    def ready(self):
        # Register startup checks (AES_MASTER_KEY, SECRET_KEY).
        from flobrain import checks  # noqa: F401
