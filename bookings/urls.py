from django.urls import path
from . import views
from .views import ReceiptView

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
    path("payments/tour/<int:tour_id>/", views.tour_payment, name="tour_payment_base"),
    path("book-tour/<int:tour_id>/", views.tour_payment, name="tour_payment"),
    path("payments/tour/<int:tour_id>/pay/", views.tour_payment, name="tour_payment_page"),
    path("payments/tour/<int:tour_id>/mpesa/", views.mpesa_payment, name="mpesa_payment"),

    # ===============================
    # Payment Result Pages
    # ===============================
    path("payments/success/", views.payment_success, name="payment_success"),
    path("payments/failed/", views.payment_failed, name="payment_failed"),

    # ===============================
    # 🔗 Pesapal Integration (with aliases to match Pesapal responses)
    # ===============================
    path("pesapal/create-order/", views.create_pesapal_order, name="create_pesapal_order"),
    path("pesapal/callback/", views.pesapal_redirect, name="pesapal_callback"),
    path("pesapal/ipn/", views.pesapal_ipn, name="pesapal_ipn"),
    path("payments/callback/", views.pesapal_redirect, name="payments_callback"),
    path("payments/ipn/", views.pesapal_ipn, name="payments_ipn"),

    # ===============================
    # 👤 Guest Checkout (Non-logged-in Users)
    # ===============================
    path("guest/checkout/<int:tour_id>/", views.guest_checkout, name="guest_checkout"),
    path("guest/process-info/", views.process_guest_info, name="process_guest_info"),
    path("guest/create-order/", views.create_guest_pesapal_order, name="create_guest_pesapal_order"),
    path("guest/callback/", views.guest_pesapal_callback, name="guest_payment_callback"),
    path("guest/success/", views.guest_payment_page, name="guest_payment_success"),
    path("guest/failed/", views.guest_payment_failed, name="guest_payment_failed"),

    # ===============================
    # 🚖 Driver Authentication & Dashboard
    # ===============================
    path("driver/login/", views.driver_login, name="driver_login"),
    path("driver/dashboard/", views.driver_dashboard, name="driver_dashboard"),
    path("driver/add-tour/", views.create_tour, name="add_tour"),
    path("driver/tour/<int:tour_id>/edit/", views.edit_tour, name="edit_tour"),
    path("driver/tour/<int:tour_id>/delete/", views.delete_tour, name="delete_tour"),

    # ===============================
    # 📡 Pesapal IPN registration
    # ===============================
    path("pesapal/register-ipn/", views.register_pesapal_ipn, name="register_pesapal_ipn"),

    # ===============================
    # 🧾 Receipt Page
    # ===============================
    path("receipt/<uuid:pk>/", ReceiptView.as_view(), name="receipt"),

    # ===============================
    # 🛠️ Custom Modern Admin Dashboard
    # ===============================
    path("brymax-admin/", views.modern_admin_dashboard, name="modern_admin_dashboard"),
]