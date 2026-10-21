from django.urls import path

from learning import public_views as v

urlpatterns = [
    path("api/public/verify/<str:slug>", v.CertificateVerifyView.as_view(), name="public-verify"),
    path("api/public/certificates/public-key", v.CertificateKeyView.as_view(), name="public-cert-key"),
    path("api/public/portfolio/<str:slug>", v.PortfolioPublicView.as_view(), name="public-portfolio"),
]
