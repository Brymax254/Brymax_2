"""
Production specific settings for GoodMan Safari Pro
"""

from .base import *
import dj_database_url
import os

# ----------------------------------------
# 🔐 Security Settings
# ----------------------------------------
DEBUG = False
ALLOWED_HOSTS = [
'brymax.xyz',
    'www.brymax.xyz',
    'brymax-2.onrender.com',
    'www.brymax-2.onrender.com'
]
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
CSRF_TRUSTED_ORIGINS = ['https://brymax-2.onrender.com']

# ----------------------------------------
# 🗄️ PostgreSQL Database for Render
# ----------------------------------------
DATABASES = {
    'default': dj_database_url.config(
        conn_max_age=600,
        conn_health_checks=True,
        ssl_require=True
    )
}

# ----------------------------------------
# 📂 Static & Media Files
# ----------------------------------------
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

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
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
}
