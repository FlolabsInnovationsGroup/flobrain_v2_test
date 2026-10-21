from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler


class V2APIError(APIException):
    status_code = 400
    default_code = "error"
    default_detail = "Request failed"

    def __init__(self, code="error", details=None, status_code=None):
        super().__init__(detail=details or code, code=code)
        self.default_code = code
        if status_code:
            self.status_code = status_code


def v2_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None
    code = getattr(exc, "default_code", None) or "error"
    if hasattr(exc, "get_codes"):
        try:
            codes = exc.get_codes()
            if isinstance(codes, str):
                code = codes
        except Exception:
            pass
    details = getattr(exc, "detail", str(exc))
    response.data = {"error": str(code), "details": details}
    return response
