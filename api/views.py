from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Avg
from django.utils import timezone
from datetime import timedelta
from bookings.models import (
    Driver, BookingCustomer, Vehicle, Destination, TourCategory, Tour,
    Booking, Trip, Payment, PaymentStatus, Review, ContactMessage,
    PaymentProvider
)

from .serializers import (
    DriverSerializer, TourSerializer, BookingSerializer, TripSerializer,
    PaymentSerializer, ReviewSerializer, VehicleSerializer, DestinationSerializer
)


class DriverViewSet(viewsets.ModelViewSet):
    queryset = Driver.objects.all()
    serializer_class = DriverSerializer

    @action(detail=True, methods=['get'])
    def dashboard_data(self, request, pk=None):
        driver = self.get_object()
        today = timezone.now().date()

        # Get basic stats
        total_earnings = Trip.objects.filter(driver=driver, status='COMPLETED').aggregate(total=Sum('earnings'))[
                             'total'] or 0
        completed_trips = Trip.objects.filter(driver=driver, status='COMPLETED').count()
        active_tours = Tour.objects.filter(created_by=driver, available=True, is_approved=True).count()

        # Get monthly earnings
        monthly_earnings = Trip.objects.filter(
            driver=driver,
            status='COMPLETED',
            date__gte=timezone.now().replace(day=1)
        ).aggregate(total=Sum('earnings'))['total'] or 0

        # Get today's trips
        today_trips = Trip.objects.filter(driver=driver, date=today)

        # Get upcoming trips
        upcoming_trips = Trip.objects.filter(
            driver=driver,
            date__gt=today
        ).order_by('date')[:10]

        # Get recent bookings
        recent_bookings = Booking.objects.filter(
            driver=driver,
            travel_date__gte=timezone.now() - timedelta(days=30)
        ).order_by('-booking_date')[:5]

        # Get vehicle status
        try:
            vehicle = driver.vehicle
            vehicle_status = {
                'name': f"{vehicle.make} {vehicle.model}",
                'plate': vehicle.license_plate,
                'status': 'ACTIVE' if vehicle.is_active else 'INACTIVE',
                'next_maintenance': vehicle.inspection_expiry.strftime(
                    "%Y-%m-%d") if vehicle.inspection_expiry else None,
                'maintenance_due': vehicle.inspection_expiry and vehicle.inspection_expiry <= today + timedelta(days=30)
            }
        except:
            vehicle_status = None

        # Get tour stats
        tours = Tour.objects.filter(created_by=driver)
        tour_stats = {
            'total': tours.count(),
            'approved': tours.filter(is_approved=True).count(),
            'pending': tours.filter(is_approved=False).count(),
            'active': tours.filter(is_approved=True, available=True).count()
        }

        # Get ratings
        reviews = Review.objects.filter(driver=driver)
        avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
        total_reviews = reviews.count()

        # Rating distribution
        rating_distribution = []
        for i in range(1, 6):
            count = reviews.filter(rating=i).count()
            rating_distribution.append({
                'rating': i,
                'count': count,
                'percentage': (count / total_reviews * 100) if total_reviews > 0 else 0
            })

        return Response({
            'driver': DriverSerializer(driver).data,
            'total_earnings': total_earnings,
            'completed_trips': completed_trips,
            'active_tours': active_tours,
            'monthly_earnings': monthly_earnings,
            'today_trips': TripSerializer(today_trips, many=True).data,
            'upcoming_trips': TripSerializer(upcoming_trips, many=True).data,
            'recent_bookings': BookingSerializer(recent_bookings, many=True).data,
            'vehicle_status': vehicle_status,
            'tour_stats': tour_stats,
            'avg_rating': avg_rating,
            'total_reviews': total_reviews,
            'rating_distribution': rating_distribution
        })


class TourViewSet(viewsets.ModelViewSet):
    queryset = Tour.objects.all()
    serializer_class = TourSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        driver_id = self.request.query_params.get('driver_id', None)
        if driver_id:
            queryset = queryset.filter(created_by_id=driver_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.driver)


class TripViewSet(viewsets.ModelViewSet):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        driver_id = self.request.query_params.get('driver_id', None)
        if driver_id:
            queryset = queryset.filter(driver_id=driver_id)
        return queryset


class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.all()
    serializer_class = BookingSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        driver_id = self.request.query_params.get('driver_id', None)
        if driver_id:
            queryset = queryset.filter(driver_id=driver_id)
        return queryset


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer


class ReviewViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        driver_id = self.request.query_params.get('driver_id', None)
        if driver_id:
            queryset = queryset.filter(driver_id=driver_id)
        return queryset

class VehicleViewSet(viewsets.ModelViewSet):
    queryset = Vehicle.objects.all()
    serializer_class = VehicleSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})  # 👈 ensures absolute image URLs
        return context


class DestinationViewSet(viewsets.ModelViewSet):
    queryset = Destination.objects.all()
    serializer_class = DestinationSerializer