# =============================================================================
# IMPORTS
# =============================================================================

# Standard library
import json
import uuid
import logging
import hmac
import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any
from datetime import timedelta, datetime

# Third-party
import requests

# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.db import models, transaction
from django.http import HttpResponse, JsonResponse, HttpResponseNotAllowed
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.generic import DetailView

# Local apps
from .models import (
    Tour, Destination, Video, Booking, Payment, ContactMessage, Trip, PaymentStatus,
    Driver, Customer
)
from .forms import GuestCheckoutForm, TourForm

# Logger
logger = logging.getLogger(__name__)


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


# Validate configuration on module load
try:
    validate_paystack_config()
except ImproperlyConfigured as e:
    logger.error(f"Paystack configuration error: {e}")
    if not settings.DEBUG:
        raise


# =============================================================================
# SERVICES & UTILITIES
# =============================================================================

class PaystackService:
    """Service class for Paystack API operations."""

    def __init__(self):
        self.secret_key = settings.PAYSTACK['SECRET_KEY']
        self.base_url = "https://api.paystack.co"
        self.timeout = 15

    def _get_headers(self):
        """Get standard headers for Paystack API."""
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    def _build_metadata(self, payment):
        """Build metadata for Paystack transaction."""
        return {
            "payment_id": str(payment.id),
            "tour_id": payment.tour.id,
            "custom_fields": [
                {
                    "display_name": "Tour Name",
                    "variable_name": "tour_name",
                    "value": payment.tour.title
                },
                {
                    "display_name": "Customer Name",
                    "variable_name": "customer_name",
                    "value": payment.guest_full_name
                }
            ]
        }

    def initialize_transaction(self, payment, callback_url):
        """Initialize Paystack transaction."""
        reference = f"PAY-{payment.id}-{uuid.uuid4().hex[:8]}"

        data = {
            "reference": reference,
            "amount": int(payment.amount * 100),  # Convert to kobo
            "email": payment.guest_email,
            "callback_url": callback_url,
            "metadata": self._build_metadata(payment)
        }

        try:
            response = requests.post(
                f"{self.base_url}/transaction/initialize",
                json=data,
                headers=self._get_headers(),
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json(), reference
        except requests.RequestException as e:
            logger.error(f"Paystack initialization error: {e}")
            raise

    def verify_transaction(self, reference):
        """Verify transaction with Paystack."""
        try:
            response = requests.get(
                f"{self.base_url}/transaction/verify/{reference}",
                headers=self._get_headers(),
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Paystack verification error: {e}")
            raise


class PaymentSessionManager:
    """Manage payment-related session data."""

    def __init__(self, session):
        self.session = session

    def set_pending_payment(self, payment):
        """Set pending payment in session."""
        self.session.update({
            "pending_payment_id": str(payment.pk),
            "guest_email": payment.guest_email,
            "guest_phone": payment.guest_phone,
            "payment_initiated_at": timezone.now().isoformat()
        })
        self.session.save()

    def get_pending_payment(self):
        """Get pending payment from session."""
        payment_id = self.session.get("pending_payment_id")
        if payment_id:
            try:
                return Payment.objects.get(id=payment_id, status=PaymentStatus.PENDING)
            except (Payment.DoesNotExist, ValueError):
                self.clear_payment_session()
        return None

    def clear_payment_session(self):
        """Clear payment-related session data."""
        keys_to_remove = [
            "pending_payment_id", "guest_email",
            "guest_phone", "payment_initiated_at"
        ]
        for key in keys_to_remove:
            self.session.pop(key, None)

    def has_pending_payment(self):
        """Check if there's a pending payment in session."""
        return self.session.get("pending_payment_id") is not None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def normalize_phone_number(phone: str) -> Optional[str]:
    """Convert a phone number to E.164 format for Kenya (+254...)."""
    if not phone:
        return None

    phone = re.sub(r'[^\d+]', '', phone.strip())

    if phone.startswith("0"):
        return "+254" + phone[1:]
    elif phone.startswith("254"):
        return "+" + phone
    elif phone.startswith("+254"):
        return phone
    elif phone.startswith("+"):
        return phone

    return None


def get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def mask_email(email: str) -> str:
    """Mask email address for logging."""
    if not email or '@' not in email:
        return "***@***"
    name, domain = email.split('@', 1)
    return f"{name[:2]}***@{domain}"


def mask_phone(phone: str) -> str:
    """Mask phone number for logging."""
    if not phone or len(phone) < 4:
        return "*******"
    return f"***{phone[-4:]}"


def log_payment_event(event_type: str, payment_id: str, **kwargs) -> None:
    """Log payment events with masked sensitive data."""
    log_data = {
        "event": event_type,
        "payment_id": payment_id,
        "timestamp": timezone.now().isoformat(),
    }

    # Mask sensitive data
    if "email" in kwargs:
        log_data["email"] = mask_email(kwargs["email"])
    if "phone" in kwargs:
        log_data["phone"] = mask_phone(kwargs["phone"])

    # Add other non-sensitive data
    for key, value in kwargs.items():
        if key not in ["email", "phone"]:
            log_data[key] = value

    logger.info(f"Payment event: {json.dumps(log_data)}")


def create_error_response(message: str, errors: Dict = None, status: int = 400) -> JsonResponse:
    """Create standardized error response."""
    response_data = {
        'success': False,
        'message': message,
        'timestamp': timezone.now().isoformat()
    }
    if errors:
        response_data['errors'] = errors
    return JsonResponse(response_data, status=status)


def create_success_response(data: Dict = None, message: str = "Success") -> JsonResponse:
    """Create standardized success response."""
    response_data = {
        'success': True,
        'message': message,
        'timestamp': timezone.now().isoformat()
    }
    if data:
        response_data.update(data)
    return JsonResponse(response_data)


def validate_payment_data(form_data: Dict, tour: Tour) -> Dict[str, str]:
    """Validate payment form data."""
    errors = {}

    # Validate required fields
    required_fields = ['full_name', 'email', 'phone']
    for field in required_fields:
        if not form_data.get(field, '').strip():
            errors[field] = f'{field.replace("_", " ").title()} is required'

    # Validate email format
    email = form_data.get('email', '')
    if email and not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        errors['email'] = 'Invalid email format'

    # Validate phone number
    phone = form_data.get('phone', '')
    if phone and not normalize_phone_number(phone):
        errors['phone'] = 'Invalid phone number format'

    # Validate travel date
    travel_date = form_data.get('travel_date')
    if travel_date and travel_date < timezone.now().date():
        errors['travel_date'] = 'Travel date cannot be in the past'

    # Validate participant counts
    try:
        adults = int(form_data.get('adults', 1))
        children = int(form_data.get('children', 0))

        if adults < 1:
            errors['adults'] = 'At least one adult is required'

        if hasattr(tour, 'max_participants') and tour.max_participants:
            if adults + children > tour.max_participants:
                errors['participants'] = f'Maximum {tour.max_participants} participants allowed'
    except (ValueError, TypeError):
        errors['participants'] = 'Invalid participant count'

    return errors


def create_payment_record(tour: Tour, form_data: Dict, total_amount: Decimal) -> Payment:
    """Create a standardized payment record."""
    return Payment.objects.create(
        tour=tour,
        amount=total_amount,
        currency="KES",
        provider="PAYSTACK",
        status=PaymentStatus.PENDING,
        guest_full_name=form_data["full_name"],
        guest_email=form_data["email"],
        guest_phone=normalize_phone_number(form_data["phone"]),
        adults=form_data.get("adults", 1),
        children=form_data.get("children", 0),
        travel_date=form_data.get("travel_date", timezone.now().date()),
        description=f"Tour {tour.title} booking",
    )


def send_payment_confirmation_email(payment: Payment) -> None:
    """Send email confirmation to guest after successful payment."""
    subject = f"Payment Confirmation - {payment.tour.title}"
    message = (
        f"Dear {payment.guest_full_name},\n\n"
        f"We have received your payment of KES {payment.amount_paid} "
        f"for \"{payment.tour.title}\".\n\n"
        f"Booking Details:\n"
        f"- Adults: {payment.adults}\n"
        f"- Children: {payment.children}\n"
        f"- Travel Date: {payment.travel_date}\n"
        f"- Reference: {payment.reference}\n\n"
        "Thank you for booking with Safari Adventures Kenya!\n\n"
        "Best regards,\n"
        "Safari Adventures Kenya Team"
    )

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [payment.guest_email],
            fail_silently=False
        )
        logger.info(f"Sent payment confirmation email to {mask_email(payment.guest_email)}")
    except Exception as e:
        logger.exception(f"Failed to send confirmation email: {e}")


# =============================================================================
# DECORATORS
# =============================================================================

def driver_required(view_func):
    """Decorator to ensure user is logged in and has a driver profile."""

    @login_required
    def _wrapped(request, *args, **kwargs):
        if not hasattr(request.user, "driver"):
            messages.error(request, "You must log in as a driver.")
            return redirect("driver_login")
        return view_func(request, *args, **kwargs)

    return _wrapped


# =============================================================================
# PUBLIC PAGES VIEWS
# =============================================================================

def home(request):
    """Render homepage."""
    featured_tours = Tour.objects.filter(featured=True, is_approved=True, available=True)[:6]
    recent_destinations = Destination.objects.filter(is_active=True)[:4]

    context = {
        "featured_tours": featured_tours,
        "recent_destinations": recent_destinations,
    }
    return render(request, "home.html", context)


def book_online(request):
    """Render Book Online landing page."""
    tours = Tour.objects.filter(is_approved=True, available=True)[:8]
    context = {"tours": tours}
    return render(request, "book_online.html", context)


def nairobi_transfers(request):
    """Render Nairobi airport transfers and taxi information page."""
    return render(request, "nairobi_transfers.html")


def excursions(request):
    """Render Excursions listing page."""
    excursions = Tour.objects.filter(
        category__in=['EXCURSION', 'ADVENTURE'],
        is_approved=True,
        available=True
    )
    context = {"excursions": excursions}
    return render(request, "excursions.html", context)


def tours(request):
    """Render Public Tours page including trips, videos, and destinations."""
    context = {
        "tours": Tour.objects.filter(is_approved=True, available=True)
            .select_related("created_by", "approved_by")
            .order_by("-created_at"),
        "trips": Trip.objects.all().order_by("-created_at"),
        "videos": Video.objects.all().order_by("-created_at"),
        "destinations": Destination.objects.all().order_by("-created_at"),
    }
    return render(request, "tours.html", context)

def contact(request):
    """Render Contact page."""
    return render(request, "contact.html")


def terms(request):
    """Render Terms and Conditions page."""
    return render(request, "terms.html")


def about(request):
    """Render About Us page."""
    return render(request, "about.html")


# =============================================================================
# TOUR DETAIL VIEWS
# =============================================================================

class TourDetailView(DetailView):
    """Detailed view for a specific tour."""
    model = Tour
    template_name = 'tours/detail.html'
    context_object_name = 'tour'

    def get_queryset(self):
        return Tour.objects.filter(is_approved=True, available=True).select_related('destination')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = GuestCheckoutForm()
        context['public_key'] = settings.PAYSTACK['PUBLIC_KEY']
        context['today'] = timezone.now().date()

        # Add related tours
        context['related_tours'] = Tour.objects.filter(
            destination=self.object.destination,
            is_approved=True,
            available=True
        ).exclude(id=self.object.id)[:3]

        return context


# =============================================================================
# PAYMENT PROCESSING VIEWS
# =============================================================================

@require_http_methods(["GET", "POST"])
def tour_payment(request, tour_id):
    """Handle checkout form and Paystack payment for a specific tour."""
    tour = get_object_or_404(Tour, id=tour_id)
    session_manager = PaymentSessionManager(request.session)
    paystack_service = PaystackService()

    if request.method == "POST":
        form = GuestCheckoutForm(request.POST)

        if form.is_valid():
            form_data = form.cleaned_data

            # Additional validation
            validation_errors = validate_payment_data(form_data, tour)
            if validation_errors:
                return create_error_response("Validation failed", validation_errors)

            # Calculate total amount
            total_amount = tour.price_per_person * (
                    form_data.get("adults", 1) + form_data.get("children", 0)
            )

            try:
                with transaction.atomic():
                    # Check for existing pending payment
                    existing_payment = Payment.objects.filter(
                        tour=tour,
                        guest_email=form_data["email"],
                        status=PaymentStatus.PENDING
                    ).first()

                    if existing_payment:
                        payment = existing_payment
                        session_manager.set_pending_payment(payment)

                        log_payment_event(
                            "existing_pending_payment",
                            str(payment.pk),
                            email=form_data["email"],
                            phone=form_data["phone"],
                            tour_id=tour_id
                        )

                        return create_success_response({
                            'payment_id': str(payment.pk),
                            'message': 'Existing payment found'
                        })

                    # Create new payment
                    payment = create_payment_record(tour, form_data, total_amount)

                    # Initialize Paystack transaction
                    response_data, reference = paystack_service.initialize_transaction(
                        payment, settings.PAYSTACK['CALLBACK_URL']
                    )

                    if response_data.get('status'):
                        # Save reference to payment
                        payment.transaction_id = reference
                        payment.save()

                        # Update session
                        session_manager.set_pending_payment(payment)

                        log_payment_event(
                            "paystack_initialized",
                            str(payment.pk),
                            email=form_data["email"],
                            phone=form_data["phone"],
                            reference=reference
                        )

                        return create_success_response({
                            'authorization_url': response_data['data']['authorization_url'],
                            'reference': reference,
                            'payment_id': str(payment.pk)
                        })
                    else:
                        # Delete payment if initialization failed
                        payment.delete()
                        error_msg = response_data.get('message', 'Payment initialization failed')

                        log_payment_event(
                            "paystack_init_failed",
                            str(payment.pk),
                            error=error_msg
                        )

                        return create_error_response(error_msg)

            except Exception as e:
                logger.exception(f"Payment processing error: {e}")
                log_payment_event(
                    "payment_processing_error",
                    "unknown",
                    error=str(e),
                    tour_id=tour_id
                )
                return create_error_response('Payment processing error. Please try again.')

        else:
            log_payment_event(
                "form_validation_failed",
                "unknown",
                errors=form.errors.as_json(),
                tour_id=tour_id
            )
            return create_error_response(
                'Please correct the errors below.',
                {'errors': form.errors}
            )

    # GET request - render form
    form = GuestCheckoutForm()
    payment = session_manager.get_pending_payment()

    if payment and payment.tour_id != tour.id:
        # Clear session if payment is for different tour
        session_manager.clear_payment_session()
        payment = None

    return render(
        request,
        "payments/tour_payment.html",
        {
            "tour": tour,
            "form": form,
            "payment": payment,
            "public_key": settings.PAYSTACK['PUBLIC_KEY'],
            "is_guest_payment": session_manager.has_pending_payment(),
            "today": timezone.now().date(),
        },
    )


@require_POST
def guest_checkout(request, tour_id):
    """Create a pending guest payment and booking, store in session."""
    tour = get_object_or_404(Tour, id=tour_id)
    session_manager = PaymentSessionManager(request.session)

    try:
        form_data = {
            'full_name': request.POST.get("full_name", "").strip(),
            'email': request.POST.get("email", "").strip(),
            'phone': request.POST.get("phone", "").strip(),
            'adults': int(request.POST.get("adults", 1)),
            'children': int(request.POST.get("children", 0)),
            'travel_date': request.POST.get("travel_date", timezone.now().date()),
        }

        # Validate form data
        validation_errors = validate_payment_data(form_data, tour)
        if validation_errors:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return create_error_response("Validation failed", validation_errors)
            messages.error(request, "Please correct the form errors.")
            return redirect("tour_payment", tour_id=tour_id)

        total = tour.price_per_person * (form_data['adults'] + form_data['children'])

        with transaction.atomic():
            payment = create_payment_record(tour, form_data, total)
            session_manager.set_pending_payment(payment)

            log_payment_event(
                "guest_checkout",
                str(payment.pk),
                email=form_data['email'],
                phone=form_data['phone'],
                amount=total,
                tour_id=tour_id
            )

            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return create_success_response({"payment_id": str(payment.pk)})

            return redirect("tour_payment", tour_id=tour_id)

    except (KeyError, ValueError, InvalidOperation) as exc:
        logger.exception("Guest checkout error: %s", exc)
        log_payment_event(
            "guest_checkout_error",
            "unknown",
            error=str(exc),
            tour_id=tour_id
        )

        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return create_error_response(str(exc))

        messages.error(request, "Checkout error. Please try again.")
        return redirect("tour_payment", tour_id=tour_id)


@csrf_exempt
@require_http_methods(["POST"])
def process_guest_info(request):
    """Process guest information via AJAX and return booking details."""
    try:
        # Extract form data
        form_data = {
            'full_name': request.POST.get('full_name', '').strip(),
            'email': request.POST.get('email', '').strip(),
            'phone': request.POST.get('phone', '').strip(),
            'adults': int(request.POST.get('adults', 1)),
            'children': int(request.POST.get('children', 0)),
            'travel_date': request.POST.get('travel_date'),
        }

        tour_id = request.POST.get('tour_id')
        total_amount = request.POST.get('total_amount')

        # Validate required fields
        if not all([form_data['full_name'], form_data['email'], form_data['phone'], tour_id]):
            missing = [k for k, v in form_data.items() if not v] + ([] if tour_id else ['tour_id'])
            return create_error_response(f'Missing required fields: {", ".join(missing)}')

        # Get tour
        tour = get_object_or_404(Tour, id=tour_id)

        # Validate form data
        validation_errors = validate_payment_data(form_data, tour)
        if validation_errors:
            return create_error_response("Validation failed", validation_errors)

        # Calculate or validate total amount
        calculated_amount = tour.price_per_person * (form_data['adults'] + form_data['children'])
        if total_amount and abs(float(total_amount) - float(calculated_amount)) > 0.01:
            return create_error_response("Amount mismatch detected")

        with transaction.atomic():
            # Check for existing pending payment
            payment = Payment.objects.filter(
                tour=tour,
                guest_email=form_data['email'],
                status=PaymentStatus.PENDING
            ).first()

            if not payment:
                # Create new payment record
                payment = create_payment_record(tour, form_data, calculated_amount)
                created = True
            else:
                created = False

            # Update session
            session_manager = PaymentSessionManager(request.session)
            session_manager.set_pending_payment(payment)

            log_payment_event(
                "guest_info_processed",
                str(payment.pk),
                email=form_data['email'],
                phone=form_data['phone'],
                created=created
            )

            return create_success_response({
                'payment_id': str(payment.pk),
                'amount': float(calculated_amount),
                'reference': f"PAY-{payment.id}-{uuid.uuid4().hex[:6]}"
            })

    except Exception as e:
        logger.exception("Error processing guest info")
        return create_error_response("Processing error occurred")


# =============================================================================
# PAYSTACK INTEGRATION VIEWS
# =============================================================================

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.db import transaction
from django.utils import timezone
from django.contrib import messages
from django.conf import settings
import json, logging, hmac, hashlib

from .models import Payment, PaymentStatus, Tour
# Services
from .services import PaystackService, PaymentSessionManager

# Utilities
from .utils import (
    log_payment_event,
    create_success_response,
    create_error_response,
    send_payment_confirmation_email
)
logger = logging.getLogger(__name__)
# bookings/views.py
import json
import hmac
import hashlib
import logging
from decimal import Decimal

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.db import transaction
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.conf import settings

from .models import Payment, PaymentStatus, Tour
from .services import PaystackService, PaymentSessionManager
from .utils import log_payment_event, send_payment_confirmation_email

logger = logging.getLogger(__name__)

# =============================================================================
# GUEST CHECKOUT: CREATE PAYSTACK ORDER
# =============================================================================
@csrf_exempt
@require_POST
def create_guest_paystack_order(request):
    """Create a Paystack order for guest checkout with proper metadata."""
    try:
        tour_id = request.POST.get('tour_id')
        adults = int(request.POST.get('adults', 1))
        children = int(request.POST.get('children', 0))
        guest_email = request.POST.get('email')
        guest_name = request.POST.get('full_name')
        guest_phone = request.POST.get('phone')

        # Validate required fields
        if not all([tour_id, guest_email, guest_name]):
            return JsonResponse({"status": False, "message": "Missing required fields"}, status=400)

        tour = get_object_or_404(Tour, id=tour_id)
        total_amount = tour.price_per_person * (adults + children)

        # Create payment record
        payment = Payment.objects.create(
            tour=tour,
            amount=total_amount,
            guest_full_name=guest_name,
            guest_email=guest_email,
            guest_phone=guest_phone,
            adults=adults,
            children=children,
            status=PaymentStatus.PENDING
        )

        # Initialize Paystack transaction
        paystack_service = PaystackService()
        metadata = {
            "payment_id": str(payment.id),
            "guest_email": guest_email,
            "guest_phone": guest_phone,
        }
        response_data, reference = paystack_service.initialize_transaction(payment, settings.PAYSTACK['CALLBACK_URL'], metadata=metadata)

        if response_data.get('status'):
            payment.transaction_id = reference
            payment.save()
            return JsonResponse({
                'status': True,
                'authorization_url': response_data['data']['authorization_url'],
                'reference': reference,
                'payment_id': str(payment.id)
            })
        else:
            payment.delete()
            return JsonResponse({"status": False, "message": "Failed to initialize payment"}, status=500)

    except Exception as e:
        logger.exception("Error creating guest Paystack order")
        return JsonResponse({"status": False, "message": "Error creating payment order"}, status=500)

# =============================================================================
# RETRY PAYMENT
# =============================================================================
@require_POST
def retry_payment(request, payment_id):
    """Retry a failed or pending payment."""
    try:
        payment = get_object_or_404(Payment, id=payment_id)

        if payment.status not in [PaymentStatus.FAILED, PaymentStatus.PENDING]:
            return JsonResponse({"status": False, "message": "Payment cannot be retried"}, status=400)

        session_manager = PaymentSessionManager(request.session)
        session_payment = session_manager.get_pending_payment()
        if not session_payment or str(session_payment.pk) != str(payment_id):
            return JsonResponse({"status": False, "message": "Unauthorized"}, status=403)

        paystack_service = PaystackService()

        # Reset status to pending
        payment.status = PaymentStatus.PENDING
        payment.save()

        metadata = {
            "payment_id": str(payment.id),
            "guest_email": payment.guest_email,
            "guest_phone": payment.guest_phone,
        }

        response_data, reference = paystack_service.initialize_transaction(payment, settings.PAYSTACK['CALLBACK_URL'], metadata=metadata)

        if response_data.get('status'):
            payment.transaction_id = reference
            payment.save()

            log_payment_event("payment_retry", str(payment.pk), email=payment.guest_email, phone=payment.guest_phone, new_reference=reference)

            return JsonResponse({
                "status": True,
                "authorization_url": response_data['data']['authorization_url'],
                "reference": reference
            })
        else:
            return JsonResponse({"status": False, "message": response_data.get('message', 'Payment initialization failed')}, status=500)

    except Exception as e:
        logger.exception(f"Payment retry error: {e}")
        return JsonResponse({"status": False, "message": "Payment retry failed"}, status=500)

# =============================================================================
# PAYSTACK CALLBACK (USER REDIRECT)
# =============================================================================
@csrf_exempt
def paystack_callback(request):
    """Handle Paystack payment callback."""
    reference = request.GET.get("reference")
    if not reference:
        messages.error(request, "Invalid payment reference")
        return redirect("payment_failed")

    session_manager = PaymentSessionManager(request.session)
    paystack_service = PaystackService()

    try:
        response_data = paystack_service.verify_transaction(reference)
        if not response_data.get('status'):
            messages.error(request, "Payment verification failed")
            return redirect("payment_failed")

        data = response_data.get('data', {})
        payment_id = data.get('metadata', {}).get('payment_id')
        if not payment_id:
            messages.error(request, "Payment record not found in metadata")
            return redirect("payment_failed")

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(id=payment_id)
            status_api = data.get('status')

            if status_api == "success":
                payment.status = PaymentStatus.SUCCESS
                payment.amount_paid = payment.amount
                payment.paid_on = timezone.now()
                payment.transaction_id = reference
                payment.paystack_transaction_id = data.get("id")
                payment.reference = reference
                payment.raw_response = response_data
                payment.save()

                session_manager.clear_payment_session()
                send_payment_confirmation_email(payment)

                messages.success(request, "Payment successful!")
                return redirect("payment_success_detail", pk=payment.pk)

            elif status_api in ["pending", "abandoned"]:
                payment.status = PaymentStatus.PENDING
                payment.raw_response = response_data
                payment.save()

                messages.info(request, f"Payment is {status_api}. We'll notify you once confirmed.")
                return redirect("payment_pending")

            else:
                payment.status = PaymentStatus.FAILED
                payment.raw_response = response_data
                payment.save()

                messages.error(request, "Payment failed.")
                return redirect("payment_failed")

    except Payment.DoesNotExist:
        messages.error(request, "Payment record not found")
        return redirect("payment_failed")
    except Exception as e:
        logger.exception(f"Paystack callback error: {e}")
        messages.error(request, "Payment processing error")
        return redirect("payment_failed")

# =============================================================================
# PAYSTACK WEBHOOK (SERVER-TO-SERVER)
# =============================================================================
@csrf_exempt
@require_POST
def paystack_webhook(request):
    """Handle Paystack webhook events."""
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        logger.error("Webhook received without signature")
        return HttpResponse("Invalid signature", status=400)

    try:
        body = request.body
        calculated_signature = hmac.new(settings.PAYSTACK['SECRET_KEY'].encode(), body, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(signature, calculated_signature):
            logger.error("Invalid webhook signature")
            return HttpResponse("Invalid signature", status=400)

        payload = json.loads(body.decode())
        event = payload.get("event")
        data = payload.get("data", {})
        payment_id = data.get("metadata", {}).get("payment_id")

        if not payment_id:
            logger.error("Payment ID not found in webhook metadata")
            return HttpResponse("Payment ID not found", status=400)

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(id=payment_id)

            if event == "charge.success":
                payment.process_paystack_webhook(payload)
            elif event == "charge.failed":
                payment.status = PaymentStatus.FAILED
                payment.raw_response = payload
                payment.save()
            else:
                logger.info(f"Ignored webhook event {event} for payment {payment_id}")

    except Payment.DoesNotExist:
        logger.error(f"Payment not found for webhook: {payment_id}")
        return HttpResponse("Payment not found", status=404)
    except Exception as e:
        logger.exception(f"Webhook error: {e}")
        return HttpResponse("Error processing webhook", status=500)

    return HttpResponse("Webhook processed", status=200)

# =============================================================================
# PAYMENT RESULT VIEWS
# =============================================================================
@require_GET
def payment_success_detail(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    if payment.status != PaymentStatus.SUCCESS:
        return redirect("payment_pending")
    return render(request, "payments/success.html", {"payment": payment})

@require_GET
def payment_pending(request):
    session_manager = PaymentSessionManager(request.session)
    payment = session_manager.get_pending_payment()
    return render(request, "payments/pending.html", {"payment": payment})

@require_GET
def payment_failed(request):
    session_manager = PaymentSessionManager(request.session)
    payment = session_manager.get_pending_payment()
    return render(request, "payments/failed.html", {"payment": payment})

@require_GET
def receipt(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    if payment.status != PaymentStatus.SUCCESS:
        return redirect("payment_pending")
    return render(request, "payments/receipt.html", {"payment": payment})
@require_GET
def payment_success_general(request):
    """Render a general payment success page (no specific payment)."""
    return render(request, "payments/success.html")

# =============================================================================
# GUEST PAYMENT VIEWS
# =============================================================================

@require_GET
def guest_payment_page(request, payment_id: str):
    """Display payment page for guest including Paystack payment."""
    try:
        payment = get_object_or_404(Payment, id=payment_id)
    except ValueError:
        messages.error(request, "Invalid payment ID")
        return redirect("home")

    if payment.status == PaymentStatus.SUCCESS:
        return redirect("receipt", pk=payment.pk)
    elif payment.status == PaymentStatus.FAILED:
        return redirect("payment_failed")

    # Update session for this payment
    session_manager = PaymentSessionManager(request.session)
    session_manager.set_pending_payment(payment)

    log_payment_event(
        "guest_payment_page_viewed",
        str(payment.pk),
        email=payment.guest_email,
        phone=payment.guest_phone
    )

    return render(request, "payments/guest_payment_page.html", {
        "payment": payment,
        "tour": payment.tour,
        "public_key": settings.PAYSTACK['PUBLIC_KEY'],
    })


@require_GET
def guest_payment_return(request):
    """Handle return from guest payment."""
    # This is a general return page that checks session for payment status
    session_manager = PaymentSessionManager(request.session)
    payment = session_manager.get_pending_payment()

    if not payment:
        messages.warning(request, "No payment found in session")
        return redirect("home")

    # Check payment status
    if payment.status == PaymentStatus.SUCCESS:
        return redirect("guest_payment_success")
    elif payment.status == PaymentStatus.FAILED:
        return redirect("guest_payment_failed")
    else:
        return redirect("guest_payment_pending")


@require_GET
def guest_payment_success(request):
    """Guest payment success page."""
    session_manager = PaymentSessionManager(request.session)
    payment = session_manager.get_pending_payment()

    if not payment or payment.status != PaymentStatus.SUCCESS:
        messages.warning(request, "Payment not completed")
        return redirect("home")

    context = {'payment': payment}
    return render(request, "payments/guest_success.html", context)


@require_GET
def guest_payment_failed(request):
    """Guest payment failed page."""
    session_manager = PaymentSessionManager(request.session)
    payment = session_manager.get_pending_payment()

    context = {'payment': payment}
    return render(request, "payments/guest_failed.html", context)


# =============================================================================
# PAYMENT UTILITY VIEWS
# =============================================================================

@require_GET
def check_payment_status(request, payment_id):
    """API endpoint to check payment status."""
    try:
        payment = get_object_or_404(Payment, id=payment_id)

        # Verify this payment belongs to the current session
        session_manager = PaymentSessionManager(request.session)
        session_payment = session_manager.get_pending_payment()

        if not session_payment or str(session_payment.pk) != str(payment_id):
            return create_error_response("Unauthorized", status=403)

        response_data = {
            'payment_id': str(payment.pk),
            'status': payment.status,
            'amount': float(payment.amount),
            'amount_paid': float(payment.amount_paid or 0),
            'reference': payment.reference,
            'created_at': payment.created_at.isoformat(),
        }

        if payment.paid_at:
            response_data['paid_at'] = payment.paid_at.isoformat()

        return create_success_response(response_data)

    except ValueError:
        return create_error_response("Invalid payment ID", status=400)
    except Exception as e:
        logger.exception(f"Error checking payment status: {e}")
        return create_error_response("Error checking payment status", status=500)


@require_POST
def retry_payment(request, payment_id):
    """Retry a failed or pending payment."""
    try:
        payment = get_object_or_404(Payment, id=payment_id)

        # Only allow retry for failed or pending payments
        if payment.status not in [PaymentStatus.FAILED, PaymentStatus.PENDING]:
            return create_error_response("Payment cannot be retried")

        # Verify this payment belongs to the current session
        session_manager = PaymentSessionManager(request.session)
        session_payment = session_manager.get_pending_payment()

        if not session_payment or str(session_payment.pk) != str(payment_id):
            return create_error_response("Unauthorized", status=403)

        paystack_service = PaystackService()

        try:
            # Reset payment status to pending
            payment.status = PaymentStatus.PENDING
            payment.save()

            # Initialize new Paystack transaction
            response_data, reference = paystack_service.initialize_transaction(
                payment, settings.PAYSTACK['CALLBACK_URL']
            )

            if response_data.get('status'):
                # Update payment with new reference
                payment.transaction_id = reference
                payment.save()

                log_payment_event(
                    "payment_retry",
                    str(payment.pk),
                    email=payment.guest_email,
                    phone=payment.guest_phone,
                    new_reference=reference
                )

                return create_success_response({
                    'authorization_url': response_data['data']['authorization_url'],
                    'reference': reference,
                })
            else:
                error_msg = response_data.get('message', 'Payment initialization failed')
                log_payment_event(
                    "payment_retry_failed",
                    str(payment.pk),
                    error=error_msg
                )
                return create_error_response(error_msg)

        except Exception as e:
            logger.exception(f"Payment retry error: {e}")
            return create_error_response("Payment retry failed")

    except ValueError:
        return create_error_response("Invalid payment ID", status=400)


@csrf_exempt
@require_POST
def create_guest_paystack_order(request):
    """Create a Paystack order for guest checkout."""
    try:
        tour_id = request.POST.get('tour_id')
        adults = int(request.POST.get('adults', 1))
        children = int(request.POST.get('children', 0))
        guest_email = request.POST.get('email')
        guest_name = request.POST.get('full_name')
        guest_phone = request.POST.get('phone')

        # Validate required fields
        if not all([tour_id, guest_email, guest_name]):
            return create_error_response("Missing required fields")

        tour = get_object_or_404(Tour, id=tour_id)

        # Calculate total amount
        total_amount = tour.price_per_person * (adults + children)

        # Create payment record
        payment = Payment.objects.create(
            tour=tour,
            amount=total_amount,
            guest_full_name=guest_name,
            guest_email=guest_email,
            guest_phone=guest_phone,
            adults=adults,
            children=children,
            status=PaymentStatus.PENDING
        )

        # Initialize Paystack transaction
        paystack_service = PaystackService()
        response_data, reference = paystack_service.initialize_transaction(
            payment, settings.PAYSTACK['CALLBACK_URL']
        )

        if response_data.get('status'):
            payment.transaction_id = reference
            payment.save()

            return create_success_response({
                'authorization_url': response_data['data']['authorization_url'],
                'reference': reference,
                'payment_id': str(payment.id)
            })
        else:
            payment.delete()
            return create_error_response("Failed to initialize payment")

    except Exception as e:
        logger.exception("Error creating guest Paystack order")
        return create_error_response("Error creating payment order")


# =============================================================================
# DRIVER VIEWS
# =============================================================================

def driver_login(request):
    """Driver login view."""
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)

            if user is not None and hasattr(user, 'driver'):
                login(request, user)
                messages.success(request, f"Welcome back, {user.driver.name}!")
                return redirect("driver_dashboard")
            else:
                messages.error(request, "Invalid username or password, or you're not registered as a driver.")
    else:
        form = AuthenticationForm()

    return render(request, 'drivers/login.html', {'form': form})


@driver_required
def driver_dashboard(request):
    """Driver dashboard view."""
    driver = request.user.driver

    # Get driver's trips
    upcoming_trips = Trip.objects.filter(
        driver=driver,
        date__gte=timezone.now().date()
    ).order_by('date')[:5]

    completed_trips = Trip.objects.filter(
        driver=driver,
        status='COMPLETED'
    ).order_by('-date')[:10]

    # Calculate statistics
    total_earnings = Trip.objects.filter(driver=driver, status='COMPLETED').aggregate(
        total=models.Sum('earnings'))['total'] or 0

    total_trips = Trip.objects.filter(driver=driver).count()

    context = {
        'driver': driver,
        'upcoming_trips': upcoming_trips,
        'completed_trips': completed_trips,
        'total_earnings': total_earnings,
        'total_trips': total_trips,
    }

    return render(request, 'drivers/dashboard.html', context)


def driver_logout(request):
    """Driver logout view."""
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect("driver_login")


# =============================================================================
# TOUR MANAGEMENT VIEWS
# =============================================================================

@driver_required
def create_tour(request):
    """Create a new tour."""
    if request.method == 'POST':
        form = TourForm(request.POST, request.FILES)
        if form.is_valid():
            tour = form.save(commit=False)
            tour.created_by = request.user
            tour.save()
            messages.success(request, "Tour created successfully!")
            return redirect("driver_dashboard")
    else:
        form = TourForm()

    return render(request, 'drivers/tour_form.html', {'form': form, 'title': 'Create Tour'})


@driver_required
def edit_tour(request, tour_id):
    """Edit an existing tour."""
    tour = get_object_or_404(Tour, id=tour_id, created_by=request.user)

    if request.method == 'POST':
        form = TourForm(request.POST, request.FILES, instance=tour)
        if form.is_valid():
            form.save()
            messages.success(request, "Tour updated successfully!")
            return redirect("driver_dashboard")
    else:
        form = TourForm(instance=tour)

    return render(request, 'drivers/tour_form.html', {'form': form, 'title': 'Edit Tour', 'tour': tour})


@driver_required
def delete_tour(request, tour_id):
    """Delete a tour."""
    tour = get_object_or_404(Tour, id=tour_id, created_by=request.user)

    if request.method == 'POST':
        tour.delete()
        messages.success(request, "Tour deleted successfully!")
        return redirect("driver_dashboard")

    return render(request, 'drivers/tour_confirm_delete.html', {'tour': tour})


# =============================================================================
# ADMIN VIEWS
# =============================================================================

@staff_member_required
def modern_admin_dashboard(request):
    """Modern admin dashboard view."""
    # Get statistics
    total_tours = Tour.objects.count()
    active_tours = Tour.objects.filter(available=True, is_approved=True).count()
    total_payments = Payment.objects.count()
    successful_payments = Payment.objects.filter(status=PaymentStatus.SUCCESS).count()
    total_bookings = Booking.objects.count()
    recent_bookings = Booking.objects.select_related('customer', 'destination').order_by('-created_at')[:10]
    recent_payments = Payment.objects.select_related('user', 'tour').order_by('-created_at')[:10]

    # Calculate revenue
    total_revenue = Payment.objects.filter(status=PaymentStatus.SUCCESS).aggregate(
        total=models.Sum('amount_paid'))['total'] or 0

    context = {
        'total_tours': total_tours,
        'active_tours': active_tours,
        'total_payments': total_payments,
        'successful_payments': successful_payments,
        'total_bookings': total_bookings,
        'total_revenue': total_revenue,
        'recent_bookings': recent_bookings,
        'recent_payments': recent_payments,
    }

    return render(request, 'admin/modern_dashboard.html', context)


@staff_member_required
def payment_admin_list(request):
    """Admin view to list all payments."""
    payments = Payment.objects.select_related('tour').order_by('-created_at')

    # Filter by status if provided
    status_filter = request.GET.get('status')
    if status_filter and status_filter in [choice[0] for choice in PaymentStatus.choices]:
        payments = payments.filter(status=status_filter)

    # Search by email or name
    search = request.GET.get('search')
    if search:
        payments = payments.filter(
            models.Q(guest_email__icontains=search) |
            models.Q(guest_full_name__icontains=search) |
            models.Q(reference__icontains=search)
        )

    context = {
        'payments': payments,
        'status_choices': PaymentStatus.choices,
        'current_status': status_filter,
        'search_query': search,
    }

    return render(request, 'admin/payments/list.html', context)


@staff_member_required
def payment_admin_detail(request, payment_id):
    """Admin view to see payment details."""
    payment = get_object_or_404(Payment, id=payment_id)

    context = {
        'payment': payment,
        'raw_response': json.dumps(payment.raw_response, indent=2) if payment.raw_response else None,
    }

    return render(request, 'admin/payments/detail.html', context)


@staff_member_required
@require_POST
def payment_admin_refund(request, payment_id):
    """Admin action to initiate refund (placeholder)."""
    payment = get_object_or_404(Payment, id=payment_id)

    if payment.status != PaymentStatus.SUCCESS:
        messages.error(request, "Can only refund successful payments")
        return redirect('payment_admin_detail', payment_id=payment_id)

    # TODO: Implement actual refund logic with Paystack
    # For now, just log the refund request
    log_payment_event(
        "refund_requested",
        str(payment.pk),
        email=payment.guest_email,
        phone=payment.guest_phone,
        admin_user=request.user.username
    )

    messages.success(request, "Refund request logged. Manual processing required.")
    return redirect('payment_admin_detail', payment_id=payment_id)


# =============================================================================
# CONTACT & MESSAGING VIEWS
# =============================================================================

@require_POST
def contact_submit(request):
    """Handle contact form submission."""
    try:
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()

        # Validate required fields
        if not all([name, email, message]):
            messages.error(request, "Please fill in all required fields.")
            return redirect('contact')

        # Validate email format
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
            messages.error(request, "Please enter a valid email address.")
            return redirect('contact')

        # Create contact message
        contact_message = ContactMessage.objects.create(
            name=name,
            email=email,
            subject=subject or "Contact Form Submission",
            message=message,
            ip_address=get_client_ip(request)
        )

        # Send notification email to admin
        try:
            admin_subject = f"New Contact Message: {contact_message.subject}"
            admin_message = (
                f"New contact message received:\n\n"
                f"Name: {name}\n"
                f"Email: {email}\n"
                f"Subject: {contact_message.subject}\n\n"
                f"Message:\n{message}\n\n"
                f"Submitted at: {contact_message.created_at}\n"
                f"IP Address: {contact_message.ip_address}"
            )

            send_mail(
                admin_subject,
                admin_message,
                settings.DEFAULT_FROM_EMAIL,
                [settings.CONTACT_EMAIL],
                fail_silently=True
            )
        except Exception as e:
            logger.exception(f"Failed to send contact notification: {e}")

        messages.success(request, "Thank you for your message! We'll get back to you soon.")
        logger.info(f"Contact message submitted by {mask_email(email)}")

    except Exception as e:
        logger.exception(f"Contact form error: {e}")
        messages.error(request, "There was an error submitting your message. Please try again.")

    return redirect('contact')


# =============================================================================
# API ENDPOINTS
# =============================================================================

@require_GET
def tour_price_api(request, tour_id):
    """API endpoint to get tour pricing information."""
    try:
        tour = get_object_or_404(Tour, id=tour_id, is_approved=True, available=True)

        adults = int(request.GET.get('adults', 1))
        children = int(request.GET.get('children', 0))

        # Validate participant counts
        if adults < 1:
            return create_error_response("At least one adult is required")

        if hasattr(tour, 'max_participants') and tour.max_participants:
            if adults + children > tour.max_participants:
                return create_error_response(f"Maximum {tour.max_participants} participants allowed")

        # Calculate pricing
        total_participants = adults + children
        base_price = tour.price_per_person * total_participants

        # Apply any discounts (implement your discount logic here)
        discount = 0
        if total_participants >= 4:  # Example: group discount
            discount = base_price * 0.1  # 10% discount

        final_price = base_price - discount

        response_data = {
            'tour_id': tour.id,
            'tour_title': tour.title,
            'price_per_person': float(tour.price_per_person),
            'adults': adults,
            'children': children,
            'total_participants': total_participants,
            'base_price': float(base_price),
            'discount': float(discount),
            'final_price': float(final_price),
            'currency': 'KES'
        }

        return create_success_response(response_data)

    except ValueError:
        return create_error_response("Invalid participant count", status=400)
    except Exception as e:
        logger.exception(f"Tour price API error: {e}")
        return create_error_response("Error calculating price", status=500)


@require_GET
def tour_availability_api(request, tour_id):
    """API endpoint to check tour availability for a specific date."""
    try:
        tour = get_object_or_404(Tour, id=tour_id, is_approved=True, available=True)
        date_str = request.GET.get('date')

        if not date_str:
            return create_error_response("Date parameter is required")

        try:
            check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return create_error_response("Invalid date format. Use YYYY-MM-DD")

        if check_date < timezone.now().date():
            return create_error_response("Cannot check availability for past dates")

        # Check if tour is available on the requested date
        # This is a simplified check - implement your actual availability logic
        is_available = True
        reason = None

        # Example availability checks:
        # 1. Check if it's within booking window
        max_advance_days = getattr(tour, 'max_advance_booking_days', 365)
        if (check_date - timezone.now().date()).days > max_advance_days:
            is_available = False
            reason = f"Bookings only accepted up to {max_advance_days} days in advance"

        # 2. Check existing bookings capacity
        existing_bookings = Payment.objects.filter(
            tour=tour,
            travel_date=check_date,
            status=PaymentStatus.SUCCESS
        ).aggregate(
            total_adults=models.Sum('adults'),
            total_children=models.Sum('children')
        )

        total_booked = (existing_bookings['total_adults'] or 0) + (existing_bookings['total_children'] or 0)
        max_capacity = getattr(tour, 'max_capacity', 50)  # Default capacity

        if total_booked >= max_capacity:
            is_available = False
            reason = "Tour is fully booked for this date"

        response_data = {
            'tour_id': tour.id,
            'date': date_str,
            'is_available': is_available,
            'reason': reason,
            'spots_remaining': max(0, max_capacity - total_booked) if is_available else 0,
            'max_capacity': max_capacity
        }

        return create_success_response(response_data)

    except Exception as e:
        logger.exception(f"Tour availability API error: {e}")
        return create_error_response("Error checking availability", status=500)


# =============================================================================
# UTILITY VIEWS
# =============================================================================

def cleanup_expired_payments():
    """Utility function to clean up expired pending payments."""
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


# =============================================================================
# ERROR HANDLER VIEWS
# =============================================================================

def handler404(request, exception):
    """Custom 404 error handler."""
    return render(request, 'errors/404.html', status=404)


def handler500(request):
    """Custom 500 error handler."""
    return render(request, 'errors/500.html', status=500)


def handler403(request, exception):
    """Custom 403 error handler."""
    return render(request, 'errors/403.html', status=403)


# =============================================================================
# HEALTH CHECK VIEW
# =============================================================================

@require_GET
def health_check(request):
    """Health check endpoint for monitoring."""
    try:
        # Basic database check
        Tour.objects.count()

        # Check Paystack configuration
        validate_paystack_config()

        return JsonResponse({
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'version': '1.0.0'
        })
    except Exception as e:
        logger.exception("Health check failed")
        return JsonResponse({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=503)