# /home/brymax/Documents/airport_destinations/bookings/api/views.py

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import requests
from django.conf import settings
from rest_framework import viewsets, filters
from rest_framework.permissions import AllowAny, IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.permissions import AllowAny, IsAuthenticated
from bookings.models import (
    Driver, BookingCustomer, Vehicle, Destination, TourCategory, Tour,
    Booking, Trip, Payment, PaymentStatus, Review, ContactMessage,
    PaymentProvider
)

from .serializers import (
    DriverSerializer, TourSerializer, BookingSerializer, TripSerializer,
    PaymentSerializer, ReviewSerializer, VehicleSerializer, DestinationSerializer,
    BookingCustomerSerializer, TourCategorySerializer, ContactMessageSerializer,
    PaymentProviderSerializer, PaymentStatusSerializer,
    # Create/Update serializers
    BookingCreateSerializer, PaymentCreateSerializer, ReviewCreateSerializer,
    DriverCreateSerializer, TourCreateSerializer, VehicleCreateSerializer
)


class DriverViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows drivers to be viewed or edited.
    """
    queryset = Driver.objects.all()
    serializer_class = DriverSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return DriverCreateSerializer
        return DriverSerializer

    @action(detail=True, methods=['get'])
    def dashboard_data(self, request, pk=None):
        """
        Retrieves detailed dashboard data for a specific driver.
        """
        driver = self.get_object()
        today = timezone.now().date()

        # Get basic stats
        total_earnings = Trip.objects.filter(driver=driver, status='COMPLETED').aggregate(total=Sum('earnings'))['total'] or 0
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
                'next_maintenance': vehicle.inspection_expiry.strftime("%Y-%m-%d") if vehicle.inspection_expiry else None,
                'maintenance_due': vehicle.inspection_expiry and vehicle.inspection_expiry <= today + timedelta(days=30)
            }
        except Vehicle.DoesNotExist:
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
    """
    API endpoint that allows tours to be viewed or edited.
    """
    queryset = Tour.objects.all().select_related('category', 'created_by', 'approved_by')
    serializer_class = TourSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return TourCreateSerializer
        return TourSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        driver_id = self.request.query_params.get('driver_id', None)
        if driver_id:
            queryset = queryset.filter(created_by_id=driver_id)
        return queryset

    def perform_create(self, serializer):
        # Assumes the User model has a OneToOneField to Driver with related_name='driver'
        serializer.save(created_by=self.request.user.driver)

    @action(detail=True, methods=['post'])
    def toggle_approval(self, request, pk=None):
        """
        Toggles the approval status of a tour.
        """
        tour = self.get_object()
        tour.is_approved = not tour.is_approved
        if tour.is_approved:
            tour.approved_by = request.user
            tour.approved_at = timezone.now()
        tour.save()
        return Response({'status': 'success', 'is_approved': tour.is_approved})

    @action(detail=True, methods=['post'])
    def toggle_availability(self, request, pk=None):
        """
        Toggles the availability status of a tour.
        """
        tour = self.get_object()
        tour.available = not tour.available
        tour.save()
        return Response({'status': 'success', 'available': tour.available})


class TripViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows trips to be viewed or edited.
    """
    queryset = Trip.objects.all().select_related('driver', 'booking', 'vehicle')
    serializer_class = TripSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        driver_id = self.request.query_params.get('driver_id', None)
        if driver_id:
            queryset = queryset.filter(driver_id=driver_id)
        return queryset


class BookingViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows bookings to be viewed or edited.
    """
    queryset = Booking.objects.all().select_related('booking_customer', 'destination', 'tour', 'driver', 'vehicle')
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return BookingCreateSerializer
        return BookingSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        driver_id = self.request.query_params.get('driver_id', None)
        if driver_id:
            queryset = queryset.filter(driver_id=driver_id)
        return queryset


class PaymentViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows payments to be viewed or edited.
    """
    queryset = Payment.objects.all().select_related('user', 'booking', 'tour')
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PaymentCreateSerializer
        return PaymentSerializer

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        """
        Verifies a payment transaction with the provider.
        """
        payment = self.get_object()
        success = payment.verify_paystack_transaction()
        if success:
            return Response({'status': 'success', 'message': 'Payment verified successfully'})
        else:
            return Response({'status': 'error', 'message': 'Payment verification failed'},
                            status=status.HTTP_400_BAD_REQUEST)


class ReviewViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows reviews to be viewed or edited.
    """
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ReviewCreateSerializer
        return ReviewSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        driver_id = self.request.query_params.get('driver_id', None)
        if driver_id:
            queryset = queryset.filter(driver_id=driver_id)
        return queryset


class VehicleViewSet(viewsets.ModelViewSet):
    """
    Vehicle API:
    - Public users: can LIST and RETRIEVE active vehicles
    - Authenticated users: can CREATE, UPDATE, DELETE vehicles
    """

    queryset = Vehicle.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['vehicle_type', 'fuel_type', 'is_active', 'capacity']
    search_fields = ['make', 'model', 'license_plate']
    ordering_fields = ['year', 'make', 'model', 'capacity']
    ordering = ['-year']

    def get_queryset(self):
        # Public users should only see active vehicles
        if self.action in ['list', 'retrieve']:
            return Vehicle.objects.filter(is_active=True)
        return Vehicle.objects.all()

    def get_permissions(self):
        # Public read access
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        # Authenticated users for write actions
        return [IsAuthenticated()]

    def get_serializer_class(self):
        # Use different serializer for write operations
        if self.action in ['create', 'update', 'partial_update']:
            return VehicleCreateSerializer
        return VehicleSerializer

    def get_serializer_context(self):
        """
        Include request in context to generate absolute URLs for images
        """
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

class BookingCustomerViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows booking customers to be viewed or edited.
    """
    queryset = BookingCustomer.objects.all()
    serializer_class = BookingCustomerSerializer
    permission_classes = [permissions.IsAuthenticated]


class DestinationViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows destinations to be viewed or edited.
    """
    queryset = Destination.objects.all()
    serializer_class = DestinationSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class TourCategoryViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows tour categories to be viewed or edited.
    """
    queryset = TourCategory.objects.all()
    serializer_class = TourCategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class ContactMessageViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows contact messages to be viewed or edited.
    """
    queryset = ContactMessage.objects.all()
    serializer_class = ContactMessageSerializer
    permission_classes = [permissions.IsAuthenticated]


class DashboardView(APIView):
    """
    A single API endpoint to get dashboard data for both drivers and admin users.
    The response structure changes based on the user's role.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.now().date()
        current_month = today.replace(day=1)

        # Base user data
        data = {
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_staff': user.is_staff,
            }
        }

        # Driver-specific data
        # Assumes the User model has a OneToOneField to Driver with related_name='driver'
        if hasattr(user, 'driver'):
            driver = user.driver

            # Trip stats
            trips = Trip.objects.filter(driver=driver)
            completed_trips = trips.filter(status='COMPLETED')

            # Earnings
            monthly_earnings = completed_trips.filter(
                date__year=current_month.year,
                date__month=current_month.month
            ).aggregate(total=Sum('earnings'))['total'] or 0

            week_ago = today - timedelta(days=7)
            weekly_earnings = completed_trips.filter(date__gte=week_ago).aggregate(total=Sum('earnings'))['total'] or 0

            # Today's and upcoming trips
            today_trips = trips.filter(date=today, status__in=['SCHEDULED', 'IN_PROGRESS']).order_by('start_time')
            upcoming_trips = trips.filter(date__gt=today, status='SCHEDULED').order_by('date')[:10]

            # Recent bookings for this driver's tours
            recent_bookings = Booking.objects.filter(
                driver=driver
            ).select_related('tour', 'payment', 'booking_customer').order_by('-created_at')[:5]

            # Vehicle status
            vehicle_status = None
            try:
                vehicle = driver.vehicle
                vehicle_status = {
                    'name': f"{vehicle.make} {vehicle.model}",
                    'plate': vehicle.license_plate,
                    'status': 'ACTIVE' if vehicle.is_active else 'INACTIVE',
                    'next_maintenance': vehicle.inspection_expiry.strftime("%Y-%m-%d") if vehicle.inspection_expiry else None,
                    'maintenance_due': vehicle.inspection_expiry and vehicle.inspection_expiry <= today + timedelta(days=7),
                }
            except Vehicle.DoesNotExist:
                pass

            # Tour stats
            tour_stats = Tour.objects.filter(created_by=driver).aggregate(
                total_tours=Count('id'),
                approved_tours=Count('id', filter=Q(is_approved=True)),
                active_tours=Count('id', filter=Q(available=True, is_approved=True)),
            )

            # Add driver-specific data to the response
            data.update({
                'driver': DriverSerializer(driver).data,
                'stats': {
                    'monthly_earnings': float(monthly_earnings),
                    'weekly_earnings': float(weekly_earnings),
                    'total_tours': tour_stats['total_tours'],
                    'approved_tours': tour_stats['approved_tours'],
                    'active_tours': tour_stats['active_tours'],
                },
                'today_trips': TripSerializer(today_trips, many=True).data,
                'upcoming_trips': TripSerializer(upcoming_trips, many=True).data,
                'recent_bookings': BookingSerializer(recent_bookings, many=True).data,
                'vehicle_status': vehicle_status,
            })

        # Admin-specific data
        elif user.is_staff:
            # Overall stats
            total_tours = Tour.objects.count()
            approved_tours = Tour.objects.filter(is_approved=True).count()
            total_bookings = Booking.objects.count()
            total_payments = Payment.objects.count()
            successful_payments = Payment.objects.filter(status='SUCCESS').count()

            # Recent activity
            recent_tours = Tour.objects.select_related('created_by').order_by('-created_at')[:5]
            recent_bookings = Booking.objects.select_related('booking_customer', 'tour').order_by('-created_at')[:5]
            pending_tours = Tour.objects.filter(is_approved=False).order_by('-created_at')

            # Add admin-specific data to the response
            data.update({
                'admin': {
                    'stats': {
                        'total_tours': total_tours,
                        'approved_tours': approved_tours,
                        'total_bookings': total_bookings,
                        'total_payments': total_payments,
                        'successful_payments': successful_payments,
                    },
                    'recent_tours': TourSerializer(recent_tours, many=True).data,
                    'recent_bookings': BookingSerializer(recent_bookings, many=True).data,
                    'pending_tours': TourSerializer(pending_tours, many=True).data,
                }
            })

        return Response(data)