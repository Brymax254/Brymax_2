# settings.py
from pathlib import Path
import os
import dj_database_url  # pip install dj-database-url
from dotenv import load_dotenv  # pip install python-dotenv
from decouple import config
import cloudinary
from airport.utils import normalize_phone_number

# ==============================
# BASE DIRECTORY & ENV LOADING
# ==============================
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # Load .env for local dev
LOGIN_URL = "bookings:driver_login"   # redirect for @login_required
LOGOUT_REDIRECT_URL = "bookings:home"

# ==============================
# SECURITY
# ==============================
SECRET_KEY = config("DJANGO_SECRET_KEY", default="dev-insecure-replace-me")
DEBUG = config("DJANGO_DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="*").split(",")

# ==============================
# APPLICATIONS
# ==============================
INSTALLED_APPS = [
    # Django default apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_extensions",

    # Project apps
    "bookings",
    "payments",
    "rest_framework",

    # Third-party apps
    "cloudinary",
    "cloudinary_storage",
    "admin_tools",
    "admin_tools.dashboard",
    "admin_tools.theming",
    "admin_tools.menu",
    "plotly",
]

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.getenv("CLOUDINARY_CLOUD_NAME"),
    "API_KEY": os.getenv("CLOUDINARY_API_KEY"),
    "API_SECRET": os.getenv("CLOUDINARY_API_SECRET"),
}
#DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"

# ==============================
# MIDDLEWARE
# ==============================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "airport.urls"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ==============================
# TEMPLATES
# ==============================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": False,  # Must be False when custom loaders are used
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
            "loaders": [
                "admin_tools.template_loaders.Loader",  # Required by django-admin-tools
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ],
        },
    },
]

WSGI_APPLICATION = "airport.wsgi.application"

# ==============================
# DATABASE CONFIGURATION
# ==============================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DATABASE_URL = config("DATABASE_URL", default=None)
if DATABASE_URL:
    # Respect sslmode from .env, don’t force ssl_require=True
    DATABASES["default"] = dj_database_url.config(
        default=DATABASE_URL,
        conn_max_age=600,
    )

# ==============================
# LOCALIZATION
# ==============================
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# ==============================
# STATIC & MEDIA FILES
# ==============================
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ==============================
# PAYSTACK PAYMENT CONFIGURATION
# ==============================
PAYSTACK_SECRET_KEY = config("PAYSTACK_SECRET_KEY")
PAYSTACK_PUBLIC_KEY = config("PAYSTACK_PUBLIC_KEY")

PAYSTACK_BASE_URL = config("PAYSTACK_BASE_URL", default="https://api.paystack.co")
USE_PAYSTACK_SANDBOX = config("USE_PAYSTACK_SANDBOX", default=False, cast=bool)
if USE_PAYSTACK_SANDBOX:
    PAYSTACK_BASE_URL = config("PAYSTACK_SANDBOX_BASE_URL", default="https://api.paystack.co")

PAYSTACK_PAYMENT_URL = f"{PAYSTACK_BASE_URL}/transaction/initialize"
PAYSTACK_VERIFICATION_URL = f"{PAYSTACK_BASE_URL}/transaction/verify/"

SITE_URL = config("SITE_URL", default="https://brymax.xyz")
PAYSTACK_CALLBACK_URL = f"{SITE_URL}/paystack/callback/"
PAYSTACK_WEBHOOK_URL = f"{SITE_URL}/paystack/webhook/"

# ==============================
# CLOUDINARY CONFIGURATION
# ==============================
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

# ==============================
# EMAIL CONFIGURATION
# ==============================
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "francisbrymax@gmail.com"
EMAIL_HOST_PASSWORD = "btlydfhstlbdsguz"  # App password, no spaces
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER)
ADMIN_EMAIL = config("ADMIN_EMAIL", default=EMAIL_HOST_USER)

# ==============================
# ADMIN TOOLS CONFIGURATION
# ==============================
ADMIN_TOOLS_MENU = "airport.dashboard.CustomMenu"
ADMIN_TOOLS_INDEX_DASHBOARD = "airport.dashboard.CustomIndexDashboard"
ADMIN_TOOLS_APP_INDEX_DASHBOARD = "admin_tools.dashboard.apps.DefaultAppIndexDashboard"

# ==============================
# LOGGING
# ==============================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "file": {
            "level": "ERROR",
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "django_errors.log",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["file"],
            "level": "ERROR",
            "propagate": True,
        },
    },
}

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20
}

# ==============================
# PAYSTACK CONFIG DICT (Optional)
# ==============================
PAYSTACK = {
    "SECRET_KEY": PAYSTACK_SECRET_KEY,
    "PUBLIC_KEY": PAYSTACK_PUBLIC_KEY,
    "CALLBACK_URL": PAYSTACK_CALLBACK_URL,
    "WEBHOOK_URL": PAYSTACK_WEBHOOK_URL,
}
