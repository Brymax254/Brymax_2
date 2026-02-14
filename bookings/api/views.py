from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes  # Added permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import requests
from django.conf import settings
from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend

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
    BookingCreateSerializer, PaymentCreateSerializer, ReviewCreateSerializer,
    DriverCreateSerializer, TourCreateSerializer, VehicleCreateSerializer
)

from rest_framework.permissions import AllowAny, IsAuthenticated

class DriverViewSet(viewsets.ModelViewSet):
    queryset = Driver.objects.all()
    serializer_class = DriverSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return DriverCreateSerializer
        return DriverSerializer

    @action(detail=True, methods=['get'])
    def dashboard_data(self, request, pk=None):
        driver = self.get_object()
        today = timezone.now().date()

        total_earnings = Trip.objects.filter(driver=driver, status='COMPLETED').aggregate(total=Sum('earnings'))['total'] or 0
        completed_trips = Trip.objects.filter(driver=driver, status='COMPLETED').count()
        active_tours = Tour.objects.filter(created_by=driver, available=True, is_approved=True).count()

        monthly_earnings = Trip.objects.filter(
            driver=driver,
            status='COMPLETED',
            date__gte=timezone.now().replace(day=1)
        ).aggregate(total=Sum('earnings'))['total'] or 0

        today_trips = Trip.objects.filter(driver=driver, date=today)
        upcoming_trips = Trip.objects.filter(driver=driver, date__gt=today).order_by('date')[:10]

        recent_bookings = Booking.objects.filter(
            driver=driver,
            travel_date__gte=timezone.now() - timedelta(days=30)
        ).order_by('-booking_date')[:5]

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

        tours = Tour.objects.filter(created_by=driver)
        tour_stats = {
            'total': tours.count(),
            'approved': tours.filter(is_approved=True).count(),
            'pending': tours.filter(is_approved=False).count(),
            'active': tours.filter(is_approved=True, available=True).count()
        }

        reviews = Review.objects.filter(driver=driver)
        avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
        total_reviews = reviews.count()

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
        serializer.save(created_by=self.request.user.driver)

    @action(detail=True, methods=['post'])
    def toggle_approval(self, request, pk=None):
        tour = self.get_object()
        tour.is_approved = not tour.is_approved
        if tour.is_approved:
            tour.approved_by = request.user
            tour.approved_at = timezone.now()
        tour.save()
        return Response({'status': 'success', 'is_approved': tour.is_approved})

    @action(detail=True, methods=['post'])
    def toggle_availability(self, request, pk=None):
        tour = self.get_object()
        tour.available = not tour.available
        tour.save()
        return Response({'status': 'success', 'available': tour.available})


class TripViewSet(viewsets.ModelViewSet):
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
    queryset = Payment.objects.all().select_related('user', 'booking', 'tour')
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PaymentCreateSerializer
        return PaymentSerializer

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        payment = self.get_object()
        success = payment.verify_paystack_transaction()
        if success:
            return Response({'status': 'success', 'message': 'Payment verified successfully'})
        else:
            return Response({'status': 'error', 'message': 'Payment verification failed'},
                            status=status.HTTP_400_BAD_REQUEST)


class ReviewViewSet(viewsets.ModelViewSet):
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
    queryset = Vehicle.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['vehicle_type', 'fuel_type', 'is_active', 'capacity']
    search_fields = ['make', 'model', 'license_plate']
    ordering_fields = ['year', 'make', 'model', 'capacity']
    ordering = ['-year']

    def get_queryset(self):
        if self.action in ['list', 'retrieve']:
            return Vehicle.objects.filter(is_active=True)
        return Vehicle.objects.all()

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return VehicleCreateSerializer
        return VehicleSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


class BookingCustomerViewSet(viewsets.ModelViewSet):
    queryset = BookingCustomer.objects.all()
    serializer_class = BookingCustomerSerializer
    permission_classes = [permissions.IsAuthenticated]


class DestinationViewSet(viewsets.ModelViewSet):
    queryset = Destination.objects.all()
    serializer_class = DestinationSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class TourCategoryViewSet(viewsets.ModelViewSet):
    queryset = TourCategory.objects.all()
    serializer_class = TourCategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class ContactMessageViewSet(viewsets.ModelViewSet):
    queryset = ContactMessage.objects.all()
    serializer_class = ContactMessageSerializer
    permission_classes = [permissions.IsAuthenticated]


class DashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.now().date()
        current_month = today.replace(day=1)

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

        if hasattr(user, 'driver'):
            driver = user.driver
            trips = Trip.objects.filter(driver=driver)
            completed_trips = trips.filter(status='COMPLETED')

            monthly_earnings = completed_trips.filter(
                date__year=current_month.year,
                date__month=current_month.month
            ).aggregate(total=Sum('earnings'))['total'] or 0

            week_ago = today - timedelta(days=7)
            weekly_earnings = completed_trips.filter(date__gte=week_ago).aggregate(total=Sum('earnings'))['total'] or 0

            today_trips = trips.filter(date=today, status__in=['SCHEDULED', 'IN_PROGRESS']).order_by('start_time')
            upcoming_trips = trips.filter(date__gt=today, status='SCHEDULED').order_by('date')[:10]

            recent_bookings = Booking.objects.filter(
                driver=driver
            ).select_related('tour', 'payment', 'booking_customer').order_by('-created_at')[:5]

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
                vehicle_status = None

            tour_stats = Tour.objects.filter(created_by=driver).aggregate(
                total_tours=Count('id'),
                approved_tours=Count('id', filter=Q(is_approved=True)),
                active_tours=Count('id', filter=Q(available=True, is_approved=True)),
            )

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

        elif user.is_staff:
            total_tours = Tour.objects.count()
            approved_tours = Tour.objects.filter(is_approved=True).count()
            total_bookings = Booking.objects.count()
            total_payments = Payment.objects.count()
            successful_payments = Payment.objects.filter(status='SUCCESS').count()

            recent_tours = Tour.objects.select_related('created_by').order_by('-created_at')[:5]
            recent_bookings = Booking.objects.select_related('booking_customer', 'tour').order_by('-created_at')[:5]
            pending_tours = Tour.objects.filter(is_approved=False).order_by('-created_at')

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


@api_view(['GET'])
def analytics_data(request):
    total_bookings = Booking.objects.count()
    total_payments = Payment.objects.count()
    total_tours = Tour.objects.count()

    data = {
        'total_bookings': total_bookings,
        'total_payments': total_payments,
        'total_tours': total_tours,
    }
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def bookings_list(request):
    bookings = Booking.objects.all().order_by('-created_at')
    serializer = BookingSerializer(bookings, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def drivers_list(request):
    drivers = Driver.objects.all()
    serializer = DriverSerializer(drivers, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def vehicles_list(request):
    vehicles = Vehicle.objects.all()
    serializer = VehicleSerializer(vehicles, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payments_list(request):
    payments = Payment.objects.all()
    serializer = PaymentSerializer(payments, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tours_list(request):
    tours = Tour.objects.all()
    serializer = TourSerializer(tours, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile_api(request):
    driver = request.user.driver
    data = {
        "id": driver.id,
        "name": driver.full_name,
        "email": driver.user.email,
        "phone": driver.normalized_phone,
        "license": driver.license_number,
        "isAvailable": driver.available,
        "rating": driver.rating,
        "responseTime": "-",  # add logic if tracked
        "completionRate": (driver.completed_trips / driver.total_trips * 100) if driver.total_trips else 0,
        "memberSince": driver.user.date_joined.strftime("%Y-%m-%d"),
    }
    return Response(data)

from bookings.models import Receipt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def receipts_list(request):
    receipts = Receipt.objects.all().order_by('-date')
    data = [
        {
            "id": r.id,
            "bookingReference": r.booking.booking_reference if r.booking else None,
            "amount": r.amount,
            "date": r.date.strftime("%Y-%m-%d"),
        }
        for r in receipts
    ]
    return Response(data)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from bookings.models import Vehicle
from .serializers import VehicleSerializer

@api_view(['GET'])
@permission_classes([AllowAny])
def vehicle_destination_prices(request):
    vehicles = Vehicle.objects.filter(is_active=True)
    serializer = VehicleSerializer(vehicles, many=True, context={'request': request})
    return Response(serializer.data)


