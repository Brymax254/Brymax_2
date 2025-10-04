from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DriverViewSet, TourViewSet, TripViewSet, BookingViewSet,
    PaymentViewSet, ReviewViewSet, VehicleViewSet, DestinationViewSet
)

router = DefaultRouter()
router.register(r'drivers', DriverViewSet)
router.register(r'tours', TourViewSet)
router.register(r'trips', TripViewSet)
router.register(r'bookings', BookingViewSet)
router.register(r'payments', PaymentViewSet)
router.register(r'reviews', ReviewViewSet)
router.register(r'vehicles', VehicleViewSet)
router.register(r'destinations', DestinationViewSet)

urlpatterns = [
    path('', include(router.urls)),
]