"""Public trust page, signed out.

- ``GET  /api/v2/public/trust/<slug>``: the published sections only (404 when not published or the flag is off)
- ``POST /api/v2/public/trust/<slug>/requests``: ``{name, email, company?, documents?, message?, website?}``;
  ``website`` is a honeypot. 3 requests an hour per visitor and 30 a day per org; then 429. Admins get an
  in-app notification and an email. The answer is the same whether or not an email went out.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from compliance import trust
from core_v2.views import V2PublicAPIView
from organizations.flags import client_ip


def _not_found():
    return Response({"error": "not_found", "details": "This trust page is not published"}, status=404)


class PublicTrustView(V2PublicAPIView):
    @extend_schema(summary="A published trust page (only the sections the org chose)")
    def get(self, request, slug):
        row = trust.published_for_slug(slug)
        if row is None:
            return _not_found()
        response = Response(trust.public_projection(row))
        response["Cache-Control"] = "public, max-age=60"
        return response


class PublicTrustRequestView(V2PublicAPIView):
    @extend_schema(summary="Ask for documents listed on a trust page")
    def post(self, request, slug):
        row = trust.published_for_slug(slug)
        if row is None or "documents" not in (row.sections or []):
            return _not_found()
        data = request.data if isinstance(request.data, dict) else {}
        name = trust.clean_text(data.get("name"), 120)
        email = str(data.get("email") or "").strip()
        if not name or not trust.EMAIL_RE.match(email):
            return Response({"error": "invalid", "details": "Enter your name and a valid work email"}, status=400)
        docs = data.get("documents") or []
        if not isinstance(docs, list):
            return Response({"error": "invalid", "details": "documents must be a list"}, status=400)
        if not trust.allow_request(row, client_ip(request) or ""):
            return Response({"error": "too_many_requests", "details": "Too many requests. Try again later."}, status=429)
        if str(data.get("website") or "").strip():
            return Response({"ok": True}, status=202)  # honeypot: looks fine, does nothing
        trust.create_request(row, data, client_ip(request) or "")
        return Response({"ok": True, "details": "Thanks. The team will check your request and answer by email."}, status=202)
