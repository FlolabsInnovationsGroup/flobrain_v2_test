from django.urls import path

from learning import views as v

urlpatterns = [
    path("orgs/<uuid:org_id>/learning/paths", v.PathListView.as_view(), name="v2-learning-paths"),
    path("orgs/<uuid:org_id>/learning/paths/<uuid:path_id>/progress", v.PathProgressView.as_view(), name="v2-learning-progress"),
    path("orgs/<uuid:org_id>/learning/quizzes", v.QuizListView.as_view(), name="v2-quizzes"),
    path("orgs/<uuid:org_id>/learning/quizzes/draft", v.QuizDraftView.as_view(), name="v2-quiz-draft"),
    path("orgs/<uuid:org_id>/learning/quizzes/<uuid:quiz_id>", v.QuizDetailView.as_view(), name="v2-quiz"),
    path("orgs/<uuid:org_id>/learning/quizzes/<uuid:quiz_id>/attempts", v.QuizAttemptView.as_view(), name="v2-quiz-attempt"),
    path("orgs/<uuid:org_id>/learning/masterclasses", v.MasterclassView.as_view(), name="v2-masterclasses"),
    path("orgs/<uuid:org_id>/certificates", v.CertificateListView.as_view(), name="v2-certificates"),
    path("orgs/<uuid:org_id>/certificates/<uuid:cert_id>/revoke", v.CertificateRevokeView.as_view(), name="v2-certificate-revoke"),
    path("orgs/<uuid:org_id>/portfolio", v.PortfolioView.as_view(), name="v2-portfolio"),
    path("orgs/<uuid:org_id>/portfolio/<uuid:item_id>", v.PortfolioItemView.as_view(), name="v2-portfolio-item"),
    path("orgs/<uuid:org_id>/mentorships", v.MentorshipListView.as_view(), name="v2-mentorships"),
    path("orgs/<uuid:org_id>/mentorships/<uuid:mentorship_id>/notes", v.MentorNoteView.as_view(), name="v2-mentor-notes"),
    path("orgs/<uuid:org_id>/mentorships/<uuid:mentorship_id>/progress", v.MenteeProgressView.as_view(), name="v2-mentee-progress"),
    path("orgs/<uuid:org_id>/cohorts", v.CohortListView.as_view(), name="v2-cohorts"),
    path("orgs/<uuid:org_id>/cohorts/<uuid:cohort_id>", v.CohortProgressView.as_view(), name="v2-cohort"),
]
