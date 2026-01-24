from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DriverViewSet,
    TourViewSet,
    BookingViewSet,
    TripViewSet,
    BookingCustomerViewSet,
    VehicleViewSet,
    DestinationViewSet,
    TourCategoryViewSet,
    ContactMessageViewSet,
    PaymentViewSet,
    ReviewViewSet,
    DashboardView,
    analytics_data,
)

app_name = "api"

router = DefaultRouter()
router.register("drivers", DriverViewSet, basename="driver")
router.register("tours", TourViewSet, basename="tour")
router.register("trips", TripViewSet, basename="trip")
router.register("bookings", BookingViewSet, basename="booking")
router.register("payments", PaymentViewSet, basename="payment")
router.register("reviews", ReviewViewSet, basename="review")
router.register("vehicles", VehicleViewSet, basename="vehicle")
router.register("destinations", DestinationViewSet, basename="destination")
router.register("booking-customers", BookingCustomerViewSet, basename="booking_customer")
router.register("tour-categories", TourCategoryViewSet, basename="tour_category")
router.register("contact-messages", ContactMessageViewSet, basename="contact_message")

urlpatterns = [
    path("", include(router.urls)),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("analytics/", analytics_data, name="analytics"),
]
