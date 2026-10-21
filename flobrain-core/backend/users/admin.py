from django.contrib import admin

from .models import Role, User

admin.site.register(Role)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "username", "user_type", "is_platform_admin", "created_at")
    list_filter = ("is_platform_admin", "user_type")
    search_fields = ("email", "username")
    readonly_fields = ("id", "created_at")