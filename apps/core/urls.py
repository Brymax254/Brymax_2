from django.urls import path
from . import views
from django.contrib.auth.views import LogoutView
from .views import (
    HomeView,
    request_ride,
    ride_detail,
    cancel_ride,
    about,
    contact,
    terms,
    privacy,
    profile_view,
    trip_history,
    confirm_ride,
    rate_ride,
    run_migrations
)

app_name = 'core'

urlpatterns = [
    # Core Pages
    path('', HomeView.as_view(), name='home'),
    path('about/', about, name='about'),
    path('contact/', contact, name='contact'),
    path('terms/', terms, name='terms'),
    path('privacy/', privacy, name='privacy'),

    # User Features
    path('profile/', profile_view, name='profile'),
    path('trip-history/', trip_history, name='trip_history'),
    path('rate-ride/<int:ride_id>/', rate_ride, name='rate_ride'),

    # Ride Management
    path('request-ride/', request_ride, name='request_ride'),
    path('ride/<int:ride_id>/', ride_detail, name='ride_detail'),
    path('ride/<int:ride_id>/cancel/', cancel_ride, name='cancel_ride'),
    path('confirm-ride/', confirm_ride, name='confirm_ride'),

    # (Optional) Admin utility route
    path('run-migrations/', run_migrations, name='run_migrations'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
]
