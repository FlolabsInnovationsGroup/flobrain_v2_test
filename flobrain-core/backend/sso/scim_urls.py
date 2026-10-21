from django.urls import path

from sso import scim

urlpatterns = [
    path("scim/v2/Users", scim.UsersView.as_view(), name="scim-users"),
    path("scim/v2/Users/<str:user_id>", scim.UserDetailView.as_view(), name="scim-user"),
    path("scim/v2/Groups", scim.GroupsView.as_view(), name="scim-groups"),
    path("scim/v2/Groups/<str:group_id>", scim.GroupDetailView.as_view(), name="scim-group"),
]
