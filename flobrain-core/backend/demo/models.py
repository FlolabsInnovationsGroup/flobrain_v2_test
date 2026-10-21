from django.db import models


class DemoAccount(models.Model):
    """Marks a seeded demo user. Demo sign-in only ever issues tokens for these rows."""

    user = models.OneToOneField("users.User", on_delete=models.CASCADE, primary_key=True, related_name="demo_account")
    role = models.CharField(max_length=16, unique=True)

    class Meta:
        db_table = "demo_accounts"
