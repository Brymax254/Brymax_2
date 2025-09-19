import json
import uuid
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.generic import DetailView

from .models import (
    Tour, Destination, Video, Booking, Payment,
    ContactMessage, Trip, PaymentStatus
)
from .services import PesaPalService, MpesaSTKPush
from .forms import GuestCheckoutForm

logger = logging.getLogger(__name__)

# =============================================================================
# UTILITIES & DECORATORS
# =============================================================================

def normalize_phone_number(phone: str) -> Optional[str]:
    """
    Convert a phone number to E.164 format for Kenya (+254...).
    Returns None if phone is invalid.

    Args:
        phone (str): Input phone number.

    Returns:
        Optional[str]: Normalized phone number in +254 format or None.
    """
    if not phone:
        return None
    phone = phone.strip()
    if phone.startswith("0"):
        return "+254" + phone[1:]
    if phone.startswith("+"):
        return phone
    return None


def send_payment_confirmation_email(payment: Payment) -> None:
    """
    Send email confirmation to guest after successful payment.

    Args:
        payment (Payment): Payment instance for which to send confirmation.
    """
    subject = f"Payment Confirmation - {payment.tour.title}"
    message = (
        f"Dear {payment.guest_full_name},\n\n"
        f"We have received your payment of KES {payment.amount_paid} "
        f"for \"{payment.tour.title}\".\n\n"
        "Thank you for booking with Safari Adventures Kenya!"
    )
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [payment.guest_email])
        logger.info(f"Sent payment confirmation email to {payment.guest_email}")
    except Exception as e:
        logger.exception(f"Failed to send confirmation email: {e}")


def driver_required(view_func):
    """
    Decorator to ensure user is logged in and has a driver profile.
    Redirects to driver login page if not.
    """

    @login_required
    def _wrapped(request, *args, **kwargs):
        if not hasattr(request.user, "driver"):
            messages.error(request, "You must log in as a driver.")
            return redirect("driver_login")
        return view_func(request, *args, **kwargs)

    return _wrapped


# =============================================================================
# FRONTEND PAGES
# =============================================================================

def home(request):
    """Render homepage."""
    return render(request, "home.html")


def book_online(request):
    """Render Book Online landing page."""
    return render(request, "book_online.html")


def nairobi_transfers(request):
    """Render Nairobi airport transfers and taxi information page."""
    return render(request, "nairobi_transfers.html")


def excursions(request):
    """Render Excursions listing page."""
    return render(request, "excursions.html")


def tours(request):
    """
    Render Public Tours page including trips, videos, and destinations.

    Context:
        tours: Approved and available Tour objects.
        trips: All Trip objects.
        videos: All Video objects.
        destinations: All Destination objects.
    """
    context = {
        "tours": Tour.objects.filter(is_approved=True, available=True)
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
# TOUR PAYMENT (PESAPAL)
# =============================================================================

@require_http_methods(["GET", "POST"])
def tour_payment(request, tour_id):
    """
    Handles checkout form and Pesapal payment iframe for a specific tour.

    GET: Display checkout form.
    POST: Create Payment object and return necessary data for Pesapal JavaScript.

    Args:
        request: HttpRequest object.
        tour_id (int): ID of the Tour being booked.

    Returns:
        HttpResponse: Renders tour_payment.html with payment form and Pesapal credentials.
    """
    tour = get_object_or_404(Tour, id=tour_id)
    payment = None
    is_guest_payment = request.session.get("pending_payment_id") is not None

    if request.method == "POST":
        form = GuestCheckoutForm(request.POST)
        if form.is_valid():
            full_name = form.cleaned_data["full_name"]
            email = form.cleaned_data["email"]
            phone = normalize_phone_number(form.cleaned_data["phone"])
            adults = form.cleaned_data.get("adults", 1)
            children = form.cleaned_data.get("children", 0)
            travel_date = form.cleaned_data.get("travel_date", timezone.now().date())
            total_amount = tour.price_per_person * (adults + children)

            with transaction.atomic():
                # Check if there's already a pending payment for this tour and email
                payment = Payment.objects.filter(
                    tour=tour,
                    guest_email=email,
                    status=PaymentStatus.PENDING
                ).first()

                if payment:
                    messages.info(request, "You already have a pending payment for this tour.")
                    request.session["pending_payment_id"] = str(payment.pk)
                    request.session["guest_email"] = email
                    request.session["guest_phone"] = phone
                else:
                    # Create a new payment record
                    payment = Payment.objects.create(
                        tour=tour,
                        amount=total_amount,
                        currency="KES",
                        provider="PESAPAL",
                        status=PaymentStatus.PENDING,
                        guest_full_name=full_name,
                        guest_email=email,
                        guest_phone=phone,
                        adults=adults,
                        children=children,
                        travel_date=travel_date,
                        description=f"Tour {tour.title} booking",
                    )
                    request.session["pending_payment_id"] = str(payment.pk)
                    request.session["guest_email"] = email
                    request.session["guest_phone"] = phone
                    logger.info(f"Payment record created for {email} - {payment.id}")
        else:
            messages.error(request, "Please correct the errors below.")
            logger.warning(f"Tour payment form invalid: {form.errors}")
    else:
        form = GuestCheckoutForm()
        payment_id_str = request.session.get("pending_payment_id")
        if payment_id_str and is_guest_payment:
            try:
                payment_id = uuid.UUID(payment_id_str)
                payment = Payment.objects.get(id=payment_id, tour_id=tour_id)
                if payment.status != PaymentStatus.PENDING:
                    # If payment is no longer pending, clear session
                    request.session.pop("pending_payment_id", None)
                    messages.info(request, "Your previous payment session has expired.")
            except (Payment.DoesNotExist, ValueError) as exc:
                logger.warning(f"Invalid pending payment session: {exc}")
                request.session.pop("pending_payment_id", None)
                messages.error(request, "Payment session expired. Please try again.")

    return render(
        request,
        "payments/tour_payment.html",
        {
            "tour": tour,
            "form": form,
            "payment": payment,
            "merchant_key": settings.PESAPAL_CONSUMER_KEY,
            "callback_url": settings.PESAPAL_CALLBACK_URL,
            "is_guest_payment": is_guest_payment,
            "today": timezone.now().date(),
        },
    )


@require_GET
def pesapal_redirect(request):
    """
    Handle redirect from Pesapal after user completes payment.

    Retrieves status from query params and updates Payment record.
    Redirects user to success page.
    """
    tracking_id = request.GET.get("pesapal_transaction_id")
    merchant_reference = request.GET.get("pesapal_merchant_reference")

    if not tracking_id or not merchant_reference:
        messages.error(request, "Invalid payment callback.")
        return redirect("home")

    try:
        # Extract payment ID from merchant reference
        payment_id = merchant_reference.split('-')[1] if '-' in merchant_reference else None

        if not payment_id:
            logger.error(f"Could not extract payment ID from merchant reference: {merchant_reference}")
            messages.error(request, "Invalid payment reference.")
            return redirect("home")

        payment = get_object_or_404(Payment, id=payment_id)

        # Update payment with Pesapal details
        payment.pesapal_reference = tracking_id
        payment.transaction_id = tracking_id
        payment.status = PaymentStatus.PENDING  # Will be updated by IPN
        payment.save()

        # Clear session
        request.session.pop("pending_payment_id", None)

        return redirect("payment_success", pk=payment.pk)

    except (Payment.DoesNotExist, ValueError) as exc:
        logger.error(f"Payment not found for tracking ID: {tracking_id} - {exc}")
        messages.error(request, "Payment not found.")
        return redirect("home")


@require_GET
def payment_success(request, pk):
    """Display success page for a payment."""
    payment = get_object_or_404(Payment, pk=pk)
    return render(request, "payments/success.html", {"payment": payment})


@require_GET
def receipt(request, pk):
    """Display receipt page for a payment."""
    payment = get_object_or_404(Payment, pk=pk)
    return render(request, "payments/receipt.html", {"payment": payment})


@csrf_exempt
@require_GET
def pesapal_health(request):
    """Simple health check endpoint for Pesapal IPN."""
    return HttpResponse("OK", status=200)


@csrf_exempt
@require_POST
def pesapal_ipn(request):
    """
    Handle Pesapal server-to-server IPN notifications.

    Expects JSON with a transaction tracking ID.
    Updates payment status accordingly.
    """
    try:
        # Parse the request body
        if request.content_type == 'application/json':
            payload = json.loads(request.body)
        else:
            # Handle form data
            payload = {
                'OrderTrackingId': request.POST.get('OrderTrackingId'),
                'OrderMerchantReference': request.POST.get('OrderMerchantReference'),
                'PaymentStatus': request.POST.get('PaymentStatus'),
            }

        tracking_id = payload.get("OrderTrackingId") or payload.get("order_tracking_id") or payload.get(
            "pesapal_transaction_id")
        merchant_reference = payload.get("OrderMerchantReference") or payload.get("merchant_reference")

        if not tracking_id:
            logger.error(f"IPN missing tracking ID: {payload}")
            return HttpResponse("Missing tracking ID", status=400)

        # Extract payment ID from merchant reference
        payment_id = None
        if merchant_reference and '-' in merchant_reference:
            payment_id = merchant_reference.split('-')[1]

        if not payment_id:
            logger.error(f"Could not extract payment ID from merchant reference: {merchant_reference}")
            return HttpResponse("Invalid merchant reference", status=400)

        payment = get_object_or_404(Payment, id=payment_id)

        # Update payment status
        status = payload.get("PaymentStatus", payload.get("status", "FAILED")).upper()

        # Map Pesapal status to our PaymentStatus
        STATUS_MAP = {
            "COMPLETED": PaymentStatus.SUCCESS,
            "FAILED": PaymentStatus.FAILED,
            "PENDING": PaymentStatus.PENDING,
            "CANCELLED": PaymentStatus.CANCELLED,
            "REFUNDED": PaymentStatus.REFUNDED,
        }

        new_status = STATUS_MAP.get(status, PaymentStatus.PENDING)

        with transaction.atomic():
            payment.status = new_status
            payment.pesapal_reference = tracking_id

            if new_status == PaymentStatus.SUCCESS:
                payment.amount_paid = payment.amount
                payment.paid_at = timezone.now()

                # Send confirmation email if not already sent
                if not payment.confirmation_sent:
                    send_payment_confirmation_email(payment)
                    payment.confirmation_sent = True

            payment.save()
            logger.info(f"Updated payment {payment.id} status to {new_status}")

        return HttpResponse("OK", status=200)

    except Exception as exc:
        logger.exception("Pesapal IPN processing failed: %s", exc)
        return HttpResponse("Server error", status=500)


# =============================================================================
# MPESA STK PUSH
# =============================================================================

@csrf_exempt
@login_required
@require_POST
def mpesa_payment(request, tour_id):
    """
    Initiate Mpesa STK Push for a specific tour.

    Args:
        request: HttpRequest with JSON body containing phone_number.
        tour_id: ID of the tour being paid.

    Returns:
        JsonResponse: STK Push initiation status.
    """
    try:
        body = json.loads(request.body)
        phone = normalize_phone_number(body.get("phone_number"))
        if not phone:
            return JsonResponse({"success": False, "message": "Invalid phone number"}, status=400)
        tour = get_object_or_404(Tour, id=tour_id)
        mpesa = MpesaSTKPush()
        response = mpesa.stk_push(
            phone_number=phone,
            amount=tour.price_per_person,
            account_reference=f"Tour-{tour.id}",
            transaction_desc=f"Payment for Tour {tour.title}",
        )
        checkout_id = response.get("CheckoutRequestID")
        if not checkout_id:
            return JsonResponse({"success": False, "message": "STK Push initiation failed"}, status=500)
        payment, _ = Payment.objects.get_or_create(
            user=request.user,
            tour=tour,
            transaction_id=checkout_id,
            provider="MPESA",
            defaults={
                "amount": tour.price_per_person,
                "currency": "KES",
                "status": PaymentStatus.PENDING,
                "method": "MPESA",
                "description": f"Tour {tour.title}",
                "travel_date": timezone.now().date(),
            },
        )
        return JsonResponse({"success": True, "message": "STK Push sent", "checkout_id": checkout_id})
    except Exception as exc:
        logger.exception("Mpesa STK Push failed: %s", exc)
        return JsonResponse({"success": False, "message": "Error processing payment"}, status=500)


# =============================================================================
# PAYMENT RESULT PAGES
# =============================================================================

@require_GET
def payment_success(request):
    """Render general payment success page."""
    return render(request, "payments/success.html")


@require_GET
def payment_failed(request):
    """Render general payment failure page."""
    return render(request, "payments/failed.html")


# =============================================================================
# GUEST CHECKOUT / PESAPAL
# =============================================================================

@require_POST
def guest_checkout(request, tour_id):
    """
    Create a pending guest payment and booking, store in session.

    Args:
        request: HttpRequest with POST data from guest form.
        tour_id: Tour being booked.

    Returns:
        JsonResponse for AJAX or redirect for normal form.
    """
    tour = get_object_or_404(Tour, id=tour_id)
    try:
        data = request.POST
        full_name = data["full_name"]
        email = data["email"]
        phone = normalize_phone_number(data["phone"])
        adults = int(data.get("adults", 1))
        children = int(data.get("children", 0))
        travel_date = data.get("travel_date", timezone.now().date())
        total = tour.price_per_person * (adults + children)
        payment = Payment.objects.create(
            tour=tour,
            guest_full_name=full_name,
            guest_email=email,
            guest_phone=phone,
            adults=adults,
            children=children,
            travel_date=travel_date,
            amount=total,
            amount_paid=0,
            currency="KES",
            provider="GUEST",
            status=PaymentStatus.PENDING,
            description=f"Tour {tour.title} (Guest)",
        )
        request.session["pending_payment_id"] = str(payment.pk)
        request.session["guest_email"] = email
        request.session["guest_phone"] = phone
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": True, "payment_id": str(payment.pk)})
        return redirect("tour_payment_page", tour_id=tour_id)
    except (KeyError, InvalidOperation) as exc:
        logger.exception("Guest checkout error: %s", exc)
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "message": str(exc)}, status=400)
        return HttpResponse(status=400)


# =============================================================================
# GUEST PAYMENT PAGES
# =============================================================================

@require_GET
def guest_payment_page(request, payment_id: str):
    """
    Display payment page for guest including Pesapal iframe.

    Args:
        request: HttpRequest object.
        payment_id: UUID of the pending payment.

    Returns:
        HttpResponse: Payment page template or redirect if already paid.
    """
    payment = get_object_or_404(Payment, id=payment_id)

    if payment.status == PaymentStatus.COMPLETED:
        return redirect("receipt", pk=payment.pk)

    request.session["guest_email"] = payment.guest_email
    request.session["guest_phone"] = payment.guest_phone

    return render(request, "payments/guest_payment_page.html", {
        "payment": payment,
        "tour": payment.tour,
    })


@csrf_exempt
@require_http_methods(["POST"])
def process_guest_info(request):
    """
    Process guest information via AJAX and return booking details for Pesapal payment.
    """
    logger.info(f"=== PROCESS GUEST INFO START ===")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request content type: {request.content_type}")
    logger.info(f"Request POST data: {request.POST}")
    logger.info(f"Request body: {request.body}")

    try:
        # Get form data
        full_name = request.POST.get('full_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        adults = request.POST.get('adults', 1)
        children = request.POST.get('children', 0)
        days = request.POST.get('days', 1)
        travel_date = request.POST.get('travel_date')
        tour_id = request.POST.get('tour_id')
        total_amount = request.POST.get('total_amount')

        logger.info(
            f"Extracted data: full_name={full_name}, email={email}, phone={phone}, tour_id={tour_id}, total_amount={total_amount}")

        # Validate required fields
        required_fields = [full_name, email, phone, tour_id, total_amount]
        if not all(required_fields):
            missing = []
            if not full_name: missing.append('full_name')
            if not email: missing.append('email')
            if not phone: missing.append('phone')
            if not tour_id: missing.append('tour_id')
            if not total_amount: missing.append('total_amount')

            logger.error(f"Missing required fields: {missing}")
            return JsonResponse({
                'success': False,
                'message': f'Missing required fields: {", ".join(missing)}'
            }, status=400)

        # Get tour
        try:
            tour = Tour.objects.get(id=tour_id)
            logger.info(f"Found tour: {tour.title}")
        except Tour.DoesNotExist:
            logger.error(f"Tour not found with ID: {tour_id}")
            return JsonResponse({
                'success': False,
                'message': 'Tour not found'
            }, status=404)

        # Create or update payment record
        with transaction.atomic():
            # Check if there's already a pending payment for this tour and email
            payment = Payment.objects.filter(
                tour=tour,
                guest_email=email,
                status=PaymentStatus.PENDING
            ).first()

            if payment:
                logger.info(f"Found existing payment: {payment.id}")
            else:
                # Create a new payment record
                payment = Payment.objects.create(
                    tour=tour,
                    amount=total_amount,
                    currency="KES",
                    provider="PESAPAL",
                    status=PaymentStatus.PENDING,
                    guest_full_name=full_name,
                    guest_email=email,
                    guest_phone=phone,
                    adults=adults,
                    children=children,
                    travel_date=travel_date,
                    description=f"Tour {tour.title} booking",
                )
                logger.info(f"Created new payment: {payment.id}")

            # Generate a unique booking ID
            booking_id = f"BOOK-{payment.id}-{uuid.uuid4().hex[:6]}"

            # Update session
            request.session["pending_payment_id"] = str(payment.pk)
            request.session["guest_email"] = email
            request.session["guest_phone"] = phone
            request.session.save()  # Explicitly save the session

            logger.info(f"Updated session with payment_id: {payment.pk}")
            logger.info(f"Generated booking_id: {booking_id}")

            response_data = {
                'success': True,
                'booking_id': booking_id,
                'message': 'Guest information processed successfully'
            }
            logger.info(f"Returning response: {response_data}")
            logger.info(f"=== PROCESS GUEST INFO END ===")
            return JsonResponse(response_data)

    except Exception as e:
        logger.exception(f"Error processing guest info: {e}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def create_guest_pesapal_order(request):
    """
    Create a Pesapal order for guest checkout
    """
    try:
        # Parse the request body
        data = json.loads(request.body)

        # Extract required fields
        full_name = data.get('full_name')
        email = data.get('email')
        phone = data.get('phone')
        country_code = data.get('country_code')
        adults = data.get('adults')
        children = data.get('children')
        days = data.get('days')
        travel_date = data.get('travel_date')
        amount = data.get('amount')
        description = data.get('description')
        currency = data.get('currency', 'KES')
        tour_id = data.get('tour_id')
        payment_method = data.get('payment_method', 'pesapal')
        installment_option = data.get('installment_option', 'full')
        discount_code = data.get('discount_code', '')
        discount_percentage = data.get('discount_percentage', 0)

        # Validate required fields
        if not all([full_name, email, phone, adults, days, travel_date, amount, tour_id]):
            return JsonResponse({
                'success': False,
                'error': 'Missing required fields'
            }, status=400)

        # Get the tour
        try:
            tour = Tour.objects.get(id=tour_id)
        except Tour.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Tour not found'
            }, status=404)

        # Create payment record
        payment = Payment.objects.create(
            guest_full_name=full_name,
            guest_email=email,
            guest_phone=f"{country_code}{phone}",
            adults=adults,
            children=children,
            days=days,
            travel_date=travel_date,
            amount=amount,
            description=description,
            currency=currency,
            status=PaymentStatus.PENDING,
            tour=tour
        )

        # Create order data for Pesapal
        order_data = {
            'order_id': str(payment.id),
            'amount': amount,
            'description': description,
            'email': email,
            'phone': f"{country_code}{phone}",
            'first_name': full_name.split(' ')[0],
            'last_name': ' '.join(full_name.split(' ')[1:]) if ' ' in full_name else '',
        }

        # Initialize Pesapal service
        pesapal_service = PesaPalService()
        result = pesapal_service.create_order(order_data)

        if result.get('success'):
            # Update payment with tracking info
            payment.pesapal_tracking_id = result.get('order_tracking_id')
            payment.reference = result.get('merchant_ref')
            payment.save()

            return JsonResponse(result)
        else:
            # Delete the payment record if payment initialization failed
            payment.delete()
            return JsonResponse({
                'success': False,
                'error': result.get('error', 'Failed to initialize payment')
            })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Tour.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Tour not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error creating Pesapal order: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while processing your payment'
        }, status=500)

@csrf_exempt
@require_POST
def guest_pesapal_callback(request):
    """
    AJAX callback from Pesapal to update guest payment status.

    Expects JSON: {order_tracking_id, status}.

    Returns:
        JsonResponse indicating success/failure.
    """
    try:
        payload = json.loads(request.body)
        tracking_id = payload.get("order_tracking_id")
        status = payload.get("status", "").upper()

        # Validate session
        if not validate_payment_session(request):
            return JsonResponse({"success": False, "message": "Session expired or invalid"}, status=400)

        # Verify tracking ID matches session
        if tracking_id != request.session.get("guest_order_tracking_id"):
            return JsonResponse({"success": False, "message": "Order not found"}, status=404)

        # Update payment record
        payment = Payment.objects.get(pesapal_tracking_id=tracking_id)
        payment.status = status
        if status == "COMPLETED":
            payment.amount_paid = payment.amount
            payment.paid_at = timezone.now()
        payment.save()

        # Update session with payment status
        request.session["guest_payment_status"] = status
        request.session["payment_updated_at"] = timezone.now().isoformat()

        # Explicitly save session
        request.session.save()

        logger.info(f"Guest payment updated: {tracking_id} -> {status}")
        return JsonResponse({"success": True})
    except Payment.DoesNotExist:
        logger.error(f"Guest payment not found for tracking_id {tracking_id}")
        return JsonResponse({"success": False, "message": "Payment not found"}, status=404)
    except Exception as exc:
        logger.exception("Guest Pesapal callback error: %s", exc)
        return JsonResponse({"success": False, "message": "Server error"}, status=500)


@require_GET
def guest_payment_return(request):
    """
    Handle return from Pesapal payment page for guest.

    Returns:
        HttpResponseRedirect to success or failed page based on status.
    """
    # Validate session
    if not validate_payment_session(request):
        clear_payment_session(request)
        return redirect("payment_failed")

    tracking_id = request.session.get("guest_order_tracking_id")
    if not tracking_id:
        clear_payment_session(request)
        return redirect("payment_failed")

    try:
        payment = Payment.objects.get(pesapal_tracking_id=tracking_id)

        # Clear session after processing
        clear_payment_session(request)

        if payment.status == "COMPLETED":
            return redirect("guest_payment_success")
        return redirect("guest_payment_failed")
    except Payment.DoesNotExist:
        logger.warning(f"Guest payment return: Payment not found {tracking_id}")
        clear_payment_session(request)
        return redirect("payment_failed")


@require_GET
def guest_payment_success(request):
    """
    Render guest payment success page.
    """
    # Get payment info before clearing session
    payment_id = request.session.get("pending_payment_id")
    status = request.session.get("guest_payment_status", "")

    # Clear session after use
    clear_payment_session(request)

    # Try to get payment details if available
    payment = None
    if payment_id:
        try:
            payment = Payment.objects.get(id=payment_id)
            if not status:
                status = payment.status
        except Payment.DoesNotExist:
            pass

    context = {"payment": payment, "status": status}
    return render(request, "payments/guest_success.html", context)


@require_GET
def guest_payment_failed(request):
    """Render guest payment failure page."""
    # Clear any remaining session data
    clear_payment_session(request)
    return render(request, "payments/guest_failed.html")


# Helper functions for session management
def validate_payment_session(request):
    """
    Validate that the payment session is still valid (not expired).

    Returns:
        bool: True if session is valid, False otherwise.
    """
    # Check if payment was initiated recently (within 30 minutes)
    initiated_at = request.session.get("payment_initiated_at")
    if initiated_at:
        try:
            initiated_time = timezone.datetime.fromisoformat(initiated_at)
            if timezone.now() - initiated_time > timezone.timedelta(minutes=30):
                return False
        except (ValueError, TypeError):
            return False

    # Check if we have the required session keys
    required_keys = ["guest_email", "guest_phone", "pending_payment_id"]
    return all(key in request.session for key in required_keys)


def clear_payment_session(request):
    """
    Clear all payment-related session keys.
    """
    payment_keys = [
        "pending_payment_id",
        "guest_email",
        "guest_phone",
        "guest_order_tracking_id",
        "guest_order_merchant_ref",
        "guest_payment_status",
        "payment_initiated_at",
        "payment_updated_at",
    ]

    for key in payment_keys:
        request.session.pop(key, None)

    # Explicitly save session
    request.session.save()
# =============================================================================
# DRIVER DASHBOARD
# =============================================================================

@driver_required
@require_GET
def driver_dashboard(request):
    """
    Render driver dashboard with trips, bookings, payments, and messages.
    """
    driver = request.user.driver
    context = {
        "driver": driver,
        "trip_history": Trip.objects.filter(driver=driver).order_by("-date"),
        "tours": Tour.objects.filter(created_by=request.user).order_by("-created_at"),
        "bookings": Booking.objects.filter(driver=driver)
        .select_related("customer", "destination"),
        "payments": Payment.objects.filter(booking__driver=driver)
        .select_related("booking", "booking__customer"),
        "messages": ContactMessage.objects.all() if request.user.is_staff else ContactMessage.objects.none(),
    }
    return render(request, "driver_dashboard.html", context)


@driver_required
@require_POST
def create_tour(request):
    """
    Create a new tour by driver with optional media upload.
    """
    try:
        title = request.POST.get("title", "").strip() or "Untitled Tour"
        price = Decimal(request.POST.get("price_per_person", "0.00"))
        tour = Tour.objects.create(
            title=title,
            description=request.POST.get("description", ""),
            itinerary=request.POST.get("itinerary", ""),
            duration_days=max(1, int(request.POST.get("duration_days", 1))),
            price_per_person=price,
            available=True,
            created_by=request.user,
            is_approved=True,
        )
        if "image" in request.FILES:
            tour.image = request.FILES["image"]
        if "video" in request.FILES:
            tour.video = request.FILES["video"]
        tour.save()
        messages.success(request, f'Tour "{tour.title}" added successfully.')
    except Exception as exc:
        logger.exception("Error creating tour: %s", exc)
        messages.error(request, "Failed to add tour.")
    return redirect("driver_dashboard")


# =============================================================================
# DRIVER TOUR MANAGEMENT
# =============================================================================

@driver_required
@require_http_methods(["GET", "POST"])
def edit_tour(request, tour_id: int):
    """
    Edit an existing tour created by the driver or by staff.

    Args:
        request: HttpRequest object.
        tour_id: ID of the tour to edit.

    Returns:
        HttpResponse: Redirects to driver dashboard on POST or renders edit form on GET.
    """
    tour = get_object_or_404(Tour, id=tour_id)
    if tour.created_by != request.user and not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect("driver_dashboard")

    if request.method == "POST":
        try:
            tour.title = request.POST.get("title", tour.title)
            tour.description = request.POST.get("description", tour.description)
            tour.itinerary = request.POST.get("itinerary", tour.itinerary)
            tour.duration_days = max(1, int(request.POST.get("duration_days", tour.duration_days)))
            tour.price_per_person = Decimal(request.POST.get("price_per_person", tour.price_per_person))
            if "image" in request.FILES:
                tour.image = request.FILES["image"]
            if "video" in request.FILES:
                tour.video = request.FILES["video"]
            tour.save()
            messages.success(request, f'Tour "{tour.title}" updated successfully.')
            logger.info(f"Tour {tour.id} updated by user {request.user.id}")
        except Exception as exc:
            logger.exception(f"Error updating tour {tour.id}: {exc}")
            messages.error(request, "Failed to update tour.")
        return redirect("driver_dashboard")

    return render(request, "edit_tour.html", {"tour": tour})


@driver_required
@require_POST
def delete_tour(request, tour_id: int):
    """
    Delete a tour created by the driver or by staff.

    Args:
        request: HttpRequest object.
        tour_id: ID of the tour to delete.

    Returns:
        HttpResponseRedirect to driver dashboard.
    """
    tour = get_object_or_404(Tour, id=tour_id)
    if tour.created_by != request.user and not request.user.is_staff:
        messages.error(request, "Permission denied.")
        logger.warning(f"User {request.user.id} attempted to delete unauthorized tour {tour.id}")
    else:
        tour.delete()
        messages.success(request, "Tour deleted successfully.")
        logger.info(f"Tour {tour.id} deleted by user {request.user.id}")
    return redirect("driver_dashboard")


# =============================================================================
# DRIVER AUTHENTICATION
# =============================================================================

@require_http_methods(["GET", "POST"])
def driver_login(request):
    """
    Handle driver login via username and password.

    Args:
        request: HttpRequest object with POST credentials.

    Returns:
        HttpResponse: Renders login page or redirects to dashboard on success.
    """
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user and hasattr(user, "driver"):
            login(request, user)
            logger.info(f"Driver {user.id} logged in successfully")
            return redirect("driver_dashboard")
        messages.error(request, "Invalid credentials or not a driver.")
        logger.warning(f"Failed login attempt for username {username}")
    return render(request, "driver_login.html")


# =============================================================================
# STAFF UTILITIES
# =============================================================================

@staff_member_required
@require_POST
def register_pesapal_ipn(request):
    """
    Register IPN URL with Pesapal. Should only be called once.
    """
    try:
        auth_res = requests.post(
            f"{settings.PESAPAL_BASE_URL}/api/Auth/RequestToken",
            json={"consumer_key": settings.PESAPAL_CONSUMER_KEY, "consumer_secret": settings.PESAPAL_CONSUMER_SECRET},
            timeout=15,
        )
        auth_res.raise_for_status()
        token = auth_res.json().get("token")
        ipn_url = request.build_absolute_uri(reverse("pesapal_ipn"))
        reg_res = requests.post(
            f"{settings.PESAPAL_BASE_URL}/api/URLSetup/RegisterIPN",
            json={"url": ipn_url, "ipn_notification_type": "GET"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        reg_res.raise_for_status()
        ipn_id = reg_res.json().get("ipn_id")
        logger.info(f"Pesapal IPN registered successfully: {ipn_id}")
        return JsonResponse({"success": True, "ipn_id": ipn_id})
    except Exception as exc:
        logger.exception("IPN registration failed: %s", exc)
        return JsonResponse({"success": False, "message": str(exc)}, status=500)


# =============================================================================
# RECEIPT VIEW
# =============================================================================

class ReceiptView(DetailView):
    """
    Display detailed receipt for a Payment.
    Staff can see all receipts; guests/users see only their own.
    """
    model = Payment
    template_name = "payments/receipt.html"
    context_object_name = "payment"

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.request.user.is_staff:
            guest_email = self.request.session.get("guest_email")
            qs = qs.filter(guest_email=guest_email) | qs.filter(user=self.request.user)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        p = self.object
        context.update({
            "days": p.days or p.tour.duration_days,
            "adults": p.adults,
            "children": p.children,
            "amount_paid": p.amount_paid or p.amount,
            "guest_full_name": p.guest_full_name or "Guest",
            "guest_email": p.guest_email or "N/A",
            "guest_phone": p.guest_phone or "N/A",
            "reference": p.pesapal_reference or p.transaction_id,
        })
        return context


@staff_member_required
def modern_admin_dashboard(request):
    """
    Render modern admin dashboard for staff at /brymax-admin/.
    """
    return render(request, "admin/brymax_dashboard.html")