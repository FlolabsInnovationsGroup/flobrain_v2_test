from django.urls import path

from growth import views as v

urlpatterns = [
    path("orgs/<uuid:org_id>/academy", v.AcademyView.as_view(), name="v2-academy"),
    path("orgs/<uuid:org_id>/academy/coach", v.CoachView.as_view(), name="v2-academy-coach"),
    path("orgs/<uuid:org_id>/academy/lessons/<slug:key>", v.LessonView.as_view(), name="v2-academy-lesson"),
    path("orgs/<uuid:org_id>/academy/lessons/<slug:key>/progress", v.LessonProgressView.as_view(), name="v2-academy-progress"),
    path("orgs/<uuid:org_id>/academy/lessons/<slug:key>/check", v.LessonCheckView.as_view(), name="v2-academy-check"),
    path("orgs/<uuid:org_id>/packs", v.PackListView.as_view(), name="v2-packs"),
    path("orgs/<uuid:org_id>/packs/<slug:key>/preview", v.PackPreviewView.as_view(), name="v2-pack-preview"),
    path("orgs/<uuid:org_id>/packs/<slug:key>/install", v.PackInstallView.as_view(), name="v2-pack-install"),
    path("orgs/<uuid:org_id>/packs/<slug:key>/uninstall", v.PackUninstallView.as_view(), name="v2-pack-uninstall"),
    path("orgs/<uuid:org_id>/ai-allowance", v.AllowanceView.as_view(), name="v2-ai-allowance"),
]
