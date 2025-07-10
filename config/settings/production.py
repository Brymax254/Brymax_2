"""
Production specific settings for GoodMan Safari Pro
"""

from .base import *

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

# Static files in production
STATIC_ROOT = '/var/www/goodman-safari/static'
MEDIA_ROOT = '/var/www/goodman-safari/media'
