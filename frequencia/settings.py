"""
Django settings for frequencia project.
Gerado pelo Django 5.1.x — ajustado para app 'controle' e Cloudinary opcional.
"""

from pathlib import Path
import os

# --- .env (carregar depois de BASE_DIR estar definido) ---
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# =========================
# Paths base
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")

# =========================
# Segurança / Debug
# =========================
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-c_78s=ywgjr_)vnhrtnjxak60lc6p-21&ts!vqnvru0*_9m#0j"  # troque em produção
)
DEBUG = os.getenv("DEBUG", "1") == "1"

ALLOWED_HOSTS = (
    os.getenv("ALLOWED_HOSTS", "").split(",") if os.getenv("ALLOWED_HOSTS") else []
)
CSRF_TRUSTED_ORIGINS = (
    os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if os.getenv("CSRF_TRUSTED_ORIGINS") else []
)

# =========================
# Apps
# =========================
# Base de apps do Django (sem Cloudinary)
BASE_DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

# Seu app
LOCAL_APPS = [
    "controle.apps.ControleConfig",
]

# Tentativa de carregar Cloudinary (opcional)
CLOUDINARY_AVAILABLE = False
try:
    import cloudinary  # noqa: F401
    import cloudinary_storage  # noqa: F401
    CLOUDINARY_AVAILABLE = True
except Exception:
    CLOUDINARY_AVAILABLE = False

# Monta INSTALLED_APPS com a ordem recomendada:
# cloudinary_storage deve vir ANTES de staticfiles; cloudinary pode vir depois.
if CLOUDINARY_AVAILABLE:
    INSTALLED_APPS = ["cloudinary_storage"] + BASE_DJANGO_APPS + ["cloudinary"] + LOCAL_APPS
else:
    INSTALLED_APPS = BASE_DJANGO_APPS + LOCAL_APPS

# =========================
# Middleware
# =========================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
        # Além das templates do app (APP_DIRS=True), também olha a pasta /templates do projeto
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

# =========================
# Banco de Dados (SQLite por padrão)
# =========================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# =========================
# Senhas
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =========================
# i18n / timezone (BR)
# =========================
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Fortaleza"  # ou "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# =========================
# Arquivos estáticos e mídia
# =========================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # para collectstatic em prod
STATIC_DIR = BASE_DIR / "static"
STATICFILES_DIRS = [STATIC_DIR] if STATIC_DIR.exists() else []

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"  # fallback/local

# ----- Cloudinary (opcional) -----
# Preferencialmente via variável única:
# CLOUDINARY_URL=cloudinary://<API_KEY>:<API_SECRET>@<CLOUD_NAME>
CLOUDINARY_URL_ENV = os.getenv("CLOUDINARY_URL")

# Ou pelas 3 variáveis separadas:
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

USE_CLOUDINARY = (
    CLOUDINARY_AVAILABLE and (
        bool(CLOUDINARY_URL_ENV) or
        all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET])
    )
)

if USE_CLOUDINARY:
    # Se NÃO usar a URL única, passa as chaves via dict
    if not CLOUDINARY_URL_ENV:
        CLOUDINARY_STORAGE = {
            "CLOUD_NAME": CLOUDINARY_CLOUD_NAME,
            "API_KEY": CLOUDINARY_API_KEY,
            "API_SECRET": CLOUDINARY_API_SECRET,
        }
    # Django 5+: STORAGES
    STORAGES = {
        "default": {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
else:
    # Fallback local (sem Cloudinary)
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

# =========================
# Auth / Login
# =========================
# Pode ser caminho absoluto (ex.: "/login/") ou nome de URL (ex.: "controle:login")
LOGIN_URL = os.getenv("LOGIN_URL", "controle:login")
LOGIN_REDIRECT_URL = os.getenv("LOGIN_REDIRECT_URL", "controle:painel_controle")
LOGOUT_REDIRECT_URL = os.getenv("LOGOUT_REDIRECT_URL", "controle:login")

# =========================
# Outras opções úteis
# =========================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# E-mails (console no dev)
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")

# Em urls.py do projeto, para servir mídia no dev (quando DEBUG):
# from django.conf import settings
# from django.conf.urls.static import static
# if settings.DEBUG:
#     urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
