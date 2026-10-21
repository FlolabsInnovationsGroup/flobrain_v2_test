from rest_framework import status
from rest_framework.response import Response


def platform_admin_required(user):
    """Return a 403 response unless the user may write to the shared registry."""
    if getattr(user, "is_platform_admin", False):
        return None
    return Response(
        {
            "error": "Forbidden",
            "details": "Only platform admins can change the model registry",
        },
        status=status.HTTP_403_FORBIDDEN,
    )
