# airport/urls.py
from django.contrib import admin
from django.urls import path, include
from bookings import views as bookings_views

urlpatterns = [
    # 1️⃣ Modern admin dashboard
    path('brymax-admin/', bookings_views.modern_admin_dashboard, name='modern_admin_dashboard'),

    # 2️⃣ Default Django admin
    path('admin/', admin.site.urls),

    # 3️⃣ Include app URLs
    path('', include('bookings.urls')),
]
