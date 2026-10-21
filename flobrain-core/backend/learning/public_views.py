"""Public pages (no sign-in): certificate verification and opt-in portfolios (Phase 11).

They return only what the person chose to publish, never ids of other records,
emails, or anything from the org beyond its name.
"""

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2PublicAPIView
from learning import certs
from learning.models import Certificate, PortfolioItem
from organizations.flags import effective_flag


class CertificateVerifyView(V2PublicAPIView):
    @extend_schema(summary="Verify a certificate by its public id")
    def get(self, request, slug):
        cert = Certificate.objects.filter(public_slug=slug).select_related("org").first()
        if cert is None:
            return Response({"error": "not_found", "details": "No certificate with this id"}, status=404)
        try:
            valid = certs.verify(cert.data, cert.signature, cert.key_id)
            public_key = certs.key_ring().get(cert.key_id, "")
        except certs.NotConfigured:
            valid, public_key = False, ""
        return Response(
            {
                "data": cert.data,
                "signature": cert.signature,
                "key_id": cert.key_id,
                "public_key": public_key,
                "signature_valid": valid,
                "demo_key": certs.is_demo_key_id(cert.key_id),
                "revoked": cert.revoked_at is not None,
                "revoked_at": cert.revoked_at.isoformat() if cert.revoked_at else None,
                "verify_url": f"{(getattr(settings, 'FRONTEND_BASE_URL', '') or '').rstrip('/')}/verify/{cert.public_slug}",
            }
        )


class CertificateKeyView(V2PublicAPIView):
    @extend_schema(summary="The Ed25519 public key certificates are signed with")
    def get(self, request):
        try:
            return Response({"algorithm": "Ed25519", "public_key": certs.public_key_b64(), "key_id": certs.key_id(), "demo": certs.using_demo_key()})
        except certs.NotConfigured:
            return Response({"error": "not_configured"}, status=404)


class PortfolioPublicView(V2PublicAPIView):
    @extend_schema(summary="A person's public portfolio")
    def get(self, request, slug):
        from users.models import User

        user = User.objects.filter(portfolio_slug=slug).first()
        if user is None:
            return Response({"error": "not_found"}, status=404)
        items = []
        for item in PortfolioItem.objects.filter(user=user, is_public=True).select_related("org").order_by("-created_at"):
            if not effective_flag(item.org, None, "public_portfolio", default=False):
                continue  # the org has not allowed public portfolios
            row = {"kind": item.kind, "title": item.title, "summary": item.summary, "organization": item.org.name}
            if item.kind == "certificate":
                cert = Certificate.objects.filter(user=user, public_slug=item.ref_id, revoked_at__isnull=True).first()
                if cert is None:
                    continue
                row["verify"] = f"/verify/{cert.public_slug}"
            items.append(row)
        if not items:
            return Response({"error": "not_found"}, status=404)
        return Response({"name": user.username or "FloBrain member", "items": items})
