"""Django settings for the mid-demo backend workspace."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-before-deploy")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if host.strip()
]
REDIS_URL = os.environ.get("REDIS_URL")
DJANGO_DATABASE_ENGINE = os.environ.get("DJANGO_DATABASE_ENGINE", "sqlite").lower()
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "change-me")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "law_db")
PROGRESS_CACHE_TTL_SECONDS = _positive_int_env("PROGRESS_CACHE_TTL_SECONDS", 300)
AGENT_WORKER_STALE_AFTER_SECONDS = _positive_int_env("AGENT_WORKER_STALE_AFTER_SECONDS", 900)
AGENT_WORKER_RETRY_BACKOFF_SECONDS = _positive_int_env("AGENT_WORKER_RETRY_BACKOFF_SECONDS", 60)
AGENT_WORKER_RETRY_BACKOFF_MAX_SECONDS = _positive_int_env("AGENT_WORKER_RETRY_BACKOFF_MAX_SECONDS", 900)
AGENT_WORKER_LOOP_SLEEP_SECONDS = _positive_int_env("AGENT_WORKER_LOOP_SLEEP_SECONDS", 5)
OBJECT_STORAGE_PROVIDER = os.environ.get("OBJECT_STORAGE_PROVIDER", "mock_s3")
OBJECT_STORAGE_BUCKET = os.environ.get("OBJECT_STORAGE_BUCKET", "skn27-demo-object-storage")
OBJECT_STORAGE_PREFIX = os.environ.get("OBJECT_STORAGE_PREFIX", "canonical")
OBJECT_STORAGE_SIGNED_URL_TTL_SECONDS = _positive_int_env("OBJECT_STORAGE_SIGNED_URL_TTL_SECONDS", 900)
OBJECT_STORAGE_LOCAL_ROOT = os.environ.get("OBJECT_STORAGE_LOCAL_ROOT", "backend/media/mock_object_storage")
OBJECT_STORAGE_ENDPOINT_URL = os.environ.get("OBJECT_STORAGE_ENDPOINT_URL", "")
OBJECT_STORAGE_REGION = os.environ.get("OBJECT_STORAGE_REGION", os.environ.get("AWS_DEFAULT_REGION", ""))
OBJECT_STORAGE_ACCESS_KEY_ID = os.environ.get("OBJECT_STORAGE_ACCESS_KEY_ID", os.environ.get("AWS_ACCESS_KEY_ID", ""))
OBJECT_STORAGE_SECRET_ACCESS_KEY = os.environ.get(
    "OBJECT_STORAGE_SECRET_ACCESS_KEY",
    os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
)
OBJECT_STORAGE_SESSION_TOKEN = os.environ.get("OBJECT_STORAGE_SESSION_TOKEN", os.environ.get("AWS_SESSION_TOKEN", ""))
FILE_SCAN_MAX_BYTES = _positive_int_env("FILE_SCAN_MAX_BYTES", 50 * 1024 * 1024)
FILE_SCAN_REJECT_PII = os.environ.get("FILE_SCAN_REJECT_PII", "0") == "1"
FILE_SCAN_PROVIDER = os.environ.get("FILE_SCAN_PROVIDER", "local_policy")
FILE_SCAN_CLAMAV_HOST = os.environ.get("FILE_SCAN_CLAMAV_HOST", "")
FILE_SCAN_CLAMAV_PORT = _positive_int_env("FILE_SCAN_CLAMAV_PORT", 3310)
FILE_SCAN_EXTERNAL_URL = os.environ.get("FILE_SCAN_EXTERNAL_URL", "")
FILE_SCAN_EXTERNAL_API_KEY = os.environ.get("FILE_SCAN_EXTERNAL_API_KEY", "")
FILE_SCAN_TIMEOUT_SECONDS = _positive_int_env("FILE_SCAN_TIMEOUT_SECONDS", 10)
FILE_SCAN_EXTERNAL_INLINE_MAX_BYTES = _positive_int_env("FILE_SCAN_EXTERNAL_INLINE_MAX_BYTES", 5 * 1024 * 1024)
ANONYMOUS_RETENTION_DAYS = _positive_int_env("ANONYMOUS_RETENTION_DAYS", 1)
GUEST_RETENTION_DAYS = _positive_int_env("GUEST_RETENTION_DAYS", 7)
USER_RETENTION_DAYS = _positive_int_env("USER_RETENTION_DAYS", 365)
RAW_MEDIA_RETENTION_DAYS = _positive_int_env("RAW_MEDIA_RETENTION_DAYS", 30)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_POPUP_REDIRECT_URI = os.environ.get("GOOGLE_POPUP_REDIRECT_URI", "")
GOOGLE_TOKEN_ENDPOINT = os.environ.get("GOOGLE_TOKEN_ENDPOINT", "https://oauth2.googleapis.com/token")
GOOGLE_USERINFO_ENDPOINT = os.environ.get(
    "GOOGLE_USERINFO_ENDPOINT",
    "https://openidconnect.googleapis.com/v1/userinfo",
)
APP_JWT_SECRET = os.environ.get("APP_JWT_SECRET", SECRET_KEY)
OAUTH_TOKEN_SECRET = os.environ.get("OAUTH_TOKEN_SECRET", APP_JWT_SECRET)
SUPERVISOR_LLM_ENABLED = os.environ.get("SUPERVISOR_LLM_ENABLED", "0") == "1"
SUPERVISOR_LLM_PROVIDER = os.environ.get("SUPERVISOR_LLM_PROVIDER", "openai")
SUPERVISOR_LLM_MODEL = os.environ.get("SUPERVISOR_LLM_MODEL", "gpt-5.4-mini")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SUPERVISOR_LLM_API_KEY = os.environ.get("SUPERVISOR_LLM_API_KEY") or OPENAI_API_KEY
SUPERVISOR_LLM_BASE_URL = os.environ.get("SUPERVISOR_LLM_BASE_URL", "")
SUPERVISOR_LLM_TEMPERATURE = os.environ.get("SUPERVISOR_LLM_TEMPERATURE", "0.1")
SUPERVISOR_LLM_TIMEOUT_SECONDS = os.environ.get("SUPERVISOR_LLM_TIMEOUT_SECONDS", "12")
LEGAL_RAG_VECTOR_ENABLED = os.environ.get("LEGAL_RAG_VECTOR_ENABLED", "0") == "1"
LEGAL_RAG_QUERY_EMBEDDING_PROVIDER = os.environ.get(
    "LEGAL_RAG_QUERY_EMBEDDING_PROVIDER",
    "sentence-transformers",
)
LEGAL_RAG_QUERY_EMBEDDING_MODEL = os.environ.get(
    "LEGAL_RAG_QUERY_EMBEDDING_MODEL",
    "intfloat/multilingual-e5-large",
)
LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS = os.environ.get("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", "1024")
LEGAL_RAG_QUERY_EMBEDDING_DEVICE = os.environ.get("LEGAL_RAG_QUERY_EMBEDDING_DEVICE", "cpu")
LEGAL_RAG_QUERY_EMBEDDING_TIMEOUT_SECONDS = os.environ.get("LEGAL_RAG_QUERY_EMBEDDING_TIMEOUT_SECONDS", "12")
LEGAL_RAG_EMBEDDING_PROVIDER_FILTER = os.environ.get("LEGAL_RAG_EMBEDDING_PROVIDER_FILTER", "")
LEGAL_RAG_OPENAI_API_KEY = os.environ.get("LEGAL_RAG_OPENAI_API_KEY") or OPENAI_API_KEY

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "chatbot",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "config.middleware.SameOriginCorsMiddleware",
    "config.middleware.JwtAuthMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 31_536_000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "0" if DEBUG else "1") == "1"

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if DJANGO_DATABASE_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": POSTGRES_HOST,
            "PORT": POSTGRES_PORT,
            "USER": POSTGRES_USER,
            "PASSWORD": POSTGRES_PASSWORD,
            "NAME": POSTGRES_DB,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "skn27-progress-cache",
        }
    }

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

