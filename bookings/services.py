# =============================================================================
# IMPORTS
# =============================================================================
import logging
from datetime import date, timedelta
import uuid
from django.conf import settings
from django.utils import timezone
import requests
from .models import Tour, Booking, Payment, BookingCustomer

# Logger
logger = logging.getLogger(__name__)


# =============================================================================
# PAYSTACK SERVICE
# =============================================================================
class PaystackService:
    """Service class for handling Paystack payment operations."""

    @staticmethod
    def initialize_transaction(payment, callback_url, metadata=None):
        """
        Initialize a Paystack transaction and save reference to DB.
        """
        try:
            url = "https://api.paystack.co/transaction/initialize"
            headers = {
                "Authorization": f"Bearer {settings.PAYSTACK['SECRET_KEY']}",
                "Content-Type": "application/json"
            }

            # Ensure reference exists
            if not payment.reference:
                payment.reference = f"PAY-{payment.id}-{uuid.uuid4().hex[:6]}"
                payment.save(update_fields=["reference"])

            # Prepare customer data (fallback to placeholder if empty)
            customer_email = payment.guest_email or (
                payment.booking.booking_customer.email
                if payment.booking and payment.booking.booking_customer else "test@example.com"
            )
            customer_name = payment.guest_full_name or (
                payment.booking.booking_customer.full_name
                if payment.booking and payment.booking.booking_customer else "Guest User"
            )
            customer_phone = payment.guest_phone or (
                payment.booking.booking_customer.phone_number
                if payment.booking and payment.booking.booking_customer else ""
            )

            # Prepare metadata
            transaction_metadata = {
                "payment_id": str(payment.id),
                "tour_id": str(payment.tour.id) if payment.tour else None,
                "booking_id": str(payment.booking.id) if payment.booking else None,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "customer_phone": customer_phone,
            }

            if metadata:
                transaction_metadata.update(metadata)

            # Payload
            payload = {
                "amount": int(payment.amount * 100),  # KES -> kobo
                "email": customer_email,
                "reference": payment.reference,
                "callback_url": callback_url,
                "metadata": transaction_metadata,
            }

            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response_data = response.json()

            if response_data.get("status"):
                logger.info(f"Paystack init successful: {response_data}")
                return response_data, payment.reference
            else:
                logger.error(f"Paystack init failed: {response_data}")
                return response_data, None

        except Exception as e:
            logger.exception(f"Error initializing Paystack transaction: {e}")
            return {"status": False, "message": str(e)}, None

    @staticmethod
    def verify_transaction(reference):
        """
        Verify a Paystack transaction and update DB.
        """
        try:
            url = f"https://api.paystack.co/transaction/verify/{reference}"
            headers = {
                "Authorization": f"Bearer {settings.PAYSTACK['SECRET_KEY']}"
            }

            response = requests.get(url, headers=headers, timeout=30)
            data = response.json()

            # Update payment in DB if it exists
            try:
                payment = Payment.objects.get(reference=reference)
            except Payment.DoesNotExist:
                logger.error(f"No payment found for reference {reference}")
                return data

            if data.get("status") and data["data"]["status"] == "success":
                payment.status = "SUCCESS"
                payment.paid_at = timezone.now()
                payment.save(update_fields=["status", "paid_at"])
                logger.info(f"Payment {reference} marked as SUCCESS")
            else:
                payment.status = "FAILED"
                payment.save(update_fields=["status"])
                logger.warning(f"Payment {reference} marked as FAILED")

            return data

        except Exception as e:
            logger.exception(f"Error verifying Paystack transaction: {e}")
            return {"status": False, "message": str(e)}


# =============================================================================
# PAYMENT SESSION MANAGER
# =============================================================================
class PaymentSessionManager:
    """Service class for managing payment sessions."""

    def __init__(self, session):
        self.session = session

    def set_pending_payment(self, payment):
        """Store a pending payment in the session."""
        self.session['pending_payment_id'] = str(payment.id)
        self.session.modified = True

    def get_pending_payment(self):
        """Retrieve the pending payment from session, if it exists."""
        payment_id = self.session.get('pending_payment_id')
        if payment_id:
            try:
                return Payment.objects.get(id=payment_id)
            except Payment.DoesNotExist:
                self.clear_payment_session()
        return None

    def clear_payment_session(self):
        """Remove any pending payment from the session."""
        if 'pending_payment_id' in self.session:
            del self.session['pending_payment_id']
            self.session.modified = True

    def has_pending_payment(self):
        """Check if a valid pending payment exists in session."""
        return self.get_pending_payment() is not None


# =============================================================================
# TOUR AVAILABILITY SERVICE
# =============================================================================
class TourAvailabilityService:
    """Service class for checking tour availability."""

    @staticmethod
    def get_available_dates(tour, months_ahead=6):
        """
        Get available dates for a tour within the given timeframe.
        """
        available_dates = []
        start_date = date.today()
        end_date = start_date + timedelta(days=30 * months_ahead)

        bookings = Booking.objects.filter(
            tour=tour,
            status__in=['CONFIRMED', 'PENDING'],
            travel_date__gte=start_date,
            travel_date__lte=end_date
        )

        booked_dates = {}
        for booking in bookings:
            date_str = booking.travel_date.isoformat()
            # Use correct field names for adults and children
            booked_dates[date_str] = booked_dates.get(date_str, 0) + booking.adults + booking.children

        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.isoformat()

            if current_date < date.today():
                current_date += timedelta(days=1)
                continue

            days_ahead = (current_date - date.today()).days
            if hasattr(tour, 'max_advance_booking_days') and days_ahead > tour.max_advance_booking_days:
                current_date += timedelta(days=1)
                continue

            booked_passengers = booked_dates.get(date_str, 0)
            if hasattr(tour, 'max_group_size') and booked_passengers < tour.max_group_size:
                available_dates.append({
                    'date': current_date.isoformat(),
                    'formatted_date': current_date.strftime('%A, %B %d, %Y'),
                    'available_spots': tour.max_group_size - booked_passengers,
                    'is_fully_booked': booked_passengers >= tour.max_group_size,
                    'has_limited_availability': (tour.max_group_size - booked_passengers) <= 2
                })

            current_date += timedelta(days=1)

        return available_dates

    @staticmethod
    def check_availability(tour, travel_date, adults=1, children=0):
        """
        Check if a tour is available on a specific date.
        """
        if travel_date < date.today():
            return {'is_available': False, 'reason': 'Date is in the past'}

        days_ahead = (travel_date - date.today()).days
        if hasattr(tour, 'max_advance_booking_days') and days_ahead > tour.max_advance_booking_days:
            return {
                'is_available': False,
                'reason': f'Bookings can only be made up to {tour.max_advance_booking_days} days in advance'
            }

        bookings = Booking.objects.filter(
            tour=tour,
            status__in=['CONFIRMED', 'PENDING'],
            travel_date=travel_date
        )

        # Use correct field names for adults and children
        total_booked = sum(b.adults + b.children for b in bookings)
        total_passengers = adults + children

        if hasattr(tour, 'max_group_size') and total_booked + total_passengers > tour.max_group_size:
            return {
                'is_available': False,
                'reason': f'Only {tour.max_group_size - total_booked} spots available',
                'available_spots': tour.max_group_size - total_booked,
                'total_booked': total_booked
            }

        if hasattr(tour, 'min_group_size') and total_passengers < tour.min_group_size:
            return {
                'is_available': True,
                'warning': f'Minimum group size is {tour.min_group_size}',
                'available_spots': tour.max_group_size - total_booked,
                'total_booked': total_booked
            }

        return {
            'is_available': True,
            'available_spots': tour.max_group_size - total_booked if hasattr(tour, 'max_group_size') else 100,
            # Default if not set
            'total_booked': total_booked
        }

    @staticmethod
    def get_tour_pricing(tour, adults=1, children=0):
        """
        Get pricing information for a tour.
        """
        base_price = tour.price_per_person
        discount_price = getattr(tour, 'discount_price', None)
        has_discount = getattr(tour, 'has_discount', False)
        discount_percentage = getattr(tour, 'discount_percentage', 0)

        total_passengers = adults + children
        total_base_price = base_price * total_passengers

        if has_discount and discount_price:
            total_discount_price = discount_price * total_passengers
        else:
            total_discount_price = None
            discount_percentage = 0

        group_discount_threshold = 5
        group_discount_percentage = 10

        if total_passengers >= group_discount_threshold:
            if total_discount_price:
                group_discount_amount = total_discount_price * (group_discount_percentage / 100)
                final_price = total_discount_price - group_discount_amount
                total_discount_percentage += group_discount_percentage
            else:
                group_discount_amount = total_base_price * (group_discount_percentage / 100)
                final_price = total_base_price - group_discount_amount
                total_discount_percentage = group_discount_percentage
        else:
            final_price = total_discount_price if total_discount_price else total_base_price

        return {
            'base_price_per_person': float(base_price),
            'discount_price_per_person': float(discount_price) if discount_price else None,
            'total_base_price': float(total_base_price),
            'total_discount_price': float(total_discount_price) if total_discount_price else None,
            'final_price': float(final_price),
            'discount_percentage': discount_percentage,
            'group_discount_applied': total_passengers >= group_discount_threshold,
            'total_passengers': total_passengers,
            'currency': 'KES'
        }