from django.urls import path

from sso import scim, views

urlpatterns = [
    path("orgs/<uuid:org_id>/sso", views.SSOConnectionView.as_view(), name="v2-sso"),
    path("orgs/<uuid:org_id>/sso/domains", views.SSODomainView.as_view(), name="v2-sso-domains"),
    path("orgs/<uuid:org_id>/sso/domains/<str:domain>/verify", views.SSODomainVerifyView.as_view(), name="v2-sso-domain-verify"),
    path("orgs/<uuid:org_id>/scim/tokens", scim.SCIMTokenView.as_view(), name="v2-scim-tokens"),
    path("sso/start", views.SSOStartView.as_view(), name="v2-sso-start"),
    path("sso/callback", views.SSOCallbackView.as_view(), name="v2-sso-callback"),
    path("sso/exchange", views.SSOExchangeView.as_view(), name="v2-sso-exchange"),
    path("sso/saml/acs", views.SAMLACSView.as_view(), name="v2-sso-saml-acs"),
    path("sso/saml/<uuid:org_id>/metadata", views.SAMLMetadataView.as_view(), name="v2-sso-saml-metadata"),
]
