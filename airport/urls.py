# =============================================================================
# URLS – Project Level (airport/urls.py)
# =============================================================================
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
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
    path("", include(("bookings.urls", "bookings"), namespace="bookings")),
]

# ===============================
# 📸 Serve Uploaded Media in Development
# ===============================
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
