"""
Django settings for the PowerPioneer backend.

Values can be overridden with environment variables for non-local setups.
"""
import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Secrets live in a local .env file next to manage.py (git-ignored). See .env.example.
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-local-dev-key-change-me-in-production-0123456789",
)
DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    # daphne must come before staticfiles so `runserver` serves ASGI (HTTP + WebSocket)
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "channels",
    "corsheaders",
    # local apps
    "employees",
    "rostering",
    "surveys",
    "wellbeing",
    "chat",
]

MIDDLEWARE = [
    # CORS must run before CommonMiddleware so preflight requests get the headers
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database: Supabase Postgres (session pooler, port 5432)
# Only SUPABASE_DB_PASSWORD is required in .env; the rest default to the team project.
# ---------------------------------------------------------------------------
if not os.environ.get("SUPABASE_DB_PASSWORD"):
    raise ImproperlyConfigured(
        "SUPABASE_DB_PASSWORD is not set. Create a .env file next to manage.py "
        "(copy .env.example) and put the Supabase database password in it."
    )

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("SUPABASE_DB_NAME", "postgres"),
        "USER": os.environ.get("SUPABASE_DB_USER", "postgres.lzxnflyjcjchytjxzobz"),
        "PASSWORD": os.environ["SUPABASE_DB_PASSWORD"],
        "HOST": os.environ.get("SUPABASE_DB_HOST", "aws-1-ap-south-1.pooler.supabase.com"),
        "PORT": os.environ.get("SUPABASE_DB_PORT", "5432"),
    }
}

# The `employee` table is the user table of the application.
AUTH_USER_MODEL = "employees.Employee"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # Session auth lets you use the browsable API after logging into /admin/
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "COERCE_DECIMAL_TO_STRING": False,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "employee_id",
    "USER_ID_CLAIM": "employee_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "PowerPioneer Backend API",
    "DESCRIPTION": (
        "Employee wellbeing platform: employees, rosters, attendance, leave, "
        "pulse surveys, wellbeing scoring, risk predictions and interventions.\n\n"
        "**How to authenticate:** call `POST /api/auth/token/` with email and password, "
        "copy the `access` token, click **Authorize** and paste it (no `Bearer ` prefix needed).\n\n"
        "**WebSocket chat:** `ws://<host>/ws/chat/<room>/?token=<access>` or "
        "`ws://<host>/ws/chat/direct/<employee_id>/?token=<access>`. "
        "A browser test client is available at `/chat/test/`."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True},
    "ENUM_NAME_OVERRIDES": {"RiskBandEnum": "wellbeing.models.RiskBand"},
}

# ---------------------------------------------------------------------------
# Channels (WebSocket). In-memory layer is fine for a single local process.
# ---------------------------------------------------------------------------
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# ---------------------------------------------------------------------------
# Domain settings
# ---------------------------------------------------------------------------
# Maximum number of employees a single buddy may support at the same time.
BUDDY_MAX_ASSIGNEES = int(os.environ.get("BUDDY_MAX_ASSIGNEES", "3"))

# ---------------------------------------------------------------------------
# CORS: lets the separately served frontend (Vite dev server) call the API.
# Override with a comma-separated list in DJANGO_CORS_ALLOWED_ORIGINS.
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "DJANGO_CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    ).split(",")
    if o.strip()
]
