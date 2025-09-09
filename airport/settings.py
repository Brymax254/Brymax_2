from pathlib import Path
import os
import dj_database_url  # pip install dj-database-url
from dotenv import load_dotenv  # pip install python-dotenv
from decouple import config

# ==============================
# BASE DIRECTORY & ENV LOADING
# ==============================
BASE_DIR = Path(__file__).resolve().parent.parent

# ✅ Load environment variables from .env (for local dev)
load_dotenv(BASE_DIR / ".env")

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

    # Project apps
    "bookings",
    "payments",
]

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
    DATABASES["default"] = dj_database_url.config(
        default=DATABASE_URL,
        conn_max_age=600,
        ssl_require=True,
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
# PESAPAL PAYMENT CONFIGURATION
# ==============================
PESAPAL_CONSUMER_KEY = config("PESAPAL_CONSUMER_KEY", default="")
PESAPAL_CONSUMER_SECRET = config("PESAPAL_CONSUMER_SECRET", default="")
PESAPAL_DEMO = config("PESAPAL_DEMO", default=True, cast=bool)
PESAPAL_IPN_URL = config("PESAPAL_IPN_URL", default="")

# Use correct base URL depending on environment
if PESAPAL_DEMO:
    PESAPAL_BASE_URL = "https://cybqa.pesapal.com/v3"
else:
    PESAPAL_BASE_URL = "https://pay.pesapal.com/v3"


# Your callback + IPN endpoints
SITE_URL = config("SITE_URL", default="https://brymax.xyz")
PESAPAL_CALLBACK_URL = f"{SITE_URL}/payments/callback/"
PESAPAL_NOTIFICATION_ID = config(
    "PESAPAL_NOTIFICATION_ID",
    default="123e4567-e89b-12d3-a456-426614174000"
)

# ==============================
# M-PESA CONFIGURATION
# ==============================
MPESA_ENV = config("MPESA_ENV", default="sandbox")  # sandbox or production
MPESA_CONSUMER_KEY = config("MPESA_CONSUMER_KEY", default="your_consumer_key")
MPESA_CONSUMER_SECRET = config("MPESA_CONSUMER_SECRET", default="your_consumer_secret")
MPESA_PASSKEY = config("MPESA_PASSKEY", default="your_lipa_na_mpesa_online_passkey")
MPESA_SHORTCODE = config("MPESA_SHORTCODE", default="174379")  # test shortcode