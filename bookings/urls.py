# =============================================================================
# URLS
# =============================================================================
from django.urls import path
from . import views
from .views import receipt

app_name = 'bookings'  # App namespace

urlpatterns = [
    # ===============================
    # 🌍 Public Pages
    # ===============================
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("terms/", views.terms, name="terms"),

    # ===============================
    # Tours & Bookings
    # ===============================
    path("book-online/", views.book_online, name="book_online"),
    path("nairobi-airport-transfers-and-taxis/", views.nairobi_transfers, name="nairobi_transfers"),
    path("book/excursions/", views.excursions, name="excursions"),
    path("tours-and-safaris/", views.tours, name="tours"),

    # ===============================
    # 💳 Payment Initiation for Tours (Paystack)
    # ===============================
    path("book-tour/<int:tour_id>/", views.tour_payment, name="tour_payment"),
    path("payments/tour/<int:tour_id>/", views.tour_payment, name="tour_payment_base"),

    # ===============================
    # 📋 Payment Result Pages
    # ===============================
    path("payments/success/<uuid:pk>/", views.payment_success_detail, name="payment_success_detail"),
    path("payments/success/", views.payment_success_general, name="payment_success_general"),
    path("payment/pending/", views.payment_pending, name="payment_pending"),
    path("payment/failed/", views.payment_failed, name="payment_failed"),

    # ===============================
    # 🔗 Paystack Integration
    # ===============================
    path("payments/create-guest-order/", views.create_guest_paystack_order, name="create_guest_paystack_order"),
    path("payments/callback/", views.paystack_callback, name="paystack_callback"),
    path("paystack/callback/", views.paystack_callback, name="paystack_callback_legacy"),
    path("payments/webhook/", views.paystack_webhook, name="paystack_webhook"),
    path("paystack/webhook/", views.paystack_webhook, name="paystack_webhook_legacy"),

    # ===============================
    # 👤 Guest Checkout Flow
    # ===============================
    path("guest/checkout/<int:tour_id>/", views.guest_checkout, name="guest_checkout"),
    path("guest/process-info/", views.process_guest_info, name="process_guest_info"),
    path("guest/payment/<uuid:payment_id>/", views.guest_payment_page, name="guest_payment_page"),
    path("guest/payment/return/", views.guest_payment_return, name="guest_payment_return"),
    path("guest/payment/success/", views.guest_payment_success, name="guest_payment_success"),
    path("guest/payment/failed/", views.guest_payment_failed, name="guest_payment_failed"),

    # ===============================
    # 🚖 Driver Authentication & Dashboard
    # ===============================
    path("driver/login/", views.driver_login, name="driver_login"),
    path("driver/dashboard/", views.driver_dashboard, name="driver_dashboard"),
    path("driver/tour/add/", views.create_tour, name="create_tour"),
    path("driver/tour/<int:tour_id>/edit/", views.edit_tour, name="edit_tour"),
    path("driver/tour/<int:tour_id>/delete/", views.delete_tour, name="delete_tour"),

    # ===============================
    # 🧾 Receipt Page
    # ===============================
    path("receipt/<int:pk>/", receipt, name="receipt"),

    # ===============================
    # 🛠️ Custom Modern Admin Dashboard
    # ===============================
    path("brymax-admin/", views.modern_admin_dashboard, name="modern_admin_dashboard"),

    # ===============================
    # 📊 API Endpoints
    # ===============================
    path("api/tour-price/<int:tour_id>/", views.tour_price_api, name="tour_price_api"),
    path("api/tour-availability/<int:tour_id>/", views.tour_availability_api, name="tour_availability_api"),
    path("api/payment-status/<uuid:payment_id>/", views.check_payment_status, name="check_payment_status"),

    # ===============================
    # 🔁 Payment Retry
    # ===============================
    path("payment/retry/<uuid:payment_id>/", views.retry_payment, name="retry_payment"),

    # ===============================
    # 📧 Contact Form
    # ===============================
    path("contact/submit/", views.contact_submit, name="contact_submit"),

    # ===============================
    # 🏥 Health Check
    # ===============================
    path("health/", views.health_check, name="health_check"),
]
