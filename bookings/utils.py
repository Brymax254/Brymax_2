# =============================================================================
# UTILS.PY
# =============================================================================

import json
import logging
import re
import uuid
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional

from django.conf import settings
from django.core.mail import send_mail
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.core.exceptions import ImproperlyConfigured
from .models import Tour, Booking, Payment, PaymentStatus

# Logger
logger = logging.getLogger(__name__)


# =============================================================================
# PHONE NUMBER UTILITIES
# =============================================================================

def normalize_phone_number(phone_number: str) -> str:
    """
    Normalize a phone number to E.164 format.

    Args:
        phone_number: The phone number to normalize

    Returns:
        The normalized phone number in E.164 format
    """
    if not phone_number:
        return ""

    # Remove all non-digit characters
    cleaned = re.sub(r'[^\d]', '', phone_number)

    # Handle Kenyan numbers (assume Kenya if country code not specified)
    if cleaned.startswith('0') and len(cleaned) == 10:  # Local format like 0712345678
        return '+254' + cleaned[1:]
    elif cleaned.startswith('7') and len(cleaned) == 9:  # Local format without leading 0
        return '+254' + cleaned
    elif cleaned.startswith('254') and len(cleaned) == 12:  # International format without +
        return '+' + cleaned
    elif cleaned.startswith('+254') and len(cleaned) == 13:  # Already in E.164 format
        return cleaned

    # For other countries, just add + if it's missing and seems to be a full number
    if len(cleaned) >= 10 and not cleaned.startswith('+'):
        return '+' + cleaned

    return phone_number


def mask_phone(phone: str) -> str:
    """
    Mask a phone number for privacy.

    Args:
        phone: Phone number to mask

    Returns:
        Masked phone number
    """
    if not phone or len(phone) < 4:
        return phone

    return phone[:2] + '*' * (len(phone) - 4) + phone[-2:]


# =============================================================================
# EMAIL UTILITIES
# =============================================================================

def mask_email(email: str) -> str:
    """
    Mask an email address for privacy.

    Args:
        email: Email address to mask

    Returns:
        Masked email address
    """
    if not email or '@' not in email:
        return email

    username, domain = email.split('@', 1)
    if len(username) <= 2:
        masked_username = username[0] + '*' * (len(username) - 1)
    else:
        masked_username = username[:2] + '*' * (len(username) - 2)

    return f"{masked_username}@{domain}"


def send_payment_confirmation_email(payment):
    """
    Send a payment confirmation email to the customer.

    Args:
        payment: Payment model instance
    """
    try:
        # Get customer email
        email = payment.guest_email
        if not email:
            logger.warning(f"No email available for payment {payment.id}")
            return

        # Prepare email context
        context = {
            'payment': payment,
            'tour': payment.tour,
            'booking': payment.booking
        }

        # Render email templates
        subject = render_to_string('payments/email/confirmation_subject.txt', context).strip()
        text_body = render_to_string('payments/email/confirmation_email.txt', context)
        html_body = render_to_string('payments/email/confirmation_email.html', context)

        # Send email
        send_mail(
            subject,
            text_body,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            html_message=html_body,
            fail_silently=False
        )

        logger.info(f"Payment confirmation email sent to {email} for payment {payment.id}")

    except Exception as e:
        logger.exception(f"Error sending payment confirmation email for payment {payment.id}: {e}")


# =============================================================================
# HTTP UTILITIES
# =============================================================================

def get_client_ip(request):
    """
    Get the client's IP address from the request.

    Args:
        request: HttpRequest object

    Returns:
        Client IP address as string
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def create_error_response(message: str, errors: Dict = None, status: int = 400):
    """
    Create a standardized error response.

    Args:
        message: Error message
        errors: Optional error details dictionary
        status: HTTP status code

    Returns:
        JsonResponse with error information
    """
    response_data = {
        "status": "error",
        "message": message
    }

    if errors:
        response_data["errors"] = errors

    return JsonResponse(response_data, status=status)


def create_success_response(data: Dict = None, message: str = "Success"):
    """
    Create a standardized success response.

    Args:
        data: Optional response data
        message: Success message

    Returns:
        JsonResponse with success information
    """
    response_data = {
        "status": "success",
        "message": message
    }

    if data:
        response_data.update(data)

    return JsonResponse(response_data)


# =============================================================================
# PAYMENT UTILITIES
# =============================================================================

def log_payment_event(event_type: str, payment_id: str, **kwargs):
    """
    Log a payment-related event.

    Args:
        event_type: Type of event
        payment_id: Payment ID
        **kwargs: Additional event data
    """
    logger.info(
        f"Payment event: {event_type} for payment {payment_id}",
        extra={"event_type": event_type, "payment_id": payment_id, **kwargs}
    )


def validate_payment_data(form_data: Dict, tour) -> Dict:
    """
    Validate payment form data.

    Args:
        form_data: Form data dictionary
        tour: Tour model instance

    Returns:
        Dictionary of validation errors
    """
    errors = {}

    # Validate required fields
    required_fields = ['full_name', 'email', 'phone', 'travel_date']
    for field in required_fields:
        if not form_data.get(field):
            errors[field] = "This field is required."

    # Validate email format
    email = form_data.get('email')
    if email and not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        errors['email'] = "Please enter a valid email address."

    # Validate phone number
    phone = form_data.get('phone')
    if phone:
        normalized = normalize_phone_number(phone)
        if not re.match(r'^\+\d{6,15}$', normalized):
            errors['phone'] = "Please enter a valid phone number in international format."

    # Validate travel date
    travel_date_str = form_data.get('travel_date')
    if travel_date_str:
        try:
            travel_date = datetime.strptime(travel_date_str, '%Y-%m-%d').date()
            if travel_date < date.today():
                errors['travel_date'] = "Travel date cannot be in the past."

            # Check if within max advance booking period
            days_ahead = (travel_date - date.today()).days
            if hasattr(tour, 'max_advance_booking_days') and days_ahead > tour.max_advance_booking_days:
                errors[
                    'travel_date'] = f"Bookings can only be made up to {tour.max_advance_booking_days} days in advance."

        except ValueError:
            errors['travel_date'] = "Please enter a valid date in YYYY-MM-DD format."

    # Validate participant counts
    adults = form_data.get('adults', 1)
    children = form_data.get('children', 0)

    try:
        adults = int(adults)
        if adults < 1:
            errors['adults'] = "At least one adult is required."
    except (ValueError, TypeError):
        errors['adults'] = "Please enter a valid number of adults."

    try:
        children = int(children)
        if children < 0:
            errors['children'] = "Number of children cannot be negative."
    except (ValueError, TypeError):
        errors['children'] = "Please enter a valid number of children."

    # Validate group size
    if 'adults' not in errors and 'children' not in errors:
        total_passengers = adults + children
        max_group_size = getattr(tour, 'max_group_size', 20)  # Default to 20 if not defined
        min_group_size = getattr(tour, 'min_group_size', 1)  # Default to 1 if not defined

        if total_passengers > max_group_size:
            errors['group_size'] = f"Maximum group size is {max_group_size}."
        if total_passengers < min_group_size:
            errors['group_size'] = f"Minimum group size is {min_group_size}."

    return errors


def create_payment_record(tour, form_data, total_amount):
    """
    Create a payment record.

    Args:
        tour: Tour model instance
        form_data: Form data dictionary
        total_amount: Total payment amount

    Returns:
        Payment model instance
    """
    # Create payment record
    payment = Payment.objects.create(
        tour=tour,
        amount=total_amount,
        guest_full_name=form_data["full_name"],
        guest_email=form_data["email"],
        guest_phone=form_data["phone"],
        adults=form_data.get("adults", 1),
        children=form_data.get("children", 0),
        travel_date=datetime.strptime(form_data["travel_date"], '%Y-%m-%d').date(),
        reference=f"PAY-{uuid.uuid4().hex[:6]}",
        status=PaymentStatus.PENDING
    )

    return payment


# =============================================================================
# TOUR UTILITIES
# =============================================================================

def get_tour_pricing(tour, adults=1, children=0):
    """
    Get pricing information for a tour.

    Args:
        tour: Tour model instance
        adults: Number of adults
        children: Number of children

    Returns:
        Dictionary with pricing information
    """
    base_price = tour.price_per_person
    discount_price = getattr(tour, 'discount_price', None) if getattr(tour, 'has_discount', False) else None

    # Calculate total price
    total_passengers = adults + children
    total_base_price = base_price * total_passengers

    # Apply discount if available
    if discount_price:
        total_discount_price = discount_price * total_passengers
        discount_amount = total_base_price - total_discount_price
        discount_percentage = getattr(tour, 'discount_percentage', 0)
    else:
        total_discount_price = None
        discount_amount = None
        discount_percentage = 0

    # Check for group discounts
    group_discount_threshold = 5  # Apply group discount for 5+ people
    group_discount_percentage = 10  # 10% group discount

    if total_passengers >= group_discount_threshold:
        if discount_price:
            # Apply group discount on already discounted price
            group_discount_amount = total_discount_price * (group_discount_percentage / 100)
            final_price = total_discount_price - group_discount_amount
            total_discount_percentage = discount_percentage + group_discount_percentage
        else:
            # Apply group discount on base price
            group_discount_amount = total_base_price * (group_discount_percentage / 100)
            final_price = total_base_price - group_discount_amount
            total_discount_percentage = group_discount_percentage
    else:
        final_price = total_discount_price if discount_price else total_base_price

    return {
        'base_price_per_person': float(base_price),
        'discount_price_per_person': float(discount_price) if discount_price else None,
        'total_base_price': float(total_base_price),
        'total_discount_price': float(total_discount_price) if discount_price else None,
        'final_price': float(final_price),
        'discount_percentage': discount_percentage,
        'group_discount_applied': total_passengers >= group_discount_threshold,
        'total_passengers': total_passengers,
        'currency': 'KES'
    }


def check_tour_availability(tour, travel_date):
    """
    Check if a tour is available on a specific date.

    Args:
        tour: Tour model instance
        travel_date: Date to check

    Returns:
        Dictionary with availability information
    """
    # Validate the date
    if travel_date < date.today():
        return {
            'is_available': False,
            'reason': 'Date is in the past'
        }

    # Check if within max advance booking period
    days_ahead = (travel_date - date.today()).days
    if hasattr(tour, 'max_advance_booking_days') and days_ahead > tour.max_advance_booking_days:
        return {
            'is_available': False,
            'reason': f'Bookings can only be made up to {tour.max_advance_booking_days} days in advance'
        }

    # Get all bookings for this tour on the specified date
    bookings = Booking.objects.filter(
        tour=tour,
        status__in=['CONFIRMED', 'PENDING'],
        travel_date=travel_date
    )

    # Calculate total booked passengers
    total_booked = sum(booking.num_adults + booking.num_children for booking in bookings)

    # Check availability
    max_group_size = getattr(tour, 'max_group_size', 20)  # Default to 20 if not defined
    if total_booked >= max_group_size:
        return {
            'is_available': False,
            'reason': 'Tour is fully booked',
            'available_spots': 0,
            'total_booked': total_booked
        }

    return {
        'is_available': True,
        'available_spots': max_group_size - total_booked,
        'total_booked': total_booked
    }


# =============================================================================
# CONFIGURATION VALIDATION
# =============================================================================

def validate_paystack_config():
    """Validate Paystack configuration on startup."""
    required_settings = ['SECRET_KEY', 'PUBLIC_KEY', 'CALLBACK_URL']
    paystack_config = getattr(settings, 'PAYSTACK', {})

    missing = [key for key in required_settings if not paystack_config.get(key)]
    if missing:
        raise ImproperlyConfigured(f"Missing Paystack settings: {missing}")

    # Validate callback URL format
    callback_url = paystack_config.get('CALLBACK_URL')
    if not callback_url or not callback_url.startswith(('http://', 'https://')):
        raise ImproperlyConfigured("PAYSTACK_CALLBACK_URL must be a valid URL")


# =============================================================================
# CLEANUP UTILITIES
# =============================================================================

def cleanup_expired_payments():
    """Utility function to clean up expired pending payments."""
    from django.utils import timezone

    expiry_time = timezone.now() - timedelta(hours=24)  # 24 hours expiry

    expired_payments = Payment.objects.filter(
        status=PaymentStatus.PENDING,
        created_at__lt=expiry_time
    )

    count = expired_payments.count()
    if count > 0:
        expired_payments.update(status=PaymentStatus.FAILED)
        logger.info(f"Cleaned up {count} expired pending payments")

    return count