"""
Production specific settings for GoodMan Safari Pro
"""

from .base import *
import dj_database_url
import os

# Security settings
DEBUG = False
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True

# Allowed hosts (update with your actual Render domain)
ALLOWED_HOSTS = ['brymax-2.onrender.com', 'www.brymax-2.onrender.com']

# Database (uses DATABASE_URL environment variable)
DATABASES = {
    'default': dj_database_url.parse(
        "postgresql://brymax_db_y2uq_user:sq1fXECNONWPTs9bv7WosydrmfJUx5y0@dpg-d1nu1gre5dus73bbqos0-a.frankfurt-postgres.render.com/brymax_db_y2uq",
        conn_max_age=600,
        ssl_require=True
    )
}

# Static files (CSS, JavaScript, Images)
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
