# =============================================================================
# URLS – Bookings App
# =============================================================================
from django.urls import path, re_path, include
from rest_framework.routers import DefaultRouter
from . import views
from .api import views as api_views  # Import API views

app_name = "bookings"

# Create a router for API endpoints
router = DefaultRouter()
router.register(r'tours', api_views.TourViewSet, basename='tour')
router.register(r'bookings', api_views.BookingViewSet, basename='booking')
router.register(r'payments', api_views.PaymentViewSet, basename='payment')
router.register(r'trips', api_views.TripViewSet, basename='trip')
router.register(r'booking-customers', api_views.BookingCustomerViewSet, basename='bookingcustomer')
router.register(r'drivers', api_views.DriverViewSet, basename='driver')
router.register(r'vehicles', api_views.VehicleViewSet, basename='vehicle')

urlpatterns = [
    # ===============================
    # 🌍 Public Pages
    # ===============================
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("terms/", views.terms, name="terms"),

    # ===============================
    # 🚌 Tours & Bookings
    # ===============================
    path("book-online/", views.book_online, name="book_online"),
    path("airport-transfers/", views.nairobi_transfers, name="airport_transfers"),
    path("excursions/", views.excursions, name="excursions"),
    path("tours-and-safaris/", views.tours, name="tours"),
    path("tour/<slug:tour_slug>/", views.TourDetailView.as_view(), name="tour_detail"),
    path("nairobi-airport-transfers-and-taxis/", views.nairobi_airport_transfers, name="nairobi_airport_transfers"),

    # ===============================
    # 💳 Tour Payments (Paystack)
    # ===============================
    path("tour/<int:tour_id>/pay/", views.tour_payment, name="tour_payment"),
    path("book-tour/<int:tour_id>/", views.tour_payment, name="tour_payment_legacy"),
    path("payments/tour/<int:tour_id>/", views.tour_payment, name="tour_payment_alt"),

    # ===============================
    # 📋 Payment Result Pages
    # ===============================
    path("payments/success/<uuid:pk>/", views.payment_success_detail, name="payment_success_detail"),
    path("payments/success/", views.payment_success, name="payment_success"),
    path("payments/pending/", views.payment_pending, name="payment_pending"),
    path("payments/failed/", views.payment_failed, name="payment_failed"),
    path("payments/retry/<uuid:payment_id>/", views.retry_payment, name="retry_payment"),

    # ===============================
    # 🔗 Paystack Integration
    # ===============================
    path("payments/create-guest-order/", views.create_guest_paystack_order, name="create_guest_paystack_order"),
    path("payments/callback/", views.paystack_callback, name="paystack_callback"),
    path("payments/webhook/", views.paystack_webhook, name="paystack_webhook"),
    path("paystack/callback/", views.paystack_callback, name="paystack_callback_legacy"),
    path("paystack/webhook/", views.paystack_webhook, name="paystack_webhook_legacy"),

    # ===============================
    # 👤 Guest Checkout Flow
    # ===============================
    path("guest/checkout/<int:tour_id>/", views.guest_checkout, name="guest_checkout"),
    path("guest/process-info/", views.process_guest_info, name="process_guest_info"),
    path("guest/payment/<uuid:payment_id>/", views.guest_payment_page, name="guest_payment_page"),

    # ===============================
    # 🚖 Driver Authentication & Dashboard
    # ===============================
    path("driver/login/", views.driver_login, name="driver_login"),
    path("driver/logout/", views.driver_logout, name="driver_logout"),
    path("driver/dashboard/", views.driver_dashboard, name="driver_dashboard"),
    path("driver/tour/add/", views.create_tour, name="create_tour"),
    path("driver/tour/<int:tour_id>/edit/", views.edit_tour, name="edit_tour"),
    path("driver/tour/<int:tour_id>/delete/", views.delete_tour, name="delete_tour"),

    # ===============================
    # 🧾 Receipts
    # ===============================
    path("receipt/<uuid:pk>/", views.receipt, name="receipt"),

    # ===============================
    # 🛠️ Custom Admin Dashboard
    # ===============================
    path("brymax-admin/", views.modern_admin_dashboard, name="modern_admin_dashboard"),
    path("brymax-admin/tour-approval/", views.admin_tour_approval, name="admin_tour_approval"),
    path("brymax-admin/tour-approval/approve/<int:tour_id>/", views.approve_tour, name="approve_tour"),
    path("brymax-admin/tour-approval/reject/<int:tour_id>/", views.reject_tour, name="reject_tour"),

    # ===============================
    # 📊 API Endpoints - ALPINE.JS INTEGRATION
    # ===============================
    path("api/tour/<int:tour_id>/price/", views.tour_price_api, name="tour_price_api"),
    path("api/tour/<int:tour_id>/availability/", views.tour_availability_api, name="tour_availability_api"),
    path("api/tours/", views.tours_api, name="tours_api"),
    path("api/payment/<uuid:payment_id>/status/", views.check_payment_status, name="check_payment_status"),

    # NEW: Alpine.js API Endpoints
    path("api/dashboard/", api_views.DashboardView.as_view(), name="api_dashboard"),
    path("api/", include(router.urls)),  # Includes all API endpoints

    # ===============================
    # 📧 Contact Form
    # ===============================
    path("contact/submit/", views.contact_submit, name="contact_submit"),
    path('api/vehicles/', views.vehicles_api, name='vehicles_api'),

    # ===============================
    # 🏥 Health Check
    # ===============================
    path("health/", views.health_check, name="health_check"),
]