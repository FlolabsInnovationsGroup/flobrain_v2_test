from django.urls import path

from integrations_hr.views import HRApplicantWebhookView

urlpatterns = [
    path("integrations/hr/applicants", HRApplicantWebhookView.as_view(), name="v2-hr-applicants"),
]
