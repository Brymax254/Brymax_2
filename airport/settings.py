from pathlib import Path
import os
import dj_database_url  # pip install dj-database-url
from dotenv import load_dotenv  # pip install python-dotenv
from decouple import config
from airport.utils import normalize_phone_number

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
    'django.contrib.humanize',
    "django_extensions",

    # Project apps
    "bookings",
    "payments",
    'cloudinary',
    'cloudinary_storage',
    'admin_tools',
    'admin_tools.dashboard',
    'admin_tools.theming',
    'admin_tools.menu',
    'plotly',
]

CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.getenv('CLOUDINARY_CLOUD_NAME'),
    'API_KEY': os.getenv('CLOUDINARY_API_KEY'),
    'API_SECRET': os.getenv('CLOUDINARY_API_SECRET'),
}

DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

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
        "DIRS": [BASE_DIR / "templates"],  # Keep your Pathlib link
        "APP_DIRS": False,  # Must be False when loaders are defined
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
            "loaders": [
                "admin_tools.template_loaders.Loader",  # Required for django-admin-tools
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
# Required credentials - no defaults to ensure they are explicitly set
PESAPAL_CONSUMER_KEY = config("PESAPAL_CONSUMER_KEY")
PESAPAL_CONSUMER_SECRET = config("PESAPAL_CONSUMER_SECRET")
PESAPAL_NOTIFICATION_ID = config("PESAPAL_NOTIFICATION_ID")

# Production (live) PesaPal v3 API
PESAPAL_BASE_URL = config(
    "PESAPAL_BASE_URL",
    default="https://pay.pesapal.com/v3"
)

# (Optional) you can also expose a SANDBOX flag and switch dynamically:
USE_PESAPAL_SANDBOX = config("USE_PESAPAL_SANDBOX", default=False, cast=bool)
if USE_PESAPAL_SANDBOX:
    PESAPAL_BASE_URL = config(
        "PESAPAL_SANDBOX_BASE_URL",
        default="https://cybqa.pesapal.com/pesapalv3"
    )
# Force live mode - no demo mode option
PESAPAL_DEMO = False

# API endpoints
PESAPAL_PAYMENT_URL = f"{PESAPAL_BASE_URL}/Transactions/SubmitOrderRequest"
PESAPAL_TOKEN_URL = f"{PESAPAL_BASE_URL}/auth/RequestToken"

# ============================
# 🌍 Site + Pesapal Integration
# ============================
# Must be HTTPS for production
SITE_URL = config("SITE_URL", default="https://brymax.xyz")

# Callback URL (where Pesapal redirects browser after payment)
PESAPAL_CALLBACK_URL = f"{SITE_URL}/payments/callback/"

# IPN URL (where Pesapal sends payment status notifications)
PESAPAL_IPN_URL = config("PESAPAL_IPN_URL", default=f"{SITE_URL}/payments/ipn/")

# Where the user is redirected after payment (user-facing receipt page)
PESAPAL_RETURN_URL = f"{SITE_URL}/payments/return/"

# ==============================
# M-PESA CONFIGURATION
# ==============================
MPESA_ENV = config("MPESA_ENV", default="sandbox")  # sandbox or production
MPESA_CONSUMER_KEY = config("MPESA_CONSUMER_KEY", default="your_consumer_key")
MPESA_CONSUMER_SECRET = config("MPESA_CONSUMER_SECRET", default="your_consumer_secret")
MPESA_PASSKEY = config("MPESA_PASSKEY", default="your_lipa_na_mpesa_online_passkey")
MPESA_SHORTCODE = config("MPESA_SHORTCODE", default="174379")  # test shortcode

# ==============================
# CLOUDINARY CONFIGURATION
# ==============================
import cloudinary

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

# ==============================
# EMAIL CONFIGURATION
# ==============================
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "francisbrymax@gmail.com"
EMAIL_HOST_PASSWORD = "btlydfhstlbdsguz"  # Remove spaces
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# ==============================
# ADMIN TOOLS CONFIGURATION
# ==============================
ADMIN_TOOLS_MENU = 'airport.dashboard.CustomMenu'
ADMIN_TOOLS_INDEX_DASHBOARD = 'airport.dashboard.CustomIndexDashboard'
ADMIN_TOOLS_APP_INDEX_DASHBOARD = 'admin_tools.dashboard.apps.DefaultAppIndexDashboard'

# Email settings
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="francisbrymax@gmail.com")
ADMIN_EMAIL = config("ADMIN_EMAIL", default="francisbrymax@gmail.com")


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'django_errors.log',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'ERROR',
            'propagate': True,
        },
    },
}