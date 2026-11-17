from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path("", RedirectView.as_view(url="/api/docs/", permanent=False)),
    path("admin/", admin.site.urls),
    # OpenAPI / Swagger
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # API
    path("api/auth/", include("employees.auth_urls")),
    path("api/", include("employees.urls")),
    path("api/", include("rostering.urls")),
    path("api/", include("surveys.urls")),
    path("api/", include("wellbeing.urls")),
    # Chat test page (WebSocket client)
    path("chat/", include("chat.urls")),
]
