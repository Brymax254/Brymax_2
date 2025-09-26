# =============================================================================
# IMPORTS
# =============================================================================

# Standard library
import json
import logging
import hmac
import hashlib
import re
import uuid
from decimal import Decimal, InvalidOperation
from datetime import timedelta, datetime, date
from typing import Optional, Dict, Any

# Django core
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import models, transaction
from django.http import (
    HttpResponse,
    JsonResponse,
    HttpResponseNotAllowed
)
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import (
    require_GET,
    require_POST,
    require_http_methods
)
from django.views.generic import DetailView

# Third-party
import requests
from requests.exceptions import RequestException

# Local apps - Models & Forms
from .models import (
    Tour, Destination, Booking, Payment, ContactMessage, Trip,
    PaymentStatus, Driver, TourCategory, BookingCustomer
)
from .forms import ContactForm

# Local apps - Services
from bookings.services import (
    PaystackService,
    PaymentSessionManager,
    TourAvailabilityService
)

# Local apps - Utils
from .utils import (
    normalize_phone_number,
    get_client_ip,
    mask_email,
    mask_phone,
    log_payment_event,
    create_error_response,
    create_success_response,
    send_payment_confirmation_email,
    validate_payment_data,
    create_payment_record,
    get_tour_pricing,
    check_tour_availability,
    validate_paystack_config,
    cleanup_expired_payments,
)

# Logger
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION VALIDATION
# =============================================================================

# Validate configuration on module load
try:
    validate_paystack_config()
except ImproperlyConfigured as e:
    logger.error(f"Paystack configuration error: {e}")
    if not settings.DEBUG:
        raise


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
    featured_tours = Tour.objects.filter(
        featured=True,
        is_approved=True,
        available=True
    ).select_related('destination').prefetch_related('images')[:6]

    recent_destinations = Destination.objects.filter(
        is_active=True
    ).prefetch_related('tours')[:4]

    # Get testimonials if available
    testimonials = getattr(settings, 'TESTIMONIALS', [])

    context = {
        "featured_tours": featured_tours,
        "recent_destinations": recent_destinations,
        "testimonials": testimonials,
    }
    return render(request, "home.html", context)


def book_online(request):
    """Render Book Online landing page."""
    # Get filter parameters
    category = request.GET.get('category')
    destination = request.GET.get('destination')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')

    # Start with all available tours (ordered for stable pagination)
    tours = Tour.objects.filter(
        is_approved=True,
        available=True
    ).select_related('destination', 'category').order_by('id')

    # Apply filters
    if category:
        tours = tours.filter(category__slug=category)
    if destination:
        tours = tours.filter(destination__slug=destination)
    if min_price:
        tours = tours.filter(price_per_person__gte=min_price)
    if max_price:
        tours = tours.filter(price_per_person__lte=max_price)

    # Get categories and destinations for filter dropdowns
    categories = TourCategory.objects.filter(is_active=True)
    destinations = Destination.objects.filter(is_active=True)

    # Pagination
    page = request.GET.get('page', 1)
    paginator = Paginator(tours, 9)  # Show 9 tours per page

    try:
        tours = paginator.page(page)
    except PageNotAnInteger:
        tours = paginator.page(1)
    except EmptyPage:
        tours = paginator.page(paginator.num_pages)

    context = {
        "tours": tours,
        "categories": categories,
        "destinations": destinations,
        "selected_category": category,
        "selected_destination": destination,
        "min_price": min_price,
        "max_price": max_price,
    }
    return render(request, "book_online.html", context)


def nairobi_transfers(request):
    """Render Nairobi airport transfers and taxi information page."""
    transfer_services = getattr(settings, 'TRANSFER_SERVICES', [])
    transfer_prices = getattr(settings, 'TRANSFER_PRICES', {})

    context = {
        "transfer_services": transfer_services,
        "transfer_prices": transfer_prices,
    }
    return render(request, "nairobi_transfers.html", context)


def excursions(request):
    """Render Excursions listing page."""
    category_slugs = ['excursion', 'adventure']
    excursions = Tour.objects.filter(
        category__slug__in=category_slugs,
        is_approved=True,
        available=True
    ).select_related('destination', 'category').prefetch_related('images').order_by('id')

    # Pagination
    page = request.GET.get('page', 1)
    paginator = Paginator(excursions, 9)

    try:
        excursions = paginator.page(page)
    except PageNotAnInteger:
        excursions = paginator.page(1)
    except EmptyPage:
        excursions = paginator.page(paginator.num_pages)

    context = {"excursions": excursions}
    return render(request, "excursions.html", context)


def tours(request):
    """Render Public Tours page including trips, and destinations."""
    # Get filter parameters
    search_query = request.GET.get('search', '')
    category = request.GET.get('category')

    # Start with all available tours (ordered for stable pagination)
    tours = Tour.objects.filter(
        is_approved=True,
        available=True
    ).select_related("created_by", "approved_by", "category").order_by("-created_at")

    # Apply filters
    if search_query:
        tours = tours.filter(
            models.Q(title__icontains=search_query) |
            models.Q(description__icontains=search_query) |
            models.Q(destination__name__icontains=search_query)
        )

    if category:
        tours = tours.filter(category__slug=category)

    # Get other content
    trips = Trip.objects.all().order_by("-created_at")[:6]
    destinations = Destination.objects.filter(is_active=True).order_by("-created_at")[:6]

    # Get categories for filter
    categories = TourCategory.objects.filter(is_active=True)

    # Pagination for tours
    page = request.GET.get('page', 1)
    paginator = Paginator(tours, 12)

    try:
        tours = paginator.page(page)
    except PageNotAnInteger:
        tours = paginator.page(1)
    except EmptyPage:
        tours = paginator.page(paginator.num_pages)

    context = {
        "tours": tours,
        "trips": trips,
        "destinations": destinations,
        "categories": categories,
        "search_query": search_query,
        "selected_category": category,
    }
    return render(request, "tours.html", context)


def contact(request):
    """Render Contact page."""
    form = ContactForm()
    contact_info = getattr(settings, 'CONTACT_INFO', {})

    context = {
        "form": form,
        "contact_info": contact_info,
    }
    return render(request, "contact.html", context)


def terms(request):
    """Render Terms and Conditions page."""
    return render(request, "terms.html")


def about(request):
    """Render About Us page."""
    team_members = getattr(settings, 'TEAM_MEMBERS', [])
    company_stats = getattr(settings, 'COMPANY_STATS', {})

    context = {
        "team_members": team_members,
        "company_stats": company_stats,
    }
    return render(request, "about.html")


# =============================================================================
# TOUR DETAIL VIEWS
# =============================================================================

class TourDetailView(DetailView):
    """Detailed view for a specific tour."""
    model = Tour
    template_name = 'tours/detail.html'
    context_object_name = 'tour'
    slug_url_kwarg = 'tour_slug'

    def get_queryset(self):
        return Tour.objects.filter(
            is_approved=True,
            available=True
        ).select_related('destination', 'category').prefetch_related('images', 'inclusions', 'exclusions')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add form
        from .forms import GuestCheckoutForm
        context['form'] = GuestCheckoutForm()

        # Add Paystack public key
        context['public_key'] = settings.PAYSTACK['PUBLIC_KEY']
        context['today'] = timezone.now().date()

        # Add related tours
        context['related_tours'] = Tour.objects.filter(
            destination=self.object.destination,
            is_approved=True,
            available=True
        ).exclude(id=self.object.id).select_related('destination')[:3]

        # Add tour availability
        availability_service = TourAvailabilityService()
        context['available_dates'] = availability_service.get_available_dates(self.object)

        # Add tour pricing options
        context['pricing_options'] = get_tour_pricing(self.object)

        return context


# =============================================================================
# PAYMENT PROCESSING VIEWS
# =============================================================================

@require_http_methods(["GET", "POST"])
def tour_payment(request, tour_id):
    """Handle checkout form and Paystack payment for a specific tour."""
    tour = get_object_or_404(Tour, id=tour_id, is_approved=True, available=True)
    session_manager = PaymentSessionManager(request.session)
    paystack_service = PaystackService()

    if request.method == "POST":
        from .forms import GuestCheckoutForm
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
                        payment.reference = reference
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
    from .forms import GuestCheckoutForm
    form = GuestCheckoutForm()
    payment = session_manager.get_pending_payment()

    if payment and payment.tour_id != tour_id:
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
    tour = get_object_or_404(Tour, id=tour_id, is_approved=True, available=True)
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
        tour = get_object_or_404(Tour, id=tour_id, is_approved=True, available=True)

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
# PAYSTACK INTEGRATION VIEWS (FULLY UPDATED)
# =============================================================================

# =============================================================================
# CREATE / RETRY PAYMENT
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

        if not all([tour_id, guest_email, guest_name]):
            return JsonResponse({"status": False, "message": "Missing required fields"}, status=400)

        tour = get_object_or_404(Tour, id=tour_id, is_approved=True, available=True)
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

        # Initialize Paystack
        paystack_service = PaystackService()
        metadata = {
            "payment_id": str(payment.id),
            "guest_email": guest_email,
            "guest_phone": guest_phone,
        }
        response_data, reference = paystack_service.initialize_transaction(
            payment,
            settings.PAYSTACK['CALLBACK_URL'],
            metadata=metadata
        )

        if response_data.get('status'):
            payment.reference = reference
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
        payment.status = PaymentStatus.PENDING
        payment.save()

        metadata = {
            "payment_id": str(payment.id),
            "guest_email": payment.guest_email,
            "guest_phone": payment.guest_phone,
        }
        response_data, reference = paystack_service.initialize_transaction(
            payment,
            settings.PAYSTACK['CALLBACK_URL'],
            metadata=metadata
        )

        if response_data.get('status'):
            payment.reference = reference
            payment.save()
            log_payment_event("payment_retry", str(payment.pk), email=payment.guest_email, phone=payment.guest_phone)
            return JsonResponse({
                "status": True,
                "authorization_url": response_data['data']['authorization_url'],
                "reference": reference
            })
        else:
            return JsonResponse({"status": False, "message": "Payment initialization failed"}, status=500)

    except Exception as e:
        logger.exception("Payment retry error")
        return JsonResponse({"status": False, "message": "Payment retry failed"}, status=500)


# =============================================================================
# CALLBACK + WEBHOOK (Unified flow)
# =============================================================================
def _update_payment_from_paystack(payment, data, payload=None, from_webhook=False):
    """Helper to sync payment + create booking if needed."""
    status = data.get("status")
    if status == "success":
        payment.status = PaymentStatus.SUCCESS
        payment.amount_paid = Decimal(str(data.get("amount", 0))) / 100
        payment.paid_on = timezone.now()
        payment.paystack_transaction_id = str(data.get("id"))
        payment.raw_response = payload or data
        if from_webhook:
            payment.webhook_verified = True
            payment.webhook_received_at = timezone.now()
        payment.save()

        # Ensure booking exists
        if not Booking.objects.filter(payment=payment).exists():
            booking_customer = BookingCustomer.objects.create(
                full_name=payment.guest_full_name,
                email=payment.guest_email,
                phone_number=payment.guest_phone,
                adults=payment.adults,
                children=payment.children,
                travel_date=payment.travel_date,
                days=payment.days,
            )
            booking = Booking.objects.create(
                tour=payment.tour,
                booking_customer=booking_customer,
                travel_date=payment.travel_date,
                adults=payment.adults,
                children=payment.children,
                total_amount=payment.amount,
                payment=payment,
                status="CONFIRMED",
            )
            payment.booking = booking
            payment.save()

    else:
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = data.get("gateway_response", "Payment failed")
        payment.raw_response = payload or data
        payment.save()


def paystack_callback(request):
    """Handle Paystack callback after redirect."""
    reference = request.GET.get("reference")
    if not reference:
        messages.error(request, "Invalid payment reference.")
        return redirect("bookings:payment_failed")

    headers = {"Authorization": f"Bearer {settings.PAYSTACK['SECRET_KEY']}"}
    url = f"https://api.paystack.co/transaction/verify/{reference}"

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response_data = response.json()
    except Exception as e:
        messages.error(request, f"Error verifying transaction: {e}")
        return redirect("bookings:payment_failed")


    if not response_data.get("status"):
        messages.error(request, "Payment verification failed.")
        return redirect("bookings:payment_failed")

    try:
        payment = Payment.objects.get(reference=reference)
    except Payment.DoesNotExist:
        messages.error(request, "Payment record not found.")
        return redirect("bookings:payment_failed")


    _update_payment_from_paystack(payment, response_data["data"], payload=response_data)
    if payment.status == PaymentStatus.SUCCESS:
        return redirect("receipt", pk=payment.pk)
    return redirect("bookings:payment_failed")



@csrf_exempt
@require_POST
def paystack_webhook(request):
    """Handle Paystack webhook events (charge.success, charge.failed)."""
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        return HttpResponse("Invalid signature", status=400)

    body = request.body
    calc_sig = hmac.new(
        settings.PAYSTACK['SECRET_KEY'].encode(),
        body,
        hashlib.sha512
    ).hexdigest()
    if not hmac.compare_digest(signature, calc_sig):
        return HttpResponse("Invalid signature", status=400)

    payload = json.loads(body.decode())
    event = payload.get("event")
    data = payload.get("data", {})
    reference = data.get("reference")
    if not reference:
        return HttpResponse("Missing reference", status=400)

    try:
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(reference=reference)
            if event == "charge.success":
                _update_payment_from_paystack(payment, data, payload=payload, from_webhook=True)
            elif event == "charge.failed":
                _update_payment_from_paystack(payment, {"status": "failed", **data}, payload=payload, from_webhook=True)
    except Payment.DoesNotExist:
        return HttpResponse("Payment not found", status=404)

    return HttpResponse("Webhook processed", status=200)


# =============================================================================
# PAYMENT RESULT VIEWS
# =============================================================================
@require_GET
def payment_success_detail(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    if payment.status != PaymentStatus.SUCCESS:
        return redirect("payment_pending")
    booking = Booking.objects.filter(payment=payment).first()
    return render(request, "payments/success.html", {"payment": payment, "booking": booking})


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


def receipt(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    booking = Booking.objects.filter(payment=payment).first()
    return render(request, "payments/receipt.html", {"payment": payment, "booking": booking})


# =============================================================================
# GUEST PAYMENT VIEWS
# =============================================================================
@require_GET
def guest_payment_page(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)
    if payment.status == PaymentStatus.SUCCESS:
        return redirect("receipt", pk=payment.pk)
    elif payment.status == PaymentStatus.FAILED:
        return redirect("bookings:payment_failed")

    session_manager = PaymentSessionManager(request.session)
    session_manager.set_pending_payment(payment)
    return render(request, "payments/guest_payment_page.html", {
        "payment": payment,
        "tour": payment.tour,
        "public_key": settings.PAYSTACK['PUBLIC_KEY'],
    })


@require_GET
def guest_payment_success(request):
    session_manager = PaymentSessionManager(request.session)
    payment = session_manager.get_pending_payment()
    if not payment or payment.status != PaymentStatus.SUCCESS:
        return redirect("home")
    return redirect("receipt", pk=payment.pk)


@require_GET
def guest_payment_failed(request):
    session_manager = PaymentSessionManager(request.session)
    payment = session_manager.get_pending_payment()
    return render(request, "payments/guest_failed.html", {"payment": payment})


# =============================================================================
# PAYMENT UTILITY VIEWS
# =============================================================================
@require_GET
def check_payment_status(request, payment_id):
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        session_manager = PaymentSessionManager(request.session)
        session_payment = session_manager.get_pending_payment()
        if not session_payment or str(session_payment.pk) != str(payment_id):
            return JsonResponse({"status": False, "message": "Unauthorized"}, status=403)

        resp = {
            'payment_id': str(payment.pk),
            'status': payment.status,
            'amount': float(payment.amount),
            'amount_paid': float(payment.amount_paid or 0),
            'reference': payment.reference,
            'created_at': payment.created_at.isoformat(),
        }
        if payment.paid_on:
            resp['paid_on'] = payment.paid_on.isoformat()
        return JsonResponse({"status": True, "data": resp})

    except Exception as e:
        logger.exception("Error checking payment status")
        return JsonResponse({"status": False, "message": "Error checking payment status"}, status=500)


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
    today = timezone.now().date()
    upcoming_trips = Trip.objects.filter(
        driver=driver,
        date__gte=today
    ).order_by('date')[:5]

    completed_trips = Trip.objects.filter(
        driver=driver,
        status='COMPLETED'
    ).order_by('-date')[:10]

    # Calculate statistics
    total_earnings = Trip.objects.filter(driver=driver, status='COMPLETED').aggregate(
        total=models.Sum('earnings'))['total'] or 0

    total_trips = Trip.objects.filter(driver=driver).count()

    # Get recent payments for driver's tours
    recent_payments = Payment.objects.filter(
        tour__created_by=request.user,
        status=PaymentStatus.SUCCESS
    ).order_by('-paid_on')[:5]

    context = {
        'driver': driver,
        'upcoming_trips': upcoming_trips,
        'completed_trips': completed_trips,
        'total_earnings': total_earnings,
        'total_trips': total_trips,
        'recent_payments': recent_payments,
        'today': today,
    }

    return render(request, 'drivers/dashboard.html', context)


def driver_logout(request):
    """Driver logout view."""
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect("driver_login")


@driver_required
def create_tour(request):
    """Create a new tour."""
    from .forms import TourForm

    if request.method == 'POST':
        form = TourForm(request.POST, request.FILES)
        if form.is_valid():
            tour = form.save(commit=False)
            tour.created_by = request.user
            tour.save()
            form.save_m2m()  # Save many-to-many relationships
            messages.success(request, "Tour created successfully! It's pending approval.")
            return redirect("driver_dashboard")
    else:
        form = TourForm()

    return render(request, 'drivers/tour_form.html', {'form': form, 'title': 'Create Tour'})


@driver_required
def edit_tour(request, tour_id):
    """Edit an existing tour."""
    from .forms import TourForm

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


@driver_required
def driver_tours(request):
    """List all tours created by the driver."""
    tours = Tour.objects.filter(
        created_by=request.user
    ).select_related('destination', 'category').order_by('-created_at')

    # Filter by status if provided
    status_filter = request.GET.get('status')
    if status_filter == 'approved':
        tours = tours.filter(is_approved=True)
    elif status_filter == 'pending':
        tours = tours.filter(is_approved=False)
    elif status_filter == 'available':
        tours = tours.filter(available=True)
    elif status_filter == 'unavailable':
        tours = tours.filter(available=False)

    # Pagination
    page = request.GET.get('page', 1)
    paginator = Paginator(tours, 10)

    try:
        tours = paginator.page(page)
    except PageNotAnInteger:
        tours = paginator.page(1)
    except EmptyPage:
        tours = paginator.page(paginator.num_pages)

    context = {
        'tours': tours,
        'status_filter': status_filter,
    }

    return render(request, 'drivers/tours.html', context)


@driver_required
def driver_tour_detail(request, tour_id):
    """View details of a specific tour created by the driver."""
    tour = get_object_or_404(Tour, id=tour_id, created_by=request.user)

    # Get bookings for this tour
    bookings = Booking.objects.filter(
        tour=tour
    ).select_related('payment').order_by('-created_at')

    context = {
        'tour': tour,
        'bookings': bookings,
    }

    return render(request, 'drivers/tour_detail.html', context)


# =============================================================================
# ADMIN VIEWS
# =============================================================================

@staff_member_required
def modern_admin_dashboard(request):
    """Modern admin dashboard view."""
    # Get statistics
    total_tours = Tour.objects.count()
    active_tours = Tour.objects.filter(available=True, is_approved=True).count()
    pending_tours = Tour.objects.filter(is_approved=False).count()
    total_payments = Payment.objects.count()
    successful_payments = Payment.objects.filter(status=PaymentStatus.SUCCESS).count()
    total_bookings = Booking.objects.count()
    recent_bookings = Booking.objects.select_related('booking_customer', 'destination', 'tour').order_by('-created_at')[
        :10]
    recent_payments = Payment.objects.select_related('tour').order_by('-created_at')[:10]

    # Get monthly revenue for the past 6 months
    monthly_revenue = []
    for i in range(6):
        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30 * i)
        month_end = month_start.replace(day=28) + timedelta(days=4)  # Get to the next month
        month_end = month_end - timedelta(days=month_end.day)  # Last day of current month

        revenue = Payment.objects.filter(
            status=PaymentStatus.SUCCESS,
            paid_on__gte=month_start,
            paid_on__lte=month_end
        ).aggregate(total=models.Sum('amount_paid'))['total'] or 0

        monthly_revenue.append({
            'month': month_start.strftime('%b %Y'),
            'revenue': float(revenue)
        })

    monthly_revenue.reverse()  # Show oldest to newest

    # Calculate revenue
    total_revenue = Payment.objects.filter(status=PaymentStatus.SUCCESS).aggregate(
        total=models.Sum('amount_paid'))['total'] or 0

    # Get top destinations
    top_destinations = Destination.objects.annotate(
        booking_count=models.Count('tour__booking')
    ).order_by('-booking_count')[:5]

    context = {
        'total_tours': total_tours,
        'active_tours': active_tours,
        'pending_tours': pending_tours,
        'total_payments': total_payments,
        'successful_payments': successful_payments,
        'total_bookings': total_bookings,
        'total_revenue': total_revenue,
        'recent_bookings': recent_bookings,
        'recent_payments': recent_payments,
        'monthly_revenue': monthly_revenue,
        'top_destinations': top_destinations,
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
            models.Q(reference__icontains=search) |
            models.Q(tour__title__icontains=search)
        )

    # Filter by date range
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if start_date:
        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            payments = payments.filter(created_at__date__gte=start_date)
        except ValueError:
            pass

    if end_date:
        try:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            payments = payments.filter(created_at__date__lte=end_date)
        except ValueError:
            pass

    # Pagination
    page = request.GET.get('page', 1)
    paginator = Paginator(payments, 20)

    try:
        payments = paginator.page(page)
    except PageNotAnInteger:
        payments = paginator.page(1)
    except EmptyPage:
        payments = paginator.page(paginator.num_pages)

    context = {
        'payments': payments,
        'status_choices': PaymentStatus.choices,
        'current_status': status_filter,
        'search_query': search,
        'start_date': start_date,
        'end_date': end_date,
    }

    return render(request, 'admin/payments/list.html', context)


@staff_member_required
def payment_admin_detail(request, payment_id):
    """Admin view to see payment details."""
    payment = get_object_or_404(Payment, id=payment_id)

    # Get booking if exists
    try:
        booking = Booking.objects.get(payment=payment)
    except Booking.DoesNotExist:
        booking = None

    context = {
        'payment': payment,
        'booking': booking,
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


@staff_member_required
def admin_tour_approval(request):
    """Admin view to approve or reject tours."""
    # Get pending tours
    pending_tours = Tour.objects.filter(
        is_approved=False
    ).select_related('created_by', 'destination', 'category').order_by('-created_at')

    # Pagination
    page = request.GET.get('page', 1)
    paginator = Paginator(pending_tours, 10)

    try:
        pending_tours = paginator.page(page)
    except PageNotAnInteger:
        pending_tours = paginator.page(1)
    except EmptyPage:
        pending_tours = paginator.page(paginator.num_pages)

    context = {
        'pending_tours': pending_tours,
    }

    return render(request, 'admin/tour_approval.html', context)


@staff_member_required
@require_POST
def approve_tour(request, tour_id):
    """Approve a tour."""
    tour = get_object_or_404(Tour, id=tour_id)

    tour.is_approved = True
    tour.approved_by = request.user
    tour.approved_at = timezone.now()
    tour.save()

    # Send notification to tour creator
    try:
        send_mail(
            "Your Tour Has Been Approved",
            f"Your tour '{tour.title}' has been approved and is now live on our website.",
            settings.DEFAULT_FROM_EMAIL,
            [tour.created_by.email],
            fail_silently=True
        )
    except Exception as e:
        logger.exception(f"Failed to send tour approval notification: {e}")

    messages.success(request, f"Tour '{tour.title}' has been approved.")
    return redirect('admin_tour_approval')


@staff_member_required
@require_POST
def reject_tour(request, tour_id):
    """Reject a tour."""
    tour = get_object_or_404(Tour, id=tour_id)
    reason = request.POST.get('reason', '')

    tour.is_approved = False
    tour.approved_by = request.user
    tour.approved_at = timezone.now()

    # Check if rejection_reason field exists before setting it
    if hasattr(tour, 'rejection_reason'):
        tour.rejection_reason = reason

    tour.save()

    # Send notification to tour creator
    try:
        send_mail(
            "Your Tour Has Been Rejected",
            f"Your tour '{tour.title}' has been rejected. Reason: {reason}",
            settings.DEFAULT_FROM_EMAIL,
            [tour.created_by.email],
            fail_silently=True
        )
    except Exception as e:
        logger.exception(f"Failed to send tour rejection notification: {e}")

    messages.success(request, f"Tour '{tour.title}' has been rejected.")
    return redirect('admin_tour_approval')


# =============================================================================
# CONTACT & MESSAGING VIEWS
# =============================================================================

@require_POST
def contact_submit(request):
    """Handle contact form submission."""
    try:
        form = ContactForm(request.POST)

        if form.is_valid():
            contact_message = form.save(commit=False)
            contact_message.ip_address = get_client_ip(request)
            contact_message.save()

            # Send notification email to admin
            try:
                admin_subject = f"New Contact Message: {contact_message.subject}"
                admin_message = (
                    f"New contact message received:\n\n"
                    f"Name: {contact_message.name}\n"
                    f"Email: {contact_message.email}\n"
                    f"Phone: {contact_message.phone}\n"
                    f"Subject: {contact_message.subject}\n\n"
                    f"Message:\n{contact_message.message}\n\n"
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
            logger.info(f"Contact message submitted by {mask_email(contact_message.email)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    except Exception as e:
        logger.exception(f"Contact form error: {e}")
        messages.error(request, "There was an error submitting your message. Please try again.")

    return redirect('contact')


def payment_success(request):
    return render(request, "payments/success.html")


def payment_failed(request):
    return render(request, "payments/failed.html")


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

        # Apply any discounts (example: group discount)
        discount = 0
        if total_participants >= 4:  # ✅ fixed typo here
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
        availability_service = TourAvailabilityService()
        availability_result = availability_service.check_availability(tour, check_date)

        return create_success_response(availability_result)

    except Exception as e:
        logger.exception(f"Tour availability API error: {e}")
        return create_error_response("Error checking availability", status=500)


@require_GET
def tours_api(request):
    """API endpoint to get tours with filtering and pagination."""
    try:
        # Get filter parameters
        category = request.GET.get('category')
        destination = request.GET.get('destination')
        min_price = request.GET.get('min_price')
        max_price = request.GET.get('max_price')
        search = request.GET.get('search')
        featured = request.GET.get('featured')

        # Start with all available tours (ordered for stable pagination)
        tours = Tour.objects.filter(
            is_approved=True,
            available=True
        ).select_related('destination', 'category').order_by('id')

        # Apply filters
        if category:
            tours = tours.filter(category__slug=category)
        if destination:
            tours = tours.filter(destination__slug=destination)
        if min_price:
            try:
                min_price = float(min_price)
                tours = tours.filter(price_per_person__gte=min_price)
            except ValueError:
                pass
        if max_price:
            try:
                max_price = float(max_price)
                tours = tours.filter(price_per_person__lte=max_price)
            except ValueError:
                pass
        if search:
            tours = tours.filter(
                models.Q(title__icontains=search) |
                models.Q(description__icontains=search) |
                models.Q(destination__name__icontains=search)
            )
        if featured and featured.lower() == 'true':
            tours = tours.filter(featured=True)

        # Pagination
        page = request.GET.get('page', 1)
        per_page = int(request.GET.get('per_page', 12))
        paginator = Paginator(tours, per_page)

        try:
            tours = paginator.page(page)
        except PageNotAnInteger:
            tours = paginator.page(1)
        except EmptyPage:
            tours = paginator.page(paginator.num_pages)

        # Serialize tours
        tours_data = []
        for tour in tours:
            tour_data = {
                'id': tour.id,
                'title': tour.title,
                'slug': tour.slug,
                'description': tour.description[:200] + '...' if len(tour.description) > 200 else tour.description,
                'price_per_person': float(tour.price_per_person),
                'duration': f"{getattr(tour, 'duration_days', 0)} days, {getattr(tour, 'duration_nights', 0)} nights",
                'destination': {
                    'id': tour.destination.id,
                    'name': tour.destination.name,
                    'slug': tour.destination.slug,
                } if tour.destination else None,
                'category': {
                    'id': tour.category.id,
                    'name': tour.category.name,
                    'slug': tour.category.slug,
                } if tour.category else None,
                'featured': tour.featured,
                'image_url': tour.image.url if hasattr(tour, 'image') and tour.image else None,
            }
            tours_data.append(tour_data)

        response_data = {
            'tours': tours_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total_pages': paginator.num_pages,
                'total_items': paginator.count,
            }
        }

        return create_success_response(response_data)

    except Exception as e:
        logger.exception(f"Tours API error: {e}")
        return create_error_response("Error fetching tours", status=500)


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


def handler400(request, exception):
    """Custom 400 error handler."""
    return render(request, 'errors/400.html', status=400)


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

        # Check if we can connect to external services
        try:
            response = requests.get('https://api.paystack.co', timeout=5)
            if response.status_code != 200:
                raise Exception("Paystack API not responding correctly")
        except RequestException:
            raise Exception("Cannot connect to Paystack API")

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

def payment_failed(request):
    """Render payment failed page."""
    return render(request, "payments/failed.html")



def guest_payment_return(request):
    # Handle guest payment return logic
    return render(request, "payments/guest_payment_return.html")