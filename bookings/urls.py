from django.urls import path
from . import views

urlpatterns = [
    # Public pages
    path('', views.home, name='home'),
    path('book-online/', views.book_online, name='book_online'),
    path('nairobi-airport-transfers-and-taxis/', views.nairobi_transfers, name='nairobi_transfers'),
    path('book/excursions/', views.excursions, name='excursions'),
    path('tours-and-safaris/', views.tours, name='tours'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('terms/', views.terms, name='terms'),

    # Tour booking → now goes to inside-site payment page
    path('book-tour/<int:tour_id>/', views.tour_payment, name='tour_payment'),

    # Driver dashboard routes
    path('driver/login/', views.driver_login, name='driver_login'),
    path('driver/dashboard/', views.driver_dashboard, name='driver_dashboard'),

    # Actions from the driver dashboard
    path('driver/add-trip/', views.add_trip, name='add_trip'),
    path('driver/add-tour/', views.add_tour, name='add_tour'),  # allow drivers to add tours

    # Tour management (edit/delete)
    path('driver/tour/<int:tour_id>/edit/', views.edit_tour, name='edit_tour'),
    path('driver/tour/<int:tour_id>/delete/', views.delete_tour, name='delete_tour'),

    # Payment-specific routes (inside-site Pesapal / Mpesa)
    path('payments/tour/<int:tour_id>/pay/', views.tour_payment, name='tour_payment_page'),
    path('payments/tour/<int:tour_id>/mpesa/', views.mpesa_payment, name='mpesa_payment'),
    path('payments/callback/', views.pesapal_callback, name='pesapal_callback'),

path("pesapal/callback/", views.pesapal_callback, name="pesapal_callback"),
    path("pesapal/ipn/", views.pesapal_ipn, name="pesapal_ipn"),
]
