from django.urls import path

from users.v2.views import (
    V2FirstLoginView,
    V2ForgotPasswordView,
    V2MeView,
    V2RefreshView,
    V2ResetPasswordView,
    V2SignInView,
    V2SignOutView,
)

urlpatterns = [
    path("auth/signin", V2SignInView.as_view(), name="v2-signin"),
    path("auth/refresh", V2RefreshView.as_view(), name="v2-refresh"),
    path("auth/signout", V2SignOutView.as_view(), name="v2-signout"),
    path("auth/password/forgot", V2ForgotPasswordView.as_view(), name="v2-password-forgot"),
    path("auth/password/reset", V2ResetPasswordView.as_view(), name="v2-password-reset"),
    path("auth/first-login", V2FirstLoginView.as_view(), name="v2-first-login"),
    path("me", V2MeView.as_view(), name="v2-me"),
]
