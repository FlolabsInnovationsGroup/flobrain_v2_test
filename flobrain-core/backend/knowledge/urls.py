from django.urls import path

from knowledge.views import KnowledgeAskView

urlpatterns = [
    path("orgs/<uuid:org_id>/knowledge/ask", KnowledgeAskView.as_view(), name="v2-knowledge-ask"),
]
