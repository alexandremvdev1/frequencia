"""
Django settings for frequencia project.
Gerado pelo Django 5.1+ — app 'controle' + Cloudinary opcional + WhiteNoise.
"""
from pathlib import Path
import os

# --- .env ---
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent
if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


def get_list(env_var: str, default=None):
    val = os.getenv(env_var)
    if val:
        return [item.strip() for item in val.split(",") if item.strip()]
    return default or []


# =========================
# Segurança / Debug
# =========================
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-c_78s=ywgjr_)vnhrtnjxak60lc6p-21&ts!vqnvru0*_9m#0j"  # troque em produção
)
DEBUG = os.getenv("DEBUG", "1") == "1"

ALLOWED_HOSTS = get_list("ALLOWED_HOSTS", [])
CSRF_TRUSTED_ORIGINS = get_list("CSRF_TRUSTED_ORIGINS", [])

# Suporte Render (preenche ALLOWED_HOSTS/CSRF automaticamente)
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    if RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    origin = f"https://{RENDER_EXTERNAL_HOSTNAME}"
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)


# =========================
# Cloudinary – detectar cedo para controlar INSTALLED_APPS
# =========================
CLOUDINARY_URL_ENV = os.getenv("CLOUDINARY_URL")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

CLOUDINARY_AVAILABLE = False
try:
    import cloudinary  # noqa
    import cloudinary_storage  # noqa
    CLOUDINARY_AVAILABLE = True
except Exception:
    CLOUDINARY_AVAILABLE = False

USE_CLOUDINARY = (
    CLOUDINARY_AVAILABLE and (
        bool(CLOUDINARY_URL_ENV) or
        all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET])
    )
)


# =========================
# Apps
# =========================
BASE_DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
LOCAL_APPS = ["controle.apps.ControleConfig"]

# Só inclui cloudinary* se realmente for usar (evita comando collectstatic custom)
if USE_CLOUDINARY:
    INSTALLED_APPS = ["cloudinary_storage"] + BASE_DJANGO_APPS + ["cloudinary"] + LOCAL_APPS
else:
    INSTALLED_APPS = BASE_DJANGO_APPS + LOCAL_APPS


# =========================
# Middleware
# =========================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise para servir estáticos em produção
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "frequencia.urls"


# =========================
# Templates
# =========================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "frequencia.wsgi.application"
ASGI_APPLICATION = "frequencia.asgi.application"


# =========================
# Banco de Dados
# =========================
import dj_database_url  # type: ignore

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=True,  # força TLS mesmo sem ?sslmode=require
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# =========================
# Validação de senhas
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# =========================
# i18n / timezone
# =========================
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Araguaina"  # ou "America/Fortaleza"
USE_I18N = True
USE_TZ = True


# =========================
# Estáticos / mídia
# =========================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_DIR = BASE_DIR / "static"
STATICFILES_DIRS = [STATIC_DIR] if STATIC_DIR.exists() else []

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# WhiteNoise (dev ajuda / prod eficiente)
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG
# WHITENOISE_KEEP_ONLY_HASHED_FILES = True  # opcional em prod


# =========================
# STORAGES (Django 5) + aliases legados p/ compatibilidade
# =========================
if USE_CLOUDINARY:
    STORAGES = {
        "default": {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    # Aliases legados para libs que ainda leem esses names:
    DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    # Aliases legados (evitam AttributeError em libs antigas)
    DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


# =========================
# Auth / Login
# =========================
LOGIN_URL = os.getenv("LOGIN_URL", "controle:login")
LOGIN_REDIRECT_URL = os.getenv("LOGIN_REDIRECT_URL", "controle:painel_controle")
LOGOUT_REDIRECT_URL = os.getenv("LOGOUT_REDIRECT_URL", "controle:login")


# =========================
# E-mail
# =========================
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@example.com")


# =========================
# Segurança prod
# =========================
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    X_FRAME_OPTIONS = "DENY"
    # HSTS
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))  # 1 ano
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"


# =========================
# Logging básico p/ ver nos logs do Render
# =========================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}


# =========================
# Campo id padrão
# =========================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# WhiteNoise: não falhar em referências ausentes no Manifest (hotfix)
WHITENOISE_MANIFEST_STRICT = False
