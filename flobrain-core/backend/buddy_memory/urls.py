from django.urls import path

from buddy_memory import views

P = "orgs/<uuid:org_id>/memory"

urlpatterns = [
    path(P, views.MemorySummaryView.as_view(), name="v2-memory"),
    path(f"{P}/items", views.MemoryItemsView.as_view(), name="v2-memory-items"),
    path(f"{P}/items/<uuid:item_id>", views.MemoryItemDetailView.as_view(), name="v2-memory-item"),
    path(f"{P}/items/<uuid:item_id>/confirm", views.MemoryDecisionView.as_view(decision="confirm"), name="v2-memory-item-confirm"),
    path(f"{P}/items/<uuid:item_id>/reject", views.MemoryDecisionView.as_view(decision="reject"), name="v2-memory-item-reject"),
    path(f"{P}/me", views.MemoryMeView.as_view(), name="v2-memory-me"),
    path(f"{P}/rules", views.MemoryRulesView.as_view(), name="v2-memory-rules"),
    path(f"{P}/teams", views.MemoryTeamsView.as_view(), name="v2-memory-teams"),
    path(f"{P}/teams/<uuid:team_id>/items", views.MemoryTeamItemsView.as_view(), name="v2-memory-team-items"),
    path(f"{P}/teams/<uuid:team_id>/items/<uuid:item_id>", views.MemoryTeamItemDetailView.as_view(), name="v2-memory-team-item"),
]
