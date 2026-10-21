from django.urls import path

from demo import views

urlpatterns = [
    path("demo", views.DemoInfoView.as_view(), name="v2-demo"),
    path("demo/signin", views.DemoSignInView.as_view(), name="v2-demo-signin"),
    path("demo/reset", views.DemoResetView.as_view(), name="v2-demo-reset"),
    path("demo/idp/sso", views.DemoIdPView.as_view(), name="v2-demo-idp"),
]
