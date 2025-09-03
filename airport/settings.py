from pathlib import Path
import os
import dj_database_url  # pip install dj-database-url
from dotenv import load_dotenv  # pip install python-dotenv

# ==============================
# BASE DIRECTORY & ENV LOADING
# ==============================
BASE_DIR = Path(__file__).resolve().parent.parent

# ✅ Load environment variables from .env (for local dev)
load_dotenv(BASE_DIR / ".env")

# ==============================
# SECURITY
# ==============================
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-replace-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "airport.urls"

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

DATABASE_URL = os.getenv("DATABASE_URL")
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
# PAYMENT CONFIGURATION
# ==============================
# PesaPal
PESAPAL_CONSUMER_KEY = os.getenv("PESAPAL_CONSUMER_KEY", "RHz/TtTm7+4Z6nWjldFb5RwUT4rSD5QL")
PESAPAL_CONSUMER_SECRET = os.getenv("PESAPAL_CONSUMER_SECRET", "lRRpdgumXxNRb58GhIvK8z9KTWA=")
PESAPAL_DEMO = os.getenv("PESAPAL_DEMO", "True") == "True"

# Your callback endpoint
PESAPAL_CALLBACK_URL = "https://www.brymax.xyz/payments/callback/"

# The Notification ID from Pesapal dashboard (UUID, NOT a URL)
PESAPAL_NOTIFICATION_ID = os.getenv("PESAPAL_NOTIFICATION_ID", "123e4567-e89b-12d3-a456-426614174000")


# M-Pesa
MPESA_ENV = os.getenv("MPESA_ENV", "sandbox")  # sandbox or production
MPESA_CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY", "your_consumer_key")
MPESA_CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET", "your_consumer_secret")
MPESA_PASSKEY = os.getenv("MPESA_PASSKEY", "your_lipa_na_mpesa_online_passkey")
MPESA_SHORTCODE = os.getenv("MPESA_SHORTCODE", "174379")  # test shortcode

# Site URL for callbacks
SITE_URL = os.getenv("SITE_URL", "https://yourdomain.com")
