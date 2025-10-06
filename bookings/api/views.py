# bookings/api/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Sum, Q, Avg
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import requests
from django.conf import settings

from ..models import (
    Tour, Booking, Payment, Trip, BookingCustomer,
    Driver, Vehicle, Destination, Review, ContactMessage, TourCategory
)


class TourViewSet(viewsets.ModelViewSet):
    queryset = Tour.objects.all().select_related('category', 'created_by', 'approved_by')

    def list(self, request):
        tours = self.get_queryset()
        serialized_tours = []
        for tour in tours:
            serialized_tours.append({
                'id': tour.id,
                'title': tour.title,
                'slug': tour.slug,
                'tagline': tour.tagline,
                'description': tour.description,
                'price_per_person': float(tour.price_per_person) if tour.price_per_person else 0,
                'discount_price': float(tour.discount_price) if tour.discount_price else 0,
                'current_price': float(tour.current_price) if hasattr(tour, 'current_price') else float(
                    tour.price_per_person) if tour.price_per_person else 0,
                'currency': tour.currency,
                'duration_days': tour.duration_days,
                'duration_nights': tour.duration_nights,
                'max_group_size': tour.max_group_size,
                'min_group_size': tour.min_group_size,
                'difficulty': tour.difficulty,
                'category': tour.category.id if tour.category else None,
                'category_name': tour.category.name if tour.category else 'Uncategorized',
                'available': tour.available,
                'featured': tour.featured,
                'is_popular': tour.is_popular,
                'is_approved': tour.is_approved,
                'created_by': tour.created_by.id if tour.created_by else None,
                'created_by_name': tour.created_by.username if tour.created_by else 'Unknown',
                'approved_by': tour.approved_by.id if tour.approved_by else None,
                'approved_at': tour.approved_at.isoformat() if tour.approved_at else None,
                'departure_point': tour.departure_point,
                'image': tour.image.url if tour.image else tour.image_url,
                'image_url': tour.image_url,
                'created_at': tour.created_at.isoformat(),
                'updated_at': tour.updated_at.isoformat(),
                'has_discount': tour.has_discount if hasattr(tour,
                                                             'has_discount') else tour.discount_price and tour.discount_price < tour.price_per_person,
                'total_duration': tour.total_duration if hasattr(tour,
                                                                 'total_duration') else f"{tour.duration_days} days, {tour.duration_nights} nights"
            })
        return Response(serialized_tours)

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


class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.all().select_related('booking_customer', 'destination', 'tour', 'driver', 'vehicle')

    def list(self, request):
        bookings = self.get_queryset()
        serialized_bookings = []
        for booking in bookings:
            serialized_bookings.append({
                'id': booking.id,
                'booking_reference': booking.booking_reference,
                'booking_customer': booking.booking_customer.id if booking.booking_customer else None,
                'booking_customer_name': booking.booking_customer.full_name if booking.booking_customer else 'Unknown',
                'destination': booking.destination.id if booking.destination else None,
                'destination_name': booking.destination.name if booking.destination else None,
                'tour': booking.tour.id if booking.tour else None,
                'tour_id': booking.tour.id if booking.tour else None,
                'tour_name': booking.tour.title if booking.tour else None,
                'booking_type': booking.booking_type,
                'num_adults': booking.num_adults,
                'num_children': booking.num_children,
                'num_infants': booking.num_infants,
                'total_passengers': booking.total_passengers,
                'pickup_location': booking.pickup_location,
                'dropoff_location': booking.dropoff_location,
                'travel_date': booking.travel_date.isoformat() if booking.travel_date else None,
                'travel_time': booking.travel_time.isoformat() if booking.travel_time else None,
                'status': booking.status,
                'total_price': float(booking.total_price) if booking.total_price else 0,
                'currency': booking.currency,
                'is_paid': booking.is_paid,
                'is_cancelled': booking.is_cancelled,
                'service_name': booking.service_name,
                'created_at': booking.created_at.isoformat(),
                'updated_at': booking.updated_at.isoformat()
            })
        return Response(serialized_bookings)


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.all().select_related('user', 'booking', 'tour')

    def list(self, request):
        payments = self.get_queryset()
        serialized_payments = []
        for payment in payments:
            serialized_payments.append({
                'id': payment.id,
                'reference': payment.reference,
                'amount': float(payment.amount) if payment.amount else 0,
                'amount_paid': float(payment.amount_paid) if payment.amount_paid else 0,
                'currency': payment.currency,
                'status': payment.status,
                'provider': payment.provider,
                'method': payment.method,
                'guest_full_name': payment.guest_full_name,
                'guest_email': payment.guest_email,
                'guest_phone': payment.guest_phone,
                'tour': payment.tour.id if payment.tour else None,
                'tour_title': payment.tour.title if payment.tour else None,
                'booking': payment.booking.id if payment.booking else None,
                'paystack_transaction_id': payment.paystack_transaction_id,
                'authorization_code': payment.authorization_code,
                'webhook_verified': payment.webhook_verified,
                'paid_on': payment.paid_on.isoformat() if payment.paid_on else None,
                'created_at': payment.created_at.isoformat(),
                'updated_at': payment.updated_at.isoformat(),
                'is_successful': payment.status == 'SUCCESS'
            })
        return Response(serialized_payments)

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        payment = self.get_object()
        success = payment.verify_paystack_transaction()
        if success:
            return Response({'status': 'success', 'message': 'Payment verified successfully'})
        else:
            return Response({'status': 'error', 'message': 'Payment verification failed'},
                            status=status.HTTP_400_BAD_REQUEST)


class TripViewSet(viewsets.ModelViewSet):
    queryset = Trip.objects.all().select_related('driver', 'booking', 'vehicle')

    def list(self, request):
        trips = self.get_queryset()
        serialized_trips = []
        for trip in trips:
            serialized_trips.append({
                'id': trip.id,
                'driver': trip.driver.id if trip.driver else None,
                'driver_name': trip.driver.full_name if trip.driver else 'Unknown',
                'destination': trip.destination,
                'date': trip.date.isoformat() if trip.date else None,
                'start_time': trip.start_time.isoformat() if trip.start_time else None,
                'end_time': trip.end_time.isoformat() if trip.end_time else None,
                'earnings': float(trip.earnings) if trip.earnings else 0,
                'distance': float(trip.distance) if trip.distance else 0,
                'status': trip.status,
                'customer_rating': trip.customer_rating,
                'customer_feedback': trip.customer_feedback,
                'created_at': trip.created_at.isoformat()
            })
        return Response(serialized_trips)


# Simplified ViewSets for other models
class BookingCustomerViewSet(viewsets.ModelViewSet):
    queryset = BookingCustomer.objects.all()

    def list(self, request):
        customers = self.get_queryset()
        serialized_customers = [{
            'id': customer.id,
            'full_name': customer.full_name,
            'email': customer.email,
            'phone_number': customer.phone_number,
            'normalized_phone': customer.normalized_phone,
            'adults': customer.adults,
            'children': customer.children,
            'travel_date': customer.travel_date.isoformat() if customer.travel_date else None,
            'days': customer.days,
            'created_at': customer.created_at.isoformat()
        } for customer in customers]
        return Response(serialized_customers)


class DriverViewSet(viewsets.ModelViewSet):
    queryset = Driver.objects.all().select_related('user', 'vehicle')

    def list(self, request):
        drivers = self.get_queryset()
        serialized_drivers = [{
            'id': driver.id,
            'full_name': driver.full_name,
            'phone_number': driver.phone_number,
            'license_number': driver.license_number,
            'available': driver.available,
            'rating': float(driver.rating) if driver.rating else 0,
            'total_trips': driver.total_trips,
            'total_earnings': float(driver.total_earnings) if driver.total_earnings else 0,
            'created_at': driver.created_at.isoformat()
        } for driver in drivers]
        return Response(serialized_drivers)


class VehicleViewSet(viewsets.ModelViewSet):
    queryset = Vehicle.objects.all()

    def list(self, request):
        vehicles = self.get_queryset()
        serialized_vehicles = [{
            'id': vehicle.id,
            'make': vehicle.make,
            'model': vehicle.model,
            'license_plate': vehicle.license_plate,
            'vehicle_type': vehicle.vehicle_type,
            'capacity': vehicle.capacity,
            'is_active': vehicle.is_active,
            'created_at': vehicle.created_at.isoformat()
        } for vehicle in vehicles]
        return Response(serialized_vehicles)


class DashboardView(APIView):
    def get(self, request):
        # Calculate real statistics from your database
        total_tours = Tour.objects.count()
        approved_tours = Tour.objects.filter(is_approved=True).count()
        pending_tours = Tour.objects.filter(is_approved=False).count()
        active_tours = Tour.objects.filter(available=True, is_approved=True).count()

        # Calculate earnings from successful payments
        successful_payments = Payment.objects.filter(status='SUCCESS')
        total_earnings = successful_payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Monthly earnings
        current_month = timezone.now().month
        current_year = timezone.now().year
        monthly_earnings = successful_payments.filter(
            created_at__month=current_month,
            created_at__year=current_year
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Completed trips
        completed_trips = Trip.objects.filter(status='COMPLETED').count()

        # Today's trips
        today = timezone.now().date()
        today_trips = Trip.objects.filter(date=today)

        # Recent bookings (last 5)
        recent_bookings = Booking.objects.select_related('booking_customer', 'tour').order_by('-created_at')[:5]

        dashboard_data = {
            'tour_stats': {
                'total': total_tours,
                'approved': approved_tours,
                'pending': pending_tours,
                'active': active_tours
            },
            'total_earnings': float(total_earnings),
            'monthly_earnings': float(monthly_earnings),
            'completed_trips': completed_trips,
            'active_tours': active_tours,
            'today_trips': [{
                'id': trip.id,
                'driver_name': trip.driver.full_name if trip.driver else 'Unknown',
                'destination': trip.destination,
                'status': trip.status
            } for trip in today_trips],
            'recent_bookings': [{
                'id': booking.id,
                'customer': booking.booking_customer.full_name if booking.booking_customer else 'Unknown',
                'service_name': booking.service_name,
                'amount': float(booking.total_price) if booking.total_price else 0
            } for booking in recent_bookings],
            'avg_rating': 4.7,  # You can calculate this from reviews
            'total_reviews': 0  # You can calculate this from reviews
        }

        return Response(dashboard_data)