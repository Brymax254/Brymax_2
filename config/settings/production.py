"""
Production specific settings for GoodMan Safari Pro
"""

from .base import *
import dj_database_url

# Security settings
DEBUG = False
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True

# Allowed hosts (update with production domain)
ALLOWED_HOSTS = ['brymax-2.onrender.com', 'www.brymax-2.onrender.com']

# Database (configure your production DB)
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'mydatabase',
#         'USER': 'mydatabaseuser',
#         'PASSWORD': 'mypassword',
#         'HOST': 'localhost',
#         'PORT': '5432',
#     }
# }
DATABASES = {
    'default': dj_database_url.config(conn_max_age=600, ssl_require=True)
}
# Static files in production
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
