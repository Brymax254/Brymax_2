# bookings/api.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, Count, Avg, Q, F
from django.utils import timezone
from datetime import timedelta
import json
from decimal import Decimal
from bookings.models import (
    BookingCustomer, Driver, Vehicle, Destination, TourCategory, Tour,
    Booking, Trip, Payment, PaymentProvider, PaymentStatus
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def serialize_booking(booking):
    """Serialize booking object"""
    return {
        'id': booking.id,
        'reference': booking.booking_reference,
        'customer_name': booking.booking_customer.full_name if booking.booking_customer else 'N/A',
        'customer_phone': booking.booking_customer.phone_number if booking.booking_customer else 'N/A',
        'service_name': booking.service_name,
        'travel_date': booking.travel_date.strftime('%Y-%m-%d') if booking.travel_date else '',
        'travel_time': booking.travel_time.strftime('%H:%M') if booking.travel_time else '',
        'status': booking.status,
        'status_class': booking.status.lower(),
        'total_price': float(booking.total_price) if booking.total_price else 0,
        'currency': booking.currency or 'KES',
        'is_paid': booking.is_paid,
        'num_adults': booking.num_adults or 0,
        'num_children': booking.num_children or 0,
        'num_infants': booking.num_infants or 0,
        'total_passengers': booking.total_passengers,
        'created_at': booking.created_at.strftime('%Y-%m-%d %H:%M') if booking.created_at else '',
    }


def serialize_driver(driver):
    """Serialize driver object"""
    return {
        'id': driver.id,
        'full_name': driver.full_name,
        'initials': driver.full_name[:2].upper() if driver.full_name else 'DR',
        'phone': driver.normalized_phone or driver.phone_number or 'N/A',
        'email': driver.user.email if driver.user else 'N/A',
        'license_number': driver.license_number or 'N/A',
        'license_type': driver.license_type or 'N/A',
        'license_expiry': driver.license_expiry.strftime('%Y-%m-%d') if driver.license_expiry else 'N/A',
        'license_status': 'Valid' if driver.license_expiry and driver.license_expiry >= timezone.now().date() else 'Expired',
        'available': driver.available,
        'is_verified': driver.is_verified,
        'experience_years': driver.experience_years or 0,
        'rating': float(driver.rating) if driver.rating else 0,
        'vehicle': {
            'make': driver.vehicle.make if driver.vehicle else '',
            'model': driver.vehicle.model if driver.vehicle else '',
            'registration': driver.vehicle.license_plate if driver.vehicle else '',
        } if driver.vehicle else None,
    }


def serialize_vehicle(vehicle):
    """Serialize vehicle object"""
    return {
        'id': vehicle.id,
        'make': vehicle.make or '',
        'model': vehicle.model or '',
        'year': vehicle.year or '',
        'color': vehicle.color or '',
        'registration': vehicle.license_plate or '',
        'vehicle_type': vehicle.vehicle_type or '',
        'fuel_type': vehicle.fuel_type or '',
        'capacity': vehicle.capacity or 0,
        'price': float(vehicle.price_ksh) if vehicle.price_ksh else 0,
        'currency': 'KES',
        'is_active': vehicle.is_active,
        'features': vehicle.features or [],
        'insurance_expiry': vehicle.insurance_expiry.strftime('%Y-%m-%d') if vehicle.insurance_expiry else '',
        'inspection_expiry': vehicle.inspection_expiry.strftime('%Y-%m-%d') if vehicle.inspection_expiry else '',
        'insurance_status': 'Valid' if vehicle.insurance_expiry and vehicle.insurance_expiry >= timezone.now().date() else 'Expired',
        'inspection_status': 'Valid' if vehicle.inspection_expiry and vehicle.inspection_expiry >= timezone.now().date() else 'Expired',
        'maintenance_status': 'Due' if vehicle.next_service_due and vehicle.next_service_due <= timezone.now().date() else 'OK',
        'maintenance_due': vehicle.next_service_due and vehicle.next_service_due <= timezone.now().date(),
    }


def serialize_tour(tour):
    """Serialize tour object"""
    return {
        'id': tour.id,
        'title': tour.title or '',
        'tagline': tour.tagline or '',
        'code': tour.code or '',
        'category': tour.category.name if tour.category else 'Uncategorized',
        'duration_days': tour.duration_days or 0,
        'duration_nights': tour.duration_nights or 0,
        'price_per_person': float(tour.price_per_person) if tour.price_per_person else 0,
        'currency': tour.currency or 'KES',
        'available': tour.available,
        'featured': tour.featured,
        'is_popular': tour.is_popular,
        'rating': float(tour.rating) if tour.rating else 0,
        'destinations_visited': ', '.join([d.name for d in tour.destinations_visited.all()]),
        'total_bookings': tour.bookings.count(),
        'image_url': tour.image_url or tour.image.url if tour.image else None,
    }


def serialize_payment(payment):
    """Serialize payment object"""
    return {
        'id': payment.id,
        'transaction_id': payment.transaction_id or 'N/A',
        'booking_reference': payment.booking.booking_reference if payment.booking else 'N/A',
        'customer_name': payment.booking.booking_customer.full_name if payment.booking and payment.booking.booking_customer else 'N/A',
        'service_name': payment.booking.service_name if payment.booking else 'N/A',
        'amount': float(payment.amount) if payment.amount else 0,
        'currency': payment.currency or 'KES',
        'provider': payment.provider.name if payment.provider else 'N/A',
        'status': payment.status,
        'status_class': payment.status.lower(),
        'is_refunded': payment.is_refunded,
        'date': payment.created_at.strftime('%Y-%m-%d') if payment.created_at else '',
        'time': payment.created_at.strftime('%H:%M') if payment.created_at else '',
    }


# =============================================================================
# API VIEWS
# =============================================================================

@csrf_exempt
@require_http_methods(["GET"])
def dashboard_stats(request):
    """Get dashboard statistics"""
    try:
        today = timezone.now().date()
        thirty_days_ago = today - timedelta(days=30)

        # Bookings stats
        total_bookings = Booking.objects.count()
        pending_bookings = Booking.objects.filter(status='PENDING').count()
        confirmed_bookings = Booking.objects.filter(status='CONFIRMED').count()
        completed_bookings = Booking.objects.filter(status='COMPLETED').count()
        today_bookings = Booking.objects.filter(travel_date=today).count()

        # Revenue stats
        total_revenue = Booking.objects.filter(is_paid=True).aggregate(
            total=Sum('total_price')
        )['total'] or Decimal('0')

        pending_revenue = Booking.objects.filter(status='PENDING', is_paid=False).aggregate(
            total=Sum('total_price')
        )['total'] or Decimal('0')

        # Drivers stats
        total_drivers = Driver.objects.count()
        available_drivers = Driver.objects.filter(available=True).count()
        verified_drivers = Driver.objects.filter(is_verified=True).count()

        # License expiring soon (within 30 days)
        expiring_licenses = Driver.objects.filter(
            license_expiry__gte=today,
            license_expiry__lte=today + timedelta(days=30)
        ).count()

        # Vehicles stats
        total_vehicles = Vehicle.objects.count()
        active_vehicles = Vehicle.objects.filter(is_active=True).count()
        available_vehicles = Vehicle.objects.filter(is_active=True, status='available').count()

        # Insurance expiring soon
        expiring_insurance = Vehicle.objects.filter(
            insurance_expiry__gte=today,
            insurance_expiry__lte=today + timedelta(days=30)
        ).count()

        # Maintenance vehicles
        maintenance_vehicles = Vehicle.objects.filter(
            next_service_due__lte=today
        ).count()

        # Payments stats
        pending_payments = Payment.objects.filter(status='PENDING').count()
        failed_payments = Payment.objects.filter(status='FAILED').count()
        refunded_amount = Payment.objects.filter(status='REFUNDED').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        # Recent activities
        recent_activities = []
        recent_bookings = Booking.objects.order_by('-created_at')[:5]
        for booking in recent_bookings:
            recent_activities.append({
                'time': booking.created_at.strftime('%H:%M') if booking.created_at else '',
                'title': f'New Booking: {booking.booking_reference}',
                'description': f'{booking.booking_customer.full_name if booking.booking_customer else "Customer"} booked {booking.service_name}',
                'status': booking.status,
                'status_class': booking.status.lower(),
            })

        # Top tours
        top_tours = []
        tours_with_bookings = Tour.objects.annotate(
            booking_count=Count('bookings')
        ).filter(booking_count__gt=0).order_by('-booking_count')[:5]

        for tour in tours_with_bookings:
            revenue = tour.bookings.filter(is_paid=True).aggregate(
                total=Sum('total_price')
            )['total'] or Decimal('0')

            top_tours.append({
                'name': tour.title,
                'bookings': tour.bookings.count(),
                'revenue': float(revenue),
            })

        # Pending actions
        pending_actions = []

        # Unverified drivers
        unverified_drivers = Driver.objects.filter(is_verified=False).count()
        if unverified_drivers > 0:
            pending_actions.append({
                'title': f'{unverified_drivers} drivers need verification',
                'description': 'Verify driver documents and licenses',
                'action': 'loadDrivers()',
                'btn_text': 'Verify Now',
                'btn_class': 'btn-primary',
                'icon': 'fa-user-check',
            })

        # Pending payments
        if pending_payments > 0:
            pending_actions.append({
                'title': f'{pending_payments} pending payments',
                'description': 'Review and process payments',
                'action': 'switchTab("payments-tab")',
                'btn_text': 'View Payments',
                'btn_class': 'btn-warning',
                'icon': 'fa-credit-card',
            })

        # Alerts
        alerts = []

        # Expiring licenses
        if expiring_licenses > 0:
            alerts.append({
                'title': f'{expiring_licenses} driver licenses expiring soon',
                'message': 'Review and renew licenses',
                'type': 'warning',
                'icon': 'fa-id-card',
            })

        # Expiring insurance
        if expiring_insurance > 0:
            alerts.append({
                'title': f'{expiring_insurance} vehicle insurance expiring',
                'message': 'Renew vehicle insurance',
                'type': 'warning',
                'icon': 'fa-car',
            })

        # Maintenance due
        if maintenance_vehicles > 0:
            alerts.append({
                'title': f'{maintenance_vehicles} vehicles need maintenance',
                'message': 'Schedule vehicle maintenance',
                'type': 'warning',
                'icon': 'fa-wrench',
            })

        data = {
            'total_bookings': total_bookings,
            'pending_bookings': pending_bookings,
            'confirmed_bookings': confirmed_bookings,
            'completed_bookings': completed_bookings,
            'today_bookings': today_bookings,
            'total_revenue': float(total_revenue),
            'pending_revenue': float(pending_revenue),
            'total_drivers': total_drivers,
            'available_drivers': available_drivers,
            'verified_drivers': verified_drivers,
            'expiring_licenses': expiring_licenses,
            'total_vehicles': total_vehicles,
            'active_vehicles': active_vehicles,
            'available_vehicles': available_vehicles,
            'expiring_insurance': expiring_insurance,
            'maintenance_vehicles': maintenance_vehicles,
            'pending_payments': pending_payments,
            'failed_payments': failed_payments,
            'refunded_amount': float(refunded_amount),
            'recent_activities': recent_activities,
            'top_tours': top_tours,
            'pending_actions': pending_actions,
            'alerts': alerts,

            # Changes from last month (simplified - you can implement real comparison)
            'bookings_change': 12,  # Example: 12% increase
            'revenue_change': 8,  # Example: 8% increase
            'drivers_change': 5,  # Example: 5% increase
            'vehicles_change': 3,  # Example: 3% increase
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def bookings_list(request):
    """Get bookings with filtering"""
    try:
        status = request.GET.get('status', '')
        booking_type = request.GET.get('type', '')
        date_from = request.GET.get('date_from', '')
        date_to = request.GET.get('date_to', '')

        bookings = Booking.objects.all().order_by('-created_at')

        # Apply filters
        if status:
            bookings = bookings.filter(status=status)
        if booking_type:
            bookings = bookings.filter(booking_type=booking_type)
        if date_from:
            bookings = bookings.filter(travel_date__gte=date_from)
        if date_to:
            bookings = bookings.filter(travel_date__lte=date_to)

        # Limit results for performance
        bookings = bookings[:100]

        data = {
            'results': [serialize_booking(booking) for booking in bookings],
            'count': bookings.count(),
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def drivers_list(request):
    """Get drivers list"""
    try:
        drivers = Driver.objects.all().order_by('-created_at')[:50]

        data = {
            'results': [serialize_driver(driver) for driver in drivers],
            'count': drivers.count(),
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def vehicles_list(request):
    """Get vehicles list"""
    try:
        vehicles = Vehicle.objects.all().order_by('-created_at')[:50]

        data = {
            'results': [serialize_vehicle(vehicle) for vehicle in vehicles],
            'count': vehicles.count(),
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def payments_list(request):
    """Get payments list"""
    try:
        payments = Payment.objects.all().order_by('-created_at')[:50]

        data = {
            'results': [serialize_payment(payment) for payment in payments],
            'count': payments.count(),
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def tours_list(request):
    """Get tours list"""
    try:
        tours = Tour.objects.all().order_by('-created_at')[:50]

        # Get categories
        categories = TourCategory.objects.filter(is_active=True).annotate(
            tour_count=Count('tours')
        )

        categories_data = []
        for category in categories:
            categories_data.append({
                'name': category.name,
                'tour_count': category.tour_count,
                'is_active': category.is_active,
            })

        data = {
            'results': [serialize_tour(tour) for tour in tours],
            'categories': categories_data,
            'count': tours.count(),
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def analytics_data(request):
    """Get analytics data"""
    try:
        # Revenue data (last 6 months)
        revenue_data = []
        months = []
        for i in range(5, -1, -1):
            month_date = timezone.now() - timedelta(days=30 * i)
            month_name = month_date.strftime('%b')
            months.append(month_name)

            # Simplified revenue calculation
            revenue = Booking.objects.filter(
                created_at__month=month_date.month,
                created_at__year=month_date.year,
                is_paid=True
            ).aggregate(total=Sum('total_price'))['total'] or Decimal('0')

            revenue_data.append({
                'month': month_name,
                'revenue': float(revenue),
            })

        # Bookings data
        bookings_data = []
        for i in range(5, -1, -1):
            month_date = timezone.now() - timedelta(days=30 * i)
            month_name = month_date.strftime('%b')

            count = Booking.objects.filter(
                created_at__month=month_date.month,
                created_at__year=month_date.year
            ).count()

            bookings_data.append({
                'month': month_name,
                'count': count,
            })

        # Monthly performance
        monthly_performance = [
            {
                'metric': 'Revenue Growth',
                'value': 'KES 1.2M',
                'description': 'This month vs last month',
                'growth': 8.5,
            },
            {
                'metric': 'New Customers',
                'value': '45',
                'description': 'New bookings this month',
                'growth': 12.3,
            },
            {
                'metric': 'Trip Completion',
                'value': '98%',
                'description': 'Successful trips rate',
                'growth': 2.1,
            },
            {
                'metric': 'Customer Satisfaction',
                'value': '4.7/5',
                'description': 'Average rating',
                'growth': 0.3,
            },
        ]

        # Customer analytics (simplified)
        customer_data = {
            'total_customers': BookingCustomer.objects.count(),
            'repeat_customers': BookingCustomer.objects.filter(bookings__count__gt=1).distinct().count(),
            'top_countries': [
                {'name': 'Kenya', 'count': 120},
                {'name': 'USA', 'count': 45},
                {'name': 'UK', 'count': 32},
                {'name': 'Germany', 'count': 28},
                {'name': 'France', 'count': 22},
            ]
        }

        data = {
            'revenue_data': revenue_data,
            'bookings_data': bookings_data,
            'monthly_performance': monthly_performance,
            'customer_data': customer_data,
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# =============================================================================
# ACTION VIEWS
# =============================================================================

@csrf_exempt
@require_http_methods(["POST"])
def confirm_booking(request, booking_id):
    """Confirm a booking"""
    try:
        booking = Booking.objects.get(id=booking_id)
        booking.status = 'CONFIRMED'
        booking.save()

        return JsonResponse({
            'success': True,
            'message': 'Booking confirmed successfully',
        })

    except Booking.DoesNotExist:
        return JsonResponse({'error': 'Booking not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def verify_driver(request, driver_id):
    """Verify a driver"""
    try:
        driver = Driver.objects.get(id=driver_id)
        driver.is_verified = True
        driver.save()

        return JsonResponse({
            'success': True,
            'message': 'Driver verified successfully',
        })

    except Driver.DoesNotExist:
        return JsonResponse({'error': 'Driver not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def mark_payment_success(request, payment_id):
    """Mark payment as successful"""
    try:
        payment = Payment.objects.get(id=payment_id)
        payment.status = 'SUCCESS'
        payment.save()

        return JsonResponse({
            'success': True,
            'message': 'Payment marked as successful',
        })

    except Payment.DoesNotExist:
        return JsonResponse({'error': 'Payment not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

from rest_framework.views import APIView
from rest_framework.response import Response

class DashboardView(APIView):
    def get(self, request):
        data = {"status": "ok"}
        return Response(data)