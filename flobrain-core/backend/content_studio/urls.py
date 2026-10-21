from django.urls import path

from content_studio import views, views_local, views_publish as vp

P = "orgs/<uuid:org_id>/content"

urlpatterns = [
    path(f"{P}/brand-kits", views.BrandKitListView.as_view(), name="v2-content-brand-kits"),
    path(f"{P}/brand-kits/<uuid:kit_id>", views.BrandKitDetailView.as_view(), name="v2-content-brand-kit"),
    path(f"{P}/templates", views.TemplateListView.as_view(), name="v2-content-templates"),
    path(f"{P}/templates/<uuid:template_id>", views.TemplateDetailView.as_view(), name="v2-content-template"),
    path(f"{P}/assets", views.AssetListCreateView.as_view(), name="v2-content-assets"),
    path(f"{P}/assets/<uuid:asset_id>", views.AssetDetailView.as_view(), name="v2-content-asset"),
    path(f"{P}/assets/<uuid:asset_id>/complete", views.AssetCompleteView.as_view(), name="v2-content-asset-complete"),
    path(f"{P}/projects", views.ProjectListCreateView.as_view(), name="v2-content-projects"),
    path(f"{P}/projects/<uuid:project_id>", views.ProjectDetailView.as_view(), name="v2-content-project"),
    path(f"{P}/projects/<uuid:project_id>/render", views.ProjectRenderView.as_view(), name="v2-content-project-render"),
    path(f"{P}/renders", views.RenderListView.as_view(), name="v2-content-renders"),
    path(f"{P}/renders/<uuid:render_id>", views.RenderDetailView.as_view(), name="v2-content-render"),
    path(f"{P}/renders/<uuid:render_id>/consent", vp.RenderConsentView.as_view(), name="v2-content-render-consent"),
    path(f"{P}/projects/<uuid:project_id>/consent", vp.ProjectConsentView.as_view(), name="v2-content-project-consent"),
    path(f"{P}/assets/<uuid:asset_id>/transcribe", views.AssetTranscribeView.as_view(), name="v2-content-asset-transcribe"),
    path("content/local/<path:key>", views_local.LocalMediaView.as_view(), name="v2-content-local"),
    path(f"{P}/assets/<uuid:asset_id>/transcript", views.AssetTranscriptView.as_view(), name="v2-content-asset-transcript"),
    path(f"{P}/projects/<uuid:project_id>/edl", views.ProjectEDLView.as_view(), name="v2-content-edl"),
    path(f"{P}/projects/<uuid:project_id>/edl/revert", views.ProjectEDLRevertView.as_view(), name="v2-content-edl-revert"),
    path(
        f"{P}/projects/<uuid:project_id>/captions.<str:fmt>", views.ProjectCaptionsView.as_view(), name="v2-content-captions"
    ),
    path(f"{P}/projects/<uuid:project_id>/suggest-clips", views.ProjectSuggestClipsView.as_view(), name="v2-content-suggest"),
    path(f"{P}/projects/<uuid:project_id>/auto-edit", views.ProjectAutoEditView.as_view(), name="v2-content-auto-edit"),
    path(f"{P}/clips/<uuid:clip_id>/accept", views.ClipAcceptView.as_view(), name="v2-content-clip-accept"),
    path(f"{P}/renders/<uuid:render_id>/cancel", views.RenderCancelView.as_view(), name="v2-content-render-cancel"),
    path(f"{P}/consents", vp.ConsentListView.as_view(), name="v2-content-consents"),
    path(f"{P}/consents/<uuid:consent_id>/revoke", vp.ConsentRevokeView.as_view(), name="v2-content-consent-revoke"),
    path(f"{P}/assets/<uuid:asset_id>/people", vp.AssetPeopleView.as_view(), name="v2-content-asset-people"),
    path("orgs/<uuid:org_id>/social-accounts", vp.SocialAccountListView.as_view(), name="v2-social-accounts"),
    path("orgs/<uuid:org_id>/social-accounts/platforms", vp.PlatformListView.as_view(), name="v2-social-platforms"),
    path(
        "orgs/<uuid:org_id>/social-accounts/<str:platform>/connect",
        vp.SocialConnectView.as_view(),
        name="v2-social-connect",
    ),
    path(
        "orgs/<uuid:org_id>/social-accounts/<uuid:account_id>",
        vp.SocialAccountDetailView.as_view(),
        name="v2-social-account",
    ),
    path("oauth/callback/<str:platform>", vp.OAuthCallbackView.as_view(), name="v2-oauth-callback"),
    path("orgs/<uuid:org_id>/social-accounts/confirm", vp.SocialConfirmView.as_view(), name="v2-social-confirm"),
    path("orgs/<uuid:org_id>/publish-jobs", vp.PublishJobListCreateView.as_view(), name="v2-publish-jobs"),
    path("orgs/<uuid:org_id>/publish-jobs/<uuid:job_id>", vp.PublishJobDetailView.as_view(), name="v2-publish-job"),
    path(
        "orgs/<uuid:org_id>/publish-jobs/<uuid:job_id>/approve",
        vp.PublishJobApproveView.as_view(),
        name="v2-publish-job-approve",
    ),
    path(
        "orgs/<uuid:org_id>/publish-jobs/<uuid:job_id>/cancel", vp.PublishJobCancelView.as_view(), name="v2-publish-job-cancel"
    ),
    path(f"{P}/calendar", vp.ContentCalendarView.as_view(), name="v2-content-calendar"),
    path(f"{P}/batch", views.BatchRenderView.as_view(), name="v2-content-batch"),
    path(f"{P}/projects/<uuid:project_id>/copy", views.ProjectCopyView.as_view(), name="v2-content-copy"),
    path(f"{P}/voiceover", views.VoiceoverView.as_view(), name="v2-content-voiceover"),
]
