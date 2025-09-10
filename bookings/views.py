# ==========================================================
# DJANGO IMPORTS
# ==========================================================
import json
import logging
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.mail import send_mail

# ==========================================================
# PROJECT IMPORTS
# ==========================================================
from .models import Tour, Destination, Video, Booking, Payment, ContactMessage, Trip
from .services import PesaPalService, MpesaSTKPush
from .utils.pesapal_auth import PesapalAuth
from .pesapal import create_pesapal_order

logger = logging.getLogger(__name__)

# ==========================================================
# FRONTEND PAGES
# ==========================================================
def home(request):
    return render(request, "home.html")

def book_online(request):
    return render(request, "book_online.html")

def nairobi_transfers(request):
    return render(request, "nairobi_transfers.html")

def excursions(request):
    return render(request, "excursions.html")

def tours(request):
    """Public tours page."""
    context = {
        "tours": Tour.objects.filter(is_approved=True, available=True).order_by("-created_at"),
        "trips": Trip.objects.all().order_by("-created_at"),
        "videos": Video.objects.all().order_by("-created_at"),
        "destinations": Destination.objects.all().order_by("-created_at"),
    }
    return render(request, "tours.html", context)

def contact(request):
    return render(request, "contact.html")

def terms(request):
    return render(request, "terms.html")

def about(request):
    return render(request, "about.html")

# ==========================================================
# HELPER FUNCTIONS
# ==========================================================
def normalize_phone_number(phone: str) -> str | None:
    """Convert phone number to E.164 format (+254...)."""
    if not phone:
        return None
    phone = phone.strip()
    if phone.startswith("0"):
        return "+254" + phone[1:]
    if phone.startswith("+"):
        return phone
    return None

def send_payment_confirmation_email(payment):
    """Send email confirmation after successful payment."""
    subject = f"Payment Confirmation - {payment.tour.title}"
    message = (
        f"Dear {payment.user.get_full_name()},\n\n"
        f"We have received your payment of KES {payment.amount} for {payment.tour.title}.\n"
        "Thank you for booking with us!"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [payment.user.email])

# ==========================================================
# PAYMENT FLOW (Pesapal + Mpesa)
# ==========================================================
@login_required
def tour_payment(request, tour_id):
    """Render payment page for logged-in users (Pesapal)."""
    tour = get_object_or_404(Tour, id=tour_id)
    context = {"tour": tour, "pesapal_iframe_url": None, "error": None}

    try:
        callback_url = request.build_absolute_uri(reverse("pesapal_callback"))

        redirect_url, order_reference, tracking_id = create_pesapal_order(
            order_id=tour.id,
            amount=tour.price_per_person,
            description=f"Payment for Tour {tour.title}",
            email=request.user.email,
            phone=normalize_phone_number(getattr(request.user, "phone", "0700000000")),
        )

        if redirect_url:
            # Save payment record
            Payment.objects.create(
                user=request.user,
                tour=tour,
                amount=tour.price_per_person,
                reference=tracking_id,
                provider="PESAPAL",
                status="PENDING",
                description=f"Payment for Tour {tour.title}",
            )
            context["pesapal_iframe_url"] = redirect_url
        else:
            context["error"] = "Payment service unavailable."

    except Exception as e:
        logger.exception("Pesapal payment initialization error: %s", e)
        context["error"] = "Error initializing payment."

    return render(request, "payments/tour_payment.html", context)

# ------------------ Pesapal Browser Callback ------------------
@csrf_exempt
def pesapal_callback(request):
    """Browser redirect after Pesapal payment."""
    tracking_id = request.GET.get("OrderTrackingId")
    if not tracking_id:
        return HttpResponse("❌ Missing OrderTrackingId", status=400)

    try:
        payment = Payment.objects.get(reference=tracking_id, provider="PESAPAL")
        if payment.status.upper() == "COMPLETED":
            return redirect("payment_receipt", payment_id=payment.id)
        else:
            return redirect("payment_failed")
    except Payment.DoesNotExist:
        return HttpResponse("❌ Payment not found.", status=404)

# ------------------ Pesapal IPN (Server Notification) ------------------
@csrf_exempt
@require_http_methods(["POST"])
def pesapal_ipn(request):
    """Pesapal IPN updates (server-to-server)."""
    try:
        data = json.loads(request.body.decode("utf-8"))
        tracking_id = data.get("order_tracking_id")
        status = data.get("status")

        if not tracking_id or not status:
            return JsonResponse({"success": False, "message": "Missing parameters"}, status=400)

        payment = Payment.objects.get(reference=tracking_id, provider="PESAPAL")
        payment.status = status.upper()
        payment.updated_at = timezone.now()
        payment.save()

        if status.upper() == "COMPLETED":
            send_payment_confirmation_email(payment)

        return JsonResponse({"success": True, "message": "IPN processed"})

    except Payment.DoesNotExist:
        return JsonResponse({"success": False, "message": "Payment not found"}, status=404)
    except Exception as e:
        logger.exception("Pesapal IPN error: %s", e)
        return JsonResponse({"success": False, "message": "Server error"}, status=500)

# ------------------ Mpesa STK Push ------------------
@csrf_exempt
@login_required
@require_http_methods(["POST"])
def mpesa_payment(request, tour_id):
    """Initiate Mpesa STK Push for a tour."""
    try:
        data = json.loads(request.body)
        phone_number = normalize_phone_number(data.get("phone_number"))
        if not phone_number:
            return JsonResponse({"success": False, "message": "Invalid phone number"}, status=400)

        tour = get_object_or_404(Tour, id=tour_id)
        mpesa = MpesaSTKPush()
        response = mpesa.stk_push(
            phone_number=phone_number,
            amount=tour.price_per_person,
            account_reference=f"Tour-{tour.id}",
            transaction_desc=f"Payment for Tour {tour.title}",
        )

        if response.get("CheckoutRequestID"):
            Payment.objects.create(
                user=request.user,
                tour=tour,
                amount=tour.price_per_person,
                reference=response.get("CheckoutRequestID"),
                provider="MPESA",
                status="PENDING",
            )
            return JsonResponse({"success": True, "message": "STK Push sent", "response": response})
        else:
            return JsonResponse({"success": False, "message": "Failed to initiate Mpesa payment"}, status=500)

    except Exception as e:
        logger.exception("Mpesa payment error: %s", e)
        return JsonResponse({"success": False, "message": "Unexpected error"}, status=500)

# ==========================================================
# PAYMENT RESULT PAGES
# ==========================================================
from django.shortcuts import get_object_or_404, render
from .models import Payment


def payment_success(request):
    return render(request, "payments/success.html")


def payment_failed(request):
    return render(request, "payments/guest_failed.html")


def payment_receipt(request, payment_id):
    """
    Show receipt after successful payment.
    Works for both logged-in users and guest checkouts.
    """
    payment = get_object_or_404(Payment, id=payment_id)

    if payment.user:
        # Logged-in user
        payer_name = f"{payment.user.first_name} {payment.user.last_name}".strip()
        payer_email = payment.user.email
        payer_phone = getattr(payment.user, "phone", "")
    else:
        # Guest user
        payer_name = payment.guest_name or "Guest User"
        payer_email = payment.guest_email
        payer_phone = payment.guest_phone

    context = {
        "payment": payment,
        "payer_name": payer_name,
        "payer_email": payer_email,
        "payer_phone": payer_phone,
    }
    return render(request, "payments/receipt.html", context)

# ==========================================================
# DRIVER DASHBOARD
# ==========================================================
@login_required
def driver_dashboard(request):
    if not hasattr(request.user, "driver"):
        messages.error(request, "You must log in as a driver.")
        return redirect("driver_login")

    driver = request.user.driver
    if request.method == "POST":
        if "new_trip" in request.POST:
            Trip.objects.create(
                driver=driver,
                destination=request.POST.get("destination"),
                date=request.POST.get("date"),
                earnings=request.POST.get("earnings") or 0,
                status=request.POST.get("status") or "Scheduled",
            )
            messages.success(request, "Trip added successfully.")
            return redirect("driver_dashboard")
        if "new_tour" in request.POST:
            return add_tour(request)

    context = {
        "driver": driver,
        "tripHistory": Trip.objects.filter(driver=driver).order_by("-date"),
        "tours": Tour.objects.filter(created_by=request.user).order_by("-created_at"),
        "bookings": Booking.objects.filter(driver=driver).select_related("customer", "destination"),
        "payments": Payment.objects.filter(booking__driver=driver).select_related("booking", "booking__customer"),
        "messages": ContactMessage.objects.none() if not request.user.is_staff else ContactMessage.objects.all(),
    }
    return render(request, "driver_dashboard.html", context)

# ==========================================================
# DRIVER TOUR MANAGEMENT
# ==========================================================
@login_required
def add_tour(request):
    # ... same as before (no changes for brevity)
    pass

@login_required
def edit_tour(request, tour_id):
    # ... same as before
    pass

@login_required
def delete_tour(request, tour_id):
    # ... same as before
    pass

# ==========================================================
# DRIVER LOGIN
# ==========================================================
def driver_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)

        if user:
            if hasattr(user, "driver"):
                login(request, user)
                return redirect("driver_dashboard")
            messages.error(request, "This account is not linked to a driver.")
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "driver_login.html")

# ==========================================================
# STAFF UTILITIES
# ==========================================================
@staff_member_required
def test_pesapal_auth(request):
    """Verify Pesapal token retrieval (staff only)."""
    try:
        token = PesapalAuth.get_token()
        masked = token[:6] + "..." + token[-6:] if len(token) > 12 else "*****"
        return JsonResponse({"status": "success", "token": masked})
    except Exception as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=500)

# ==========================================================
# GUEST CHECKOUT & PAYMENTS (updated)
# ==========================================================
def guest_checkout_page(request, tour_id=None, booking_id=None):
    """
    Render payment page for guests (non-logged-in users)
    """
    booking = None
    tour = None

    if booking_id:
        booking = get_object_or_404(Booking, id=booking_id)
    elif tour_id:
        tour = get_object_or_404(Tour, id=tour_id)

    # Prefill from session if present
    context = {
        "booking": booking,
        "tour": tour,
        "pesapal_iframe_url": None,
        "error": None,
        "guest_email": request.session.get("guest_email", ""),
        "guest_phone": request.session.get("guest_phone", ""),
    }
    return render(request, "guest_checkout.html", context)


@csrf_exempt
def process_guest_info(request):
    """
    Handle guest info form submission (email + phone) and store in session
    """
    if request.method == "POST":
        email = request.POST.get("email")
        phone = request.POST.get("phone")

        if not email or not phone:
            return JsonResponse({"success": False, "message": "Email and phone are required."})

        request.session["guest_email"] = email
        request.session["guest_phone"] = phone
        return JsonResponse({"success": True})

    return JsonResponse({"success": False, "message": "Invalid request method."})


@csrf_exempt
def create_guest_pesapal_order(request):
    """
    Create a Pesapal order for guests and return the redirect URL.
    Also create a Payment DB record for the guest so IPN/callbacks can update it.
    Expected POST JSON body:
    {
      "amount": 1500,
      "description": "Payment for Tour X",
      "tour_id": 12,           # optional
      "booking_id": 34         # optional
    }
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Invalid request method."})

    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON"}, status=400)

    amount = data.get("amount")
    description = data.get("description", "Payment for tour/booking")
    tour_id = data.get("tour_id")
    booking_id = data.get("booking_id")

    email = request.session.get("guest_email")
    phone = request.session.get("guest_phone")

    if not email or not phone:
        return JsonResponse({"success": False, "message": "Missing guest email or phone."}, status=400)

    # Validate amount minimally
    try:
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError("Amount must be positive")
    except Exception as e:
        return JsonResponse({"success": False, "message": "Invalid amount."}, status=400)

    tour = None
    booking = None
    if booking_id:
        booking = get_object_or_404(Booking, id=booking_id)
    elif tour_id:
        tour = get_object_or_404(Tour, id=tour_id)

    try:
        # Create a stable order id for Pesapal
        order_id = f"GUEST-{uuid.uuid4().hex[:12]}"

        # Create a DB Payment record BEFORE calling Pesapal so we can map updates
        payment = Payment.objects.create(
            user=None,
            tour=tour,
            booking=booking,
            amount=amount,
            reference="",  # will update after we receive tracking id from pesapal helper
            provider="PESAPAL",
            status="PENDING",
            description=f"{description} (guest: {email}, phone: {phone})",
            created_at=timezone.now(),
        )

        # call helper to create pesapal order
        redirect_url, unique_code, order_tracking_id = create_pesapal_order(
            order_id=order_id,
            amount=str(amount),  # ensure string if helper expects string
            description=description,
            email=email,
            phone=normalize_phone_number(phone),
        )

        # Update payment reference with Pesapal tracking id (if provided)
        if order_tracking_id:
            payment.reference = order_tracking_id
            payment.save()

        # Store guest payment id and some metadata in session for quick access after browser redirect
        request.session["guest_payment_id"] = payment.id
        request.session["guest_order_tracking_id"] = order_tracking_id
        request.session["guest_order_amount"] = str(amount)
        request.session["guest_order_description"] = description

        return JsonResponse({"success": True, "redirect_url": redirect_url})

    except Exception as e:
        logger.exception("Guest Pesapal order creation error: %s", e)
        # Try to delete incomplete payment if it exists
        try:
            payment.delete()
        except Exception:
            pass
        return JsonResponse({"success": False, "message": "Failed to create guest order."}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def guest_pesapal_callback(request):
    """
    Pesapal server-to-server callback for guest payments.
    Pesapal will POST JSON containing order_tracking_id and status (and other fields).
    We update the corresponding Payment record by reference.
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON"}, status=400)

    tracking_id = data.get("order_tracking_id") or data.get("order_trackingid") or data.get("orderReference")
    status = data.get("status")

    if not tracking_id or not status:
        return JsonResponse({"success": False, "message": "Missing parameters"}, status=400)

    try:
        payment = Payment.objects.get(reference=tracking_id, provider="PESAPAL")
        payment.status = status.upper()
        payment.updated_at = timezone.now()
        payment.save()

        # If completed, optionally send email
        if payment.status == "COMPLETED":
            try:
                # If this was a guest, we saved guest email in description; we can't call send_mail to unknown field.
                # If Payment.user is present, send email using the helper.
                if payment.user:
                    send_payment_confirmation_email(payment)
            except Exception:
                logger.exception("Error sending confirmation email for payment %s", payment.id)

        return JsonResponse({"success": True, "message": "Guest payment updated"})

    except Payment.DoesNotExist:
        return JsonResponse({"success": False, "message": "Payment not found"}, status=404)
    except Exception as e:
        logger.exception("Guest Pesapal callback error: %s", e)
        return JsonResponse({"success": False, "message": "Server error"}, status=500)


def guest_payment_success(request):
    """
    Display guest payment success page (receipt). We attempt to find a payment id
    in session; if not present, try looking up by tracking id that may be in session.
    """
    payment = None
    payment_id = request.session.get("guest_payment_id")
    if payment_id:
        payment = Payment.objects.filter(id=payment_id).first()

    # fallback: try by tracking id stored in session (in case payment was created/updated server-side)
    if not payment:
        tracking_id = request.session.get("guest_order_tracking_id")
        if tracking_id:
            payment = Payment.objects.filter(reference=tracking_id, provider="PESAPAL").first()

    if payment and payment.status == "COMPLETED":
        return render(request, "payments/receipt.html", {"payment": payment, "is_guest": True})

    # else show failed page (or pending)
    return render(request, "payments/guest_failed.html", {"payment": payment})


def guest_payment_failed(request):
    """
    Display guest payment failure page
    """
    payment = None
    payment_id = request.session.get("guest_payment_id")
    if payment_id:
        payment = Payment.objects.filter(id=payment_id).first()
    return render(request, "payments/guest_failed.html", {"payment": payment})