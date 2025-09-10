# ================================================
# urls.py
# Organized URL configuration for Tours & Payments
# ================================================

from django.urls import path
from . import views

urlpatterns = [
    # ===============================
    # 🌍 Public Pages
    # ===============================
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("terms/", views.terms, name="terms"),

    # Tours & Bookings
    path("book-online/", views.book_online, name="book_online"),
    path("nairobi-airport-transfers-and-taxis/", views.nairobi_transfers, name="nairobi_transfers"),
    path("book/excursions/", views.excursions, name="excursions"),
    path("tours-and-safaris/", views.tours, name="tours"),

    # ===============================
    # 💳 Payments (Mpesa + Pesapal + Tours)
    # ===============================
    # Tour Payments
    path("book-tour/<int:tour_id>/", views.tour_payment, name="tour_payment"),
    path("payments/tour/<int:tour_id>/pay/", views.tour_payment, name="tour_payment_page"),  # alias
    path("payments/tour/<int:tour_id>/mpesa/", views.mpesa_payment, name="mpesa_payment"),

    # Payment Result Pages
    path("payments/success/", views.payment_success, name="payment_success"),
    path("payments/failed/", views.payment_failed, name="payment_failed"),

    # ===============================
    # 🔗 Pesapal Integration
    # ===============================
    path("pesapal/create-order/", views.create_pesapal_order, name="create_pesapal_order"),
    path("pesapal/callback/", views.pesapal_callback, name="pesapal_callback"),
    path("pesapal/ipn/", views.pesapal_ipn, name="pesapal_ipn"),
    path("pesapal/test-auth/", views.test_pesapal_auth, name="test_pesapal_auth"),

    # ===============================
    # 👤 Guest Checkout (Non-logged-in Users)
    # ===============================
    path("guest/checkout/<int:tour_id>/", views.guest_checkout_page, name="guest_checkout"),
    path("guest/process-info/", views.process_guest_info, name="process_guest_info"),
    path("guest/create-order/", views.create_guest_pesapal_order, name="create_guest_pesapal_order"),
    path("guest/callback/", views.guest_pesapal_callback, name="guest_pesapal_callback"),
    path("guest/success/", views.guest_payment_success, name="guest_payment_success"),
    path("guest/failed/", views.guest_payment_failed, name="guest_payment_failed"),

    # ===============================
    # 🚖 Driver Authentication & Dashboard
    # ===============================
    path("driver/login/", views.driver_login, name="driver_login"),
    path("driver/dashboard/", views.driver_dashboard, name="driver_dashboard"),

    # Driver Actions (Tour Management)
    path("driver/add-tour/", views.add_tour, name="add_tour"),
    path("driver/tour/<int:tour_id>/edit/", views.edit_tour, name="edit_tour"),
    path("driver/tour/<int:tour_id>/delete/", views.delete_tour, name="delete_tour"),
]
