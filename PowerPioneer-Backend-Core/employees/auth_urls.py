from django.urls import path
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView, TokenVerifyView

from .views import ChangePasswordView, LoginView, MeView, RegisterView

urlpatterns = [
    path("token/", LoginView.as_view(), name="token_obtain_pair"),
    path(
        "token/refresh/",
        extend_schema_view(post=extend_schema(tags=["Auth"], summary="Refresh the access token"))(
            TokenRefreshView
        ).as_view(),
        name="token_refresh",
    ),
    path(
        "token/verify/",
        extend_schema_view(post=extend_schema(tags=["Auth"], summary="Verify a token"))(TokenVerifyView).as_view(),
        name="token_verify",
    ),
    path(
        "logout/",
        extend_schema_view(post=extend_schema(tags=["Auth"], summary="Logout: blacklist the refresh token"))(
            TokenBlacklistView
        ).as_view(),
        name="token_blacklist",
    ),
    path("register/", RegisterView.as_view(), name="register"),
    path("me/", MeView.as_view(), name="me"),
    path("change-password/", ChangePasswordView.as_view(), name="change_password"),
]
