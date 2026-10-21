from django.urls import path

from buddies.views import (
    BuddyDetailView,
    BuddyListView,
    BuddyShareDecisionView,
    BuddyShareRequestListView,
    BuddyShareView,
    BuddyPinView,
    BuddyThreadDetailView,
    BuddyThreadListCreateView,
    BuddyThreadSendView,
)
from buddies.views_quality import (
    BuddyFeedbackDetailView,
    BuddyFeedbackView,
    BuddyQualityView,
    BuddyRouteView,
    BuddyTemplateInstallView,
    BuddyTemplateListView,
)

urlpatterns = [
    # Crew (W5): Flo routing hints, specialist templates, feedback and quality. Before <uuid:buddy_id>.
    path("orgs/<uuid:org_id>/buddies/route", BuddyRouteView.as_view(), name="v2-buddy-route"),
    path("orgs/<uuid:org_id>/buddies/templates", BuddyTemplateListView.as_view(), name="v2-buddy-templates"),
    path(
        "orgs/<uuid:org_id>/buddies/templates/<slug:key>/install",
        BuddyTemplateInstallView.as_view(),
        name="v2-buddy-template-install",
    ),
    path("orgs/<uuid:org_id>/buddies/feedback", BuddyFeedbackView.as_view(), name="v2-buddy-feedback"),
    path(
        "orgs/<uuid:org_id>/buddies/feedback/<int:message_id>",
        BuddyFeedbackDetailView.as_view(),
        name="v2-buddy-feedback-detail",
    ),
    path("orgs/<uuid:org_id>/buddies/quality", BuddyQualityView.as_view(), name="v2-buddy-quality"),
    path("orgs/<uuid:org_id>/buddies", BuddyListView.as_view(), name="v2-buddies"),
    path("orgs/<uuid:org_id>/buddies/pins", BuddyPinView.as_view(), name="v2-buddy-pins"),
    path(
        "orgs/<uuid:org_id>/buddies/share-requests",
        BuddyShareRequestListView.as_view(),
        name="v2-buddy-share-requests",
    ),
    path("orgs/<uuid:org_id>/buddies/<uuid:buddy_id>", BuddyDetailView.as_view(), name="v2-buddy-detail"),
    path("orgs/<uuid:org_id>/buddies/<uuid:buddy_id>/share", BuddyShareView.as_view(), name="v2-buddy-share"),
    path(
        "orgs/<uuid:org_id>/buddies/<uuid:buddy_id>/share/<str:decision>",
        BuddyShareDecisionView.as_view(),
        name="v2-buddy-share-decision",
    ),
    path("orgs/<uuid:org_id>/buddies/threads/<int:thread_id>", BuddyThreadDetailView.as_view(), name="v2-buddy-thread"),
    path(
        "orgs/<uuid:org_id>/buddies/threads/<int:thread_id>/send",
        BuddyThreadSendView.as_view(),
        name="v2-buddy-thread-send",
    ),
    path(
        "orgs/<uuid:org_id>/buddies/<uuid:buddy_id>/threads",
        BuddyThreadListCreateView.as_view(),
        name="v2-buddy-threads",
    ),
]
