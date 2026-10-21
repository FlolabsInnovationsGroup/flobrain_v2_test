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

urlpatterns = [
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
