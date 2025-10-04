# =============================================================================
# URLS – Project Level (airport/urls.py)
# =============================================================================
from django.contrib import admin
from django.urls import path, include
from bookings import views as bookings_views

urlpatterns = [
    # ===============================
    # 🛠️ Custom Admin Dashboard
    # ===============================
    path("brymax-admin/", bookings_views.modern_admin_dashboard, name="modern_admin_dashboard"),

    # ===============================
    # ⚙️ Default Django Admin
    # ===============================
    path("admin/", admin.site.urls),

    # ===============================
    # 📦 App Routes
    # ===============================
    path("", include(("bookings.urls", "bookings"), namespace="bookings")),  # Bookings app
    path("api/", include(("api.urls", "api"), namespace="api")),             # API app
]
