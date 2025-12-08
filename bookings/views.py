# =============================================================================
# IMPORTS
# =============================================================================

# Standard library
import calendar
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

# Third-party
import requests
from requests.exceptions import RequestException

# Django core
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models, transaction
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.generic import DetailView

# Local apps - Models
from .models import (
    Booking, BookingCustomer, Destination, Payment,
    PaymentProvider, PaymentStatus, Review, Tour, TourCategory, Trip
)

# Local apps - Serializers

# Local apps - Forms
from .forms import ContactForm, GuestCheckoutForm, TourForm

# Local apps - Services
from bookings.services import (
    PaystackService, PaymentSessionManager, TourAvailabilityService
)

# Local apps - Utils
from .utils import (
    check_tour_availability, create_error_response,
    create_payment_record, create_success_response, get_client_ip,
    get_tour_pricing, log_payment_event, mask_email, validate_paystack_config, validate_payment_data
)

# Local apps - Decorators
from .decorators import driver_required

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
# AUTHENTICATION VIEWS
# =============================================================================

@sensitive_post_parameters('password')
def driver_login(request):
    """Handle driver login. All users must have a valid driver profile."""
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)

            if user is not None:
                # Check if the user has a driver profile and it's valid
                if hasattr(user, 'driver_profile'):
                    driver = user.driver_profile
                    if driver.is_verified and driver.available:
                        login(request, user)
                        return redirect('bookings:driver_dashboard')
                    else:
                        if not driver.is_verified:
                            messages.error(request, "Your driver account is not verified yet.")
                        elif not driver.available:
                            messages.error(request, "Your driver account is currently unavailable.")
                        return redirect('bookings:driver_login')
                else:
                    # User doesn't have a driver profile
                    messages.error(request, "You are not registered as a driver.")
                    return redirect('bookings:driver_login')
            else:
                messages.error(request, "Invalid username or password.")
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()

    return render(request, 'drivers/login.html', {'form': form})


def driver_logout(request):
    """Handle driver logout."""
    logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect("bookings:driver_login")


# =============================================================================
# PUBLIC PAGES VIEWS
# =============================================================================

def home(request):
    """Render homepage with featured tours and destinations."""
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
    """Render Book Online landing page with filtering options."""
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
    return render(request, "nairobi_airport_transfers.html", context)


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
# PAYSTACK INTEGRATION VIEWS
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
# PAYSTACK CALLBACK & WEBHOOK VIEWS
# =============================================================================

def _update_payment_from_paystack(payment, data, payload=None, from_webhook=False):
    """Helper to sync payment + create booking if needed."""
    status = data.get("status")
    if status == "success":
        payment.status = PaymentStatus.SUCCESS
        payment.amount_paid = Decimal(str(data.get("amount", 0))) / 100
        payment.paid_on = timezone.now()
        payment.paystack_transaction_id = str(data.get("id"))
        payment.payment_channel = data.get("channel", "")
        payment.ip_address = data.get("ip_address", "")
        payment.authorization_code = data.get("authorization", {}).get("authorization_code", "")
        payment.raw_response = payload or data

        if from_webhook:
            payment.webhook_verified = True
            payment.webhook_received_at = timezone.now()

        payment.save()

        # Ensure booking exists
        if not payment.booking:
            try:
                # Create booking customer
                booking_customer = BookingCustomer.objects.create(
                    full_name=payment.guest_full_name or "Guest Customer",
                    email=payment.guest_email or data.get("customer", {}).get("email", ""),
                    phone_number=payment.guest_phone or "",
                    adults=payment.adults or 1,
                    children=payment.children or 0,
                    travel_date=payment.travel_date or timezone.now().date(),
                    days=payment.days or 1,
                )

                # Create booking
                booking = Booking.objects.create(
                    booking_customer=booking_customer,
                    tour=payment.tour,
                    travel_date=payment.travel_date or timezone.now().date(),
                    num_adults=payment.adults or 1,
                    num_children=payment.children or 0,
                    total_price=payment.amount,
                    status="CONFIRMED",
                )

                # Now link the payment to the booking
                payment.booking = booking
                payment.save()

                logger.info(f"Created booking {booking.id} and linked to payment {payment.id}")

            except Exception as e:
                logger.error(f"Error creating booking for payment {payment.id}: {e}")

    else:
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = data.get("gateway_response", "Payment failed")
        payment.raw_response = payload or data
        if from_webhook:
            payment.webhook_verified = True
            payment.webhook_received_at = timezone.now()
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
        # Try to get existing payment first
        payment = Payment.objects.get(reference=reference)
    except Payment.DoesNotExist:
        # Create payment if it doesn't exist
        data = response_data["data"]
        customer_data = data.get("customer", {})

        # Extract guest info from Paystack data
        guest_email = customer_data.get("email", "")
        guest_full_name = customer_data.get("first_name", "") + " " + customer_data.get("last_name", "")
        guest_full_name = guest_full_name.strip() or "Guest Customer"

        payment = Payment.objects.create(
            reference=reference,
            amount=Decimal(str(data.get("amount", 0))) / 100,
            status=PaymentStatus.PENDING,
            guest_email=guest_email,
            guest_full_name=guest_full_name,
            provider=PaymentProvider.PAYSTACK,
            method=PaymentProvider.PAYSTACK,
            currency=data.get("currency", "KES"),
            paystack_transaction_id=str(data.get("id")),
            payment_channel=data.get("channel", ""),
            ip_address=data.get("ip_address", ""),
            authorization_code=data.get("authorization", {}).get("authorization_code", ""),
            raw_response=data,
        )

    # Update payment with verification data
    _update_payment_from_paystack(payment, response_data["data"], payload=response_data)

    if payment.status == PaymentStatus.SUCCESS:
        return redirect("bookings:receipt", pk=payment.pk)
    return redirect("bookings:payment_failed")


@csrf_exempt
@require_POST
def paystack_webhook(request):
    """
    Handle Paystack webhook events securely (charge.success, charge.failed).
    Creates payment if it doesn't exist.
    """
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        return HttpResponse("Missing signature", status=400)

    body = request.body
    computed_sig = hmac.new(
        key=settings.PAYSTACK['SECRET_KEY'].encode(),
        msg=body,
        digestmod=hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(signature, computed_sig):
        return HttpResponse("Invalid signature", status=400)

    try:
        payload = json.loads(body.decode())
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON payload", status=400)

    event = payload.get("event")
    data = payload.get("data", {})
    reference = data.get("reference")
    if not reference:
        return HttpResponse("Missing reference", status=400)

    try:
        with transaction.atomic():
            # Try to get existing payment or create a new one
            payment, created = Payment.objects.select_for_update().get_or_create(
                reference=reference,
                defaults={
                    'amount': Decimal(data.get('amount', 0)) / 100,
                    'status': PaymentStatus.PENDING,
                    'guest_email': data.get('customer', {}).get('email', ''),
                    'guest_full_name': f"{data.get('customer', {}).get('first_name', '')} {data.get('customer', {}).get('last_name', '')}".strip() or "Guest Customer",
                    'provider': PaymentProvider.PAYSTACK,
                    'method': PaymentProvider.PAYSTACK,
                    'currency': data.get('currency', 'KES'),
                    'paystack_transaction_id': str(data.get('id')),
                    'payment_channel': data.get('channel', ''),
                    'ip_address': data.get('ip_address', ''),
                    'authorization_code': data.get('authorization', {}).get('authorization_code', ''),
                    'raw_response': data,
                }
            )

            if event == "charge.success":
                _update_payment_from_paystack(payment, data, payload=payload, from_webhook=True)
            elif event == "charge.failed":
                _update_payment_from_paystack(payment, {"status": "failed", **data}, payload=payload, from_webhook=True)
            else:
                logger.info(f"Received unhandled webhook event: {event}")

    except Exception as e:
        logger.exception(f"Webhook processing error: {e}")
        return HttpResponse("Internal server error", status=500)

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
        return redirect("bookings:receipt", pk=payment.pk)
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
    return redirect("bookings:receipt", pk=payment.pk)


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

@driver_required
def driver_dashboard(request):
    """Enhanced driver dashboard with ALL sections in one template."""
    driver = request.user.driver_profile
    today = timezone.now().date()
    current_month = today.replace(day=1)

    # ==================== DASHBOARD DATA ====================
    today_trips = Trip.objects.filter(
        driver=driver,
        date=today,
        status__in=["SCHEDULED", "IN_PROGRESS"]
    ).order_by("start_time")

    upcoming_trips = Trip.objects.filter(
        driver=driver,
        date__gt=today,
        status="SCHEDULED"
    ).order_by("date")[:10]

    completed_trips = Trip.objects.filter(
        driver=driver,
        status="COMPLETED"
    ).order_by("-date", "-end_time")[:5]

    trip_stats = Trip.objects.filter(driver=driver).aggregate(
        total_earnings=Sum("earnings"),
        total_trips=Count("id"),
        completed_trips=Count("id", filter=Q(status="COMPLETED")),
        cancelled_trips=Count("id", filter=Q(status="CANCELLED")),
    )

    monthly_earnings = Trip.objects.filter(
        driver=driver,
        status="COMPLETED",
        date__year=current_month.year,
        date__month=current_month.month,
    ).aggregate(total=Sum("earnings"))["total"] or 0

    week_ago = today - timedelta(days=7)
    weekly_earnings = Trip.objects.filter(
        driver=driver,
        status="COMPLETED",
        date__gte=week_ago,
    ).aggregate(total=Sum("earnings"))["total"] or 0

    tour_stats = Tour.objects.filter(created_by=request.user).aggregate(
        total_tours=Count("id"),
        approved_tours=Count("id", filter=Q(is_approved=True)),
        active_tours=Count("id", filter=Q(available=True, is_approved=True)),
    )

    recent_bookings = Booking.objects.filter(
        tour__created_by=request.user,
        payment__status=PaymentStatus.SUCCESS,
    ).select_related("tour", "payment", "booking_customer").order_by("-created_at")[:5]

    upcoming_bookings = Booking.objects.filter(
        tour__created_by=request.user,
        travel_date__gte=today,
        payment__status=PaymentStatus.SUCCESS,
    ).select_related("tour", "booking_customer").order_by("travel_date")[:5]

    vehicle_status = None
    if hasattr(driver, "vehicle") and driver.vehicle:
        vehicle = driver.vehicle
        # Use a fallback for missing fields
        status = getattr(vehicle, "available", None)
        if status is True:
            status_text = "Available"
        elif status is False:
            status_text = "Unavailable"
        else:
            status_text = "Unknown"

        vehicle_status = {
            "name": f"{vehicle.make} {vehicle.model}",
            "plate": getattr(vehicle, "license_plate", "N/A"),
            "status": status_text,
            "next_maintenance": getattr(vehicle, "next_maintenance_date", None),
            "maintenance_due": getattr(vehicle, "next_maintenance_date", None)
                               and vehicle.next_maintenance_date <= today + timedelta(days=7),
        }

    # ==================== EARNINGS DATA ====================
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    earnings_trips = Trip.objects.filter(driver=driver, status="COMPLETED")
    if start_date:
        earnings_trips = earnings_trips.filter(date__gte=start_date)
    if end_date:
        earnings_trips = earnings_trips.filter(date__lte=end_date)

    monthly_earnings_data = earnings_trips.annotate(
        month=TruncMonth("date")
    ).values("month").annotate(
        total_earnings=Sum("earnings"),
        trip_count=Count("id"),
    ).order_by("month")

    total_stats = earnings_trips.aggregate(
        total_earnings=Sum("earnings"),
        total_trips=Count("id"),
        avg_earnings=Avg("earnings"),
    )

    # ==================== SCHEDULE DATA ====================
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    schedule_trips = Trip.objects.filter(
        driver=driver, date__year=year, date__month=month
    ).order_by("date", "start_time")

    trips_by_date = {}
    for trip in schedule_trips:
        trips_by_date.setdefault(trip.date.isoformat(), []).append(trip)

    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]
    week_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    # ==================== TOURS DATA ====================
    tours = (
        Tour.objects.filter(created_by=request.user)
        .select_related("category")  # only FK fields here
        .prefetch_related("features", "destinations")  # M2M fields here
        .order_by("-created_at")
    )

    tours_stats = {
        "total": tours.count(),
        "approved": tours.filter(is_approved=True).count(),
        "pending": tours.filter(is_approved=False).count(),
        "active": tours.filter(available=True, is_approved=True).count(),
    }

    # ==================== RATINGS DATA ====================
    # Base queryset for the driver's reviews
    reviews_qs = Review.objects.filter(booking__driver=driver).select_related(
        "booking__booking_customer", "booking"
    )

    # Aggregate ratings (do this first, without slicing)
    rating_distribution = (
        reviews_qs.values("rating")
        .annotate(count=Count("id"))
        .order_by("rating")
    )

    # Get latest 10 reviews
    reviews = reviews_qs.order_by("-created_at")[:10]

    performance_metrics = {
        "completion_rate": (trip_stats["completed_trips"] / trip_stats["total_trips"] * 100)
        if trip_stats["total_trips"] > 0
        else 0,
        "avg_rating": getattr(driver, "rating", 0) or 0,
        "response_time": "15 min",
    }

    # ==================== CONTEXT ====================
    context = {
        "driver": driver,
        "today_trips": today_trips,
        "upcoming_trips": upcoming_trips,
        "completed_trips": completed_trips,
        "recent_bookings": recent_bookings,
        "upcoming_bookings": upcoming_bookings,
        "vehicle_status": vehicle_status,
        "total_earnings": trip_stats["total_earnings"] or 0,
        "total_trips": trip_stats["total_trips"],
        "completed_trips_count": trip_stats["completed_trips"],
        "cancelled_trips_count": trip_stats["cancelled_trips"],
        "monthly_earnings": monthly_earnings,
        "weekly_earnings": weekly_earnings,
        "total_tours": tour_stats["total_tours"],
        "approved_tours": tour_stats["approved_tours"],
        "active_tours": tour_stats["active_tours"],
        "performance_metrics": performance_metrics,
        "today": today,
        "current_month": current_month,
        "monthly_earnings_data": monthly_earnings_data,
        "total_stats": total_stats,
        "start_date": start_date,
        "end_date": end_date,
        "calendar": cal,
        "month_name": month_name,
        "year": year,
        "month": month,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "trips_by_date": trips_by_date,
        "week_days": week_days,
        "tours": tours[:10],
        "tour_stats": tours_stats,
        "reviews": reviews,
        "rating_distribution": rating_distribution,
        "total_reviews": reviews.count(),
        "view_mode": "dashboard",
    }

    return render(request, "drivers/dashboard.html", context)


# =============================================================================
# TOUR MANAGEMENT VIEWS
# =============================================================================

@driver_required
def create_tour(request):
    """Create a new tour."""
    if request.method == "POST":
        form = TourForm(request.POST, request.FILES)
        if form.is_valid():
            tour = form.save(commit=False)
            tour.created_by = request.user
            tour.is_approved = False  # 🔒 New tours must be approved first
            tour.save()
            messages.success(request, "✅ Tour created successfully! Pending approval.")
            return redirect("bookings:driver_dashboard")
        else:
            messages.error(request, "❌ Please correct the errors below.")
    else:
        form = TourForm()

    return render(request, "tours/create_tour.html", {"form": form})


@driver_required
def edit_tour(request, tour_id):
    """Edit an existing tour."""
    tour = get_object_or_404(Tour, id=tour_id, created_by=request.user)

    if request.method == "POST":
        form = TourForm(request.POST, request.FILES, instance=tour)
        if form.is_valid():
            tour = form.save(commit=False)
            # ⚡ Optional: reset approval after edits
            tour.is_approved = False
            tour.save()
            messages.success(request, "✏️ Tour updated successfully! Awaiting approval.")
            return redirect("bookings:driver_dashboard")
        else:
            messages.error(request, "❌ Please fix the errors below.")
    else:
        form = TourForm(instance=tour)

    return render(request, "tours/edit_tour.html", {"form": form, "tour": tour})


@driver_required
def delete_tour(request, tour_id):
    """Delete a tour."""
    tour = get_object_or_404(Tour, id=tour_id, created_by=request.user)

    if request.method == "POST":
        tour.delete()
        messages.success(request, "🗑️ Tour deleted successfully.")
        return redirect("bookings:driver_dashboard")

    return render(request, "tours/confirm_delete_tour.html", {"tour": tour})

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
        if total_participants >= 4:
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
        ).select_related('category').prefetch_related('destinations').order_by('id')

        # Apply filters
        if category:
            tours = tours.filter(category__slug=category)
        if destination:
            tours = tours.filter(destinations__slug=destination)
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
                models.Q(destinations__name__icontains=search)
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
            # Get the primary destination (first one in the many-to-many relationship)
            primary_destination = tour.destinations.first() if tour.destinations.exists() else None

            tour_data = {
                'id': tour.id,
                'title': tour.title,
                'slug': tour.slug,
                'description': tour.description[:200] + '...' if len(tour.description) > 200 else tour.description,
                'price_per_person': float(tour.price_per_person),
                'duration': f"{getattr(tour, 'duration_days', 0)} days, {getattr(tour, 'duration_nights', 0)} nights",
                'destination': {
                    'id': primary_destination.id,
                    'name': primary_destination.name,
                    'slug': primary_destination.slug,
                } if primary_destination else None,
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


def guest_payment_return(request):
    """Handle guest payment return logic."""
    return render(request, "payments/guest_payment_return.html")

def nairobi_airport_transfers(request):
    return render(request, "nairobi_airport_transfers.html")


@require_GET
def vehicles_api(request):
    """API endpoint to get vehicles with filtering and pagination - OPTIMIZED VERSION"""
    try:
        # Get filter parameters
        vehicle_type = request.GET.get('type')
        min_capacity = request.GET.get('min_capacity')
        available = request.GET.get('available')

        # Import Vehicle model
        from .models import Vehicle

        # Start with all vehicles - OPTIMIZED: prefetch related data
        vehicles = Vehicle.objects.select_related('image', 'photo').all().order_by('id')

        # Apply filters
        if vehicle_type:
            vehicles = vehicles.filter(vehicle_type__icontains=vehicle_type)
        if min_capacity:
            try:
                min_capacity = int(min_capacity)
                vehicles = vehicles.filter(capacity__gte=min_capacity)
            except ValueError:
                pass
        if available and available.lower() == 'true':
            vehicles = vehicles.filter(is_active=True)

        # OPTIMIZATION: Count before pagination for better performance
        total_count = vehicles.count()

        # Pagination
        page = request.GET.get('page', 1)
        per_page = int(request.GET.get('per_page', 12))
        paginator = Paginator(vehicles, per_page)

        try:
            vehicles_page = paginator.page(page)
        except PageNotAnInteger:
            vehicles_page = paginator.page(1)
        except EmptyPage:
            vehicles_page = paginator.page(paginator.num_pages)

        # OPTIMIZED: Serialize vehicles with efficient image handling
        vehicles_data = []
        for vehicle in vehicles_page:
            # Get image URL efficiently - single function call
            image_url = get_vehicle_image_url(vehicle)

            vehicle_data = {
                'id': vehicle.id,
                'make': vehicle.make,
                'model': vehicle.model,
                'year': vehicle.year,
                'color': getattr(vehicle, 'color', 'Standard'),
                'fuel_type': getattr(vehicle, 'fuel_type', 'Petrol'),
                'capacity': vehicle.capacity,
                'vehicle_type': vehicle.vehicle_type,
                'license_plate': getattr(vehicle, 'license_plate', ''),
                'price_per_day': float(getattr(vehicle, 'price_per_day', 0)),
                'is_active': getattr(vehicle, 'is_active', True),
                'features': getattr(vehicle, 'features', []),
                'accessibility_features': getattr(vehicle, 'accessibility_features', []),
                'image_url': image_url,
            }
            vehicles_data.append(vehicle_data)

        response_data = {
            'vehicles': vehicles_data,
            'pagination': {
                'page': int(page),
                'per_page': per_page,
                'total_pages': paginator.num_pages,
                'total_items': total_count,
            }
        }

        return create_success_response(response_data)

    except Exception as e:
        logger.exception(f"Vehicles API error: {e}")
        return create_error_response("Error fetching vehicles", status=500)


def get_vehicle_image_url(vehicle):
    """Helper function to efficiently get vehicle image URL"""
    # Check image attributes in order of preference, but only once each
    if hasattr(vehicle, 'image') and vehicle.image:
        return vehicle.image.url
    elif hasattr(vehicle, 'photo') and vehicle.photo:
        return vehicle.photo.url
    elif hasattr(vehicle, 'image_url') and vehicle.image_url:
        return vehicle.image_url
    return None

def nairobi_airport_transfers(request):
    """Render Nairobi airport transfers page."""
    transfer_services = getattr(settings, 'TRANSFER_SERVICES', [])
    transfer_prices = getattr(settings, 'TRANSFER_PRICES', {})

    context = {
        "transfer_services": transfer_services,
        "transfer_prices": transfer_prices,
    }
    return render(request, "nairobi_airport_transfers.html", context)


@staff_member_required
def modern_admin_dashboard(request):
    """Render modern admin dashboard."""
    # Add dashboard logic here
    return render(request, "admin/modern_dashboard.html")


@staff_member_required
def admin_tour_approval(request):
    """Render tour approval page."""
    tours = Tour.objects.filter(is_approved=False)
    return render(request, "admin/tour_approval.html", {"tours": tours})


@staff_member_required
def approve_tour(request, tour_id):
    """Approve a tour."""
    tour = get_object_or_404(Tour, id=tour_id)
    tour.is_approved = True
    tour.approved_by = request.user
    tour.approved_at = timezone.now()
    tour.save()
    messages.success(request, "Tour approved successfully.")
    return redirect("bookings:admin_tour_approval")


@staff_member_required
def reject_tour(request, tour_id):
    """Reject a tour."""
    tour = get_object_or_404(Tour, id=tour_id)
    tour.delete()
    messages.success(request, "Tour rejected successfully.")
    return redirect("bookings:admin_tour_approval")


def tour_price_api(request, tour_id):
    """API endpoint to get tour pricing."""
    tour = get_object_or_404(Tour, id=tour_id)
    adults = int(request.GET.get('adults', 1))
    children = int(request.GET.get('children', 0))

    pricing = get_tour_pricing(tour, adults, children)
    return JsonResponse(pricing)


def tour_availability_api(request, tour_id):
    """API endpoint to check tour availability."""
    tour = get_object_or_404(Tour, id=tour_id)
    travel_date_str = request.GET.get('travel_date')

    if not travel_date_str:
        return JsonResponse({"error": "travel_date is required"}, status=400)

    try:
        travel_date = datetime.strptime(travel_date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({"error": "Invalid date format"}, status=400)

    availability = check_tour_availability(tour, travel_date)
    return JsonResponse(availability)


def tours_api(request):
    """API endpoint to get tours."""
    tours = Tour.objects.filter(is_approved=True, available=True)

    # Apply filters
    category = request.GET.get('category')
    if category:
        tours = tours.filter(category__slug=category)

    # Serialize
    tours_data = []
    for tour in tours:
        tours_data.append({
            'id': tour.id,
            'title': tour.title,
            'slug': tour.slug,
            'price': float(tour.current_price),
            'image': tour.get_image_src(),
            'duration': tour.total_duration,
            'category': tour.category.name if tour.category else None,
        })

    return JsonResponse({"tours": tours_data})


def contact_submit(request):
    """Handle contact form submission."""
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            contact_message = form.save()

            # Send notification email
            subject = f"New Contact: {contact_message.subject}"
            message = f"""
From: {contact_message.name}
Email: {contact_message.email}
Phone: {contact_message.phone}

Message:
{contact_message.message}
            """

            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [settings.ADMIN_EMAIL],
                    fail_silently=False,
                )
                messages.success(request, "Your message has been sent. We'll get back to you soon.")
            except Exception as e:
                logger.error(f"Error sending contact email: {e}")
                messages.error(request, "There was an error sending your message. Please try again.")

            return redirect('bookings:contact')
        else:
            messages.error(request, "Please correct the errors below.")

    return redirect('bookings:contact')


def health_check(request):
    """Health check endpoint."""
    return JsonResponse({"status": "healthy"})


def payment_success(request):
    """Generic payment success page."""
    return render(request, "payments/success.html")

def get_serializer_context(self):
    context = super().get_serializer_context()
    context['request'] = self.request
    return context

from rest_framework.response import Response
from rest_framework.decorators import api_view
from .models import Vehicle
from .serializers import VehicleSerializer

@api_view(['GET'])
def vehicle_list(request):
    vehicles = Vehicle.objects.filter(is_active=True)
    serializer = VehicleSerializer(vehicles, many=True, context={'request': request})
    return Response(serializer.data)


from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from .models import Driver

def driver_action(request, driver_id):
    """Toggle a driver's active status from the admin button."""
    driver = get_object_or_404(Driver, id=driver_id)
    driver.is_active = not driver.is_active
    driver.save()
    messages.success(
        request,
        f"Driver '{driver.name}' status changed to {'Active' if driver.is_active else 'Inactive'}."
    )
    return redirect("/admin/bookings/driver/")


from django.shortcuts import get_object_or_404, redirect
from .models import Booking


def booking_action(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    # Example logic (customize this part)
    booking.status = "processed"
    booking.save()

    # Redirect back to the booking admin page
    return redirect("admin:bookings_booking_change", booking_id)
