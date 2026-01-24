from django.urls import path
from . import views

app_name = "bookings"

urlpatterns = [
    # 🌍 Public pages
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("terms/", views.terms, name="terms"),

    # 🚌 Tours & Bookings
    path("book-online/", views.book_online, name="book_online"),
    path("airport-transfers/", views.nairobi_transfers, name="airport_transfers"),
    path("excursions/", views.excursions, name="excursions"),
    path("tours-and-safaris/", views.tours, name="tours"),
    path("tour/<slug:tour_slug>/", views.TourDetailView.as_view(), name="tour_detail"),
    path(
        "nairobi-airport-transfers-and-taxis/",
        views.nairobi_airport_transfers,
        name="nairobi_airport_transfers",
    ),
path("destination/<slug:slug>/", views.DestinationDetailView.as_view(), name="destination_detail"),

    # 💳 Payments
    path("tour/<int:tour_id>/pay/", views.tour_payment, name="tour_payment"),
    path("payments/success/", views.payment_success, name="payment_success"),
    path("payments/success/<uuid:pk>/", views.payment_success_detail, name="payment_success_detail"),
    path("payments/pending/", views.payment_pending, name="payment_pending"),
    path("payments/failed/", views.payment_failed, name="payment_failed"),

    # 🚖 Driver dashboard
    path("driver/login/", views.driver_login, name="driver_login"),
    path("driver/logout/", views.driver_logout, name="driver_logout"),
    path("driver/dashboard/", views.driver_dashboard, name="driver_dashboard"),
# PDF receipt
path("receipt/<int:booking_id>/pdf/", views.generate_receipt_pdf, name="generate_receipt_pdf"),

path('api/vehicle-destination-prices/', views.vehicle_destination_prices_api, name='vehicle_destination_prices_api'),

    # 🧾 Receipts
    path("receipt/<uuid:pk>/", views.receipt, name="receipt"),
path("driver/tour/add/", views.create_tour, name="create_tour"),
path("driver/tour/<int:tour_id>/edit/", views.edit_tour, name="edit_tour"),
path("driver/tour/<int:tour_id>/delete/", views.delete_tour, name="delete_tour"),
    # 🏥 Health
    path("health/", views.health_check, name="health_check"),
]
