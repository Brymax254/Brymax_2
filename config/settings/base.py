"""
Django base settings for GoodMan Safari Pro project.
"""

import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv
load_dotenv()
# ----------------------------------------
# 🔧 Project Structure
# ----------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ----------------------------------------
# 🔐 Security
# ----------------------------------------
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-*dummy-key-for-dev*')
DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    'brymax-2.onrender.com',
    'www.brymax-2.onrender.com'
]

# ----------------------------------------
# 📦 Installed Applications
# ----------------------------------------
INSTALLED_APPS = [
    'whitenoise.runserver_nostatic',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Local apps
    'apps.core',
    'apps.client',
    'apps.driver',
    'apps.payments',
    'apps.notifications',
    'apps.adminpanel',
]

# ----------------------------------------
# ⚙️ Middleware
# ----------------------------------------
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ----------------------------------------
# 🔗 URL Configuration
# ----------------------------------------
ROOT_URLCONF = 'config.urls'

# ----------------------------------------
# 🧠 Templates
# ----------------------------------------
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

# ----------------------------------------
# 🔌 WSGI Application
# ----------------------------------------
WSGI_APPLICATION = 'config.wsgi.application'

# ----------------------------------------
# 🗄️ Database (Always use PostgreSQL via Render)
# ----------------------------------------
DATABASES = {
    'default': dj_database_url.config(
        conn_max_age=600,
        conn_health_checks=True,
        ssl_require=True
    )
}

# ----------------------------------------
# 🌍 Localization
# ----------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

# ----------------------------------------
# 📂 Static Files
# ----------------------------------------
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ----------------------------------------
# 📁 Media Files
# ----------------------------------------
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ----------------------------------------
# 🔐 Authentication Redirects
# ----------------------------------------
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# ----------------------------------------
# 🆔 Default Auto Field
# ----------------------------------------
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ----------------------------------------
# 🪵 Logging
# ----------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module} - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose'
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
}

# ----------------------------------------
# 🔐 Security for HTTPS on Render
# ----------------------------------------
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
CSRF_TRUSTED_ORIGINS = ['https://brymax-2.onrender.com']

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]
