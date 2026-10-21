from django.urls import path

from marketplace import views

urlpatterns = [
    path("orgs/<uuid:org_id>/marketplace", views.ListingView.as_view(), name="v2-marketplace"),
    path("orgs/<uuid:org_id>/marketplace/<uuid:listing_id>/withdraw", views.ListingWithdrawView.as_view(), name="v2-marketplace-withdraw"),
    path("orgs/<uuid:org_id>/marketplace/<uuid:listing_id>/install", views.ListingInstallView.as_view(), name="v2-marketplace-install"),
    path("orgs/<uuid:org_id>/marketplace/<uuid:listing_id>/versions", views.ListingVersionView.as_view(), name="v2-marketplace-versions"),
    path("orgs/<uuid:org_id>/marketplace/installs/<uuid:install_id>/update", views.InstallUpdateView.as_view(), name="v2-marketplace-update"),
    path("orgs/<uuid:org_id>/marketplace/<uuid:listing_id>/<str:decision>", views.ListingDecisionView.as_view(), name="v2-marketplace-decide"),
]
