"""Middleware that answers ALB/container health checks without host validation."""


class HealthCheckMiddleware:
    """
    Must sit before CommonMiddleware so GET /healthz is not rejected when
    ALLOWED_HOSTS is strict and the load balancer sends the task IP as Host.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "GET" and request.path == "/healthz":
            from django.http import HttpResponse

            return HttpResponse("ok", status=200, content_type="text/plain")
        return self.get_response(request)
