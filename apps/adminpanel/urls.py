from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('reports/', views.reports, name='reports'),
    path('reports/bookings/', views.booking_reports, name='booking_reports'),
    path('reports/payments/', views.payment_reports, name='payment_reports'),
    path('settings/', views.site_settings, name='settings'),
    path('users/', views.user_management, name='users'),
]