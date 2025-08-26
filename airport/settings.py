from pathlib import Path
import os
import dj_database_url  # 👈 make sure this is installed: pip install dj-database-url

BASE_DIR = Path(__file__).resolve().parent.parent

# 🔐 Use env variable for production, fallback for local dev
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-insecure-replace-me')

# ⚠️ Turn this OFF in production
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

# Allow all for now (you can restrict later)
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'bookings',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'airport.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'airport.wsgi.application'

# ==============================
# DATABASE CONFIGURATION
# ==============================

# Default: SQLite (for local development)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Use Render PostgreSQL if available
DATABASE_INTERNAL_URL = os.getenv("DATABASE_INTERNAL_URL")
DATABASE_EXTERNAL_URL = os.getenv("DATABASE_EXTERNAL_URL")
DATABASE_URL = DATABASE_INTERNAL_URL or DATABASE_EXTERNAL_URL

if DATABASE_URL:
    DATABASES['default'] = dj_database_url.config(
        default=DATABASE_URL,
        conn_max_age=600,   # persistent connections
        ssl_require=True    # Render PostgreSQL requires SSL
    )


# ==============================
# LOCALIZATION
# ==============================
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

# ==============================
# STATIC FILES
# ==============================
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'   # for production collectstatic

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
