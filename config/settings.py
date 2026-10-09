"""
AstonBundle settings.

Secrets and environment-specific values are read from environment variables
(or a local, git-ignored `.env` file). Nothing sensitive is committed.
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-change-me"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DEBUG is off.")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "accounts",
    "catalog",
    "inventory",
    "orders",
    "reviews",
    "support",
    "staff",
    "ai",
    "living",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
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
                "core.context_processors.site",
            ],
            "builtins": ["core.templatetags.ab", "django.contrib.humanize.templatetags.humanize"],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database: PostgreSQL in Docker / production via DATABASE_URL.
# Falls back to a local SQLite file so the project also runs with no setup.
if not os.environ.get("DATABASE_URL", "").strip():
    os.environ.pop("DATABASE_URL", None)
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.EmailBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "accounts.validators.MixedCharacterValidator"},
]

LOGIN_URL = "accounts:signin"
LOGIN_REDIRECT_URL = "accounts:overview"
LOGOUT_REDIRECT_URL = "core:home"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email is SIMULATED: every message is stored in the Demo Inbox table,
# nothing is sent to a real address.
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "accounts.email_backend.DemoInboxBackend")
DEMO_INBOX_ENABLED = EMAIL_BACKEND == "accounts.email_backend.DemoInboxBackend"
# Password-reset emails are only shown in the Demo inbox for these public test
# accounts, or for an account registered in the same browser session.
DEMO_RESET_VISIBLE = ["demo.student@aston.ac.uk"]
DEFAULT_FROM_EMAIL = "AstonBundle <no-reply@astonbundle.example>"

# Sessions & cookies
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# HTTPS: on by default in production. Set DJANGO_HTTPS=false only for a temporary
# test deployment without a certificate (cookies would otherwise not be sent).
HTTPS = env_bool("DJANGO_HTTPS", not DEBUG)
if HTTPS:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# ---- AstonBundle business settings -------------------------------------
ASTON_EMAIL_DOMAIN = "aston.ac.uk"
STAFF_EMAIL_DOMAIN = "astonbundle.example"
VERIFICATION_CODE_TTL_MINUTES = 10
VERIFICATION_MAX_ATTEMPTS = 5
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
FREE_DELIVERY_THRESHOLD = 40  # GBP
DELIVERY_FEE = "3.99"
RETURN_WINDOW_DAYS = 30
SLOT_CAPACITY = 25  # orders per delivery slot
# Indicative exchange rates for the "home-currency estimate" only.
# Customers always pay in GBP. Update the date when the rates are refreshed.
FX_RATES_AS_OF = "1 October 2026"
FX_RATES = {"TRY": 56.0, "INR": 118.0, "CNY": 9.6, "NGN": 2050.0, "PKR": 372.0}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}
PASSWORD_RESET_TIMEOUT = 60 * 30  # reset links work for 30 minutes
