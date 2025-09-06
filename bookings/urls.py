from django.urls import path
from . import views

urlpatterns = [
    # Public Pages
    path('', views.home, name='home'),
    path('book-online/', views.book_online, name='book_online'),
    path('nairobi-airport-transfers-and-taxis/', views.nairobi_transfers, name='nairobi_transfers'),
    path('book/excursions/', views.excursions, name='excursions'),
    path('tours-and-safaris/', views.tours, name='tours'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('terms/', views.terms, name='terms'),

    # Tour Booking & Payments
    path('book-tour/<int:tour_id>/', views.tour_payment, name='tour_payment'),
    path('payments/tour/<int:tour_id>/pay/', views.tour_payment, name='tour_payment_page'),  # You might want to consolidate this with the above if both map to the same view
    path('payments/tour/<int:tour_id>/mpesa/', views.mpesa_payment, name='mpesa_payment'),
    path('payments/success/', views.payment_success, name='payment_success'),
    path('payments/failed/', views.payment_failed, name='payment_failed'),

    # Driver Authentication & Dashboard
    path('driver/login/', views.driver_login, name='driver_login'),
    path('driver/dashboard/', views.driver_dashboard, name='driver_dashboard'),

    # Driver Actions (Dashboard Management)
    path('driver/add-trip/', views.add_trip, name='add_trip'),
    path('driver/add-tour/', views.add_tour, name='add_tour'),

    # Driver Tour Management
    path('driver/tour/<int:tour_id>/edit/', views.edit_tour, name='edit_tour'),
    path('driver/tour/<int:tour_id>/delete/', views.delete_tour, name='delete_tour'),

    # Pesapal Payment Integration
    path('pesapal/callback/', views.pesapal_callback, name='pesapal_callback'),
    path('pesapal/ipn/', views.pesapal_ipn, name='pesapal_ipn'),
    path('pesapal/test-auth/', views.test_pesapal_auth, name='test_pesapal_auth'),
]
