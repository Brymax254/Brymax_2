from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from bookings import views as bookings_views

urlpatterns = [
    # -------------------------------------------------------------------------
    # 🛠 Custom Admin Dashboard
    # -------------------------------------------------------------------------
    path(
        "brymax-admin/",
        bookings_views.modern_admin_dashboard,
        name="modern_admin_dashboard",
    ),

    # -------------------------------------------------------------------------
    # ⚙️ Default Django Admin
    # -------------------------------------------------------------------------
    path("admin/", admin.site.urls),

    # -------------------------------------------------------------------------
    # 🌍 Bookings App Frontend Pages
    # -------------------------------------------------------------------------
    path(
        "",
        include(("bookings.urls", "bookings"), namespace="bookings"),
    ),

    # -------------------------------------------------------------------------
    # 🔌 API ENDPOINTS (DRF Router)
    # -------------------------------------------------------------------------
    path(
        "api/",
        include("bookings.api.urls"),  # include router URLs only
    ),
]

# -------------------------------------------------------------------------
# 📦 Static & Media Files
# -------------------------------------------------------------------------
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
