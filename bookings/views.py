# ==========================================================
# DJANGO IMPORTS
# ==========================================================
import json
import logging
import uuid
from decimal import Decimal, InvalidOperation
import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import send_mail
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from airport.dashboard import CustomIndexDashboard
from airport.dashboard import CustomMenu

# ==========================================================
# PROJECT IMPORTS
# ==========================================================
from .models import (
    Tour, Destination, Video, Booking, Payment, ContactMessage, Trip, PaymentStatus
)
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
    """Public tours page with all trips, videos, and destinations."""
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
# HELPERS
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
# PAYMENT FLOW - PESAPAL
# ==========================================================
def tour_payment(request, tour_id):
    """
    Render payment page for logged-in users or redirect guests to guest checkout.
    Handles Pesapal payments.
    """
    tour = get_object_or_404(Tour, id=tour_id)

    if not request.user.is_authenticated:
        return redirect("guest_checkout", tour_id=tour.id)

    context = {"tour": tour, "pesapal_iframe_url": None, "error": None}

    try:
        # Build callback URL
        callback_url = request.build_absolute_uri(reverse("pesapal_callback"))

        redirect_url, order_reference, tracking_id = create_pesapal_order(
            order_id=tour.id,
            amount=tour.price_per_person,
            description=f"Payment for Tour {tour.title}",
            email=request.user.email,
            phone=normalize_phone_number(getattr(request.user, "phone", "0700000000")),
            first_name=getattr(request.user, "first_name", "Guest"),
            last_name=getattr(request.user, "last_name", "User"),
        )

        if redirect_url:
            Payment.objects.create(
                user=request.user,
                tour=tour,
                amount=tour.price_per_person,
                reference=order_reference,
                pesapal_reference=tracking_id,
                transaction_id=tracking_id,
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


@csrf_exempt
def pesapal_callback(request):
    """
    Handles Pesapal browser redirect or IPN callback.
    Updates Payment status and sends admin email.
    """
    if request.method != "GET":
        return HttpResponse("Method not allowed", status=405)

    tracking_id = request.GET.get("OrderTrackingId")
    merchant_ref = request.GET.get("OrderMerchantReference")

    if not tracking_id:
        return HttpResponse("❌ Missing tracking ID.", status=400)

    payment = Payment.objects.filter(pesapal_reference=tracking_id).first() or \
              Payment.objects.filter(reference=merchant_ref).first()

    if not payment:
        return HttpResponse("❌ Payment not found.", status=404)

    try:
        # ✅ Use correct v3 status endpoint (GET with query params)
        access_token = PesapalAuth.get_token()
        pesapal_url = "https://pay.pesapal.com/v3/api/Transactions/GetTransactionStatus"
        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.get(
            pesapal_url,
            params={"orderTrackingId": tracking_id},
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        # ✅ Map Pesapal response fields properly
        live_status = data.get("status", "").upper()
        confirmation_code = data.get("confirmation_code")
        payment_method = data.get("payment_method")

        status_map = {
            "COMPLETED": PaymentStatus.SUCCESS,
            "FAILED": PaymentStatus.FAILED,
            "PENDING": PaymentStatus.PENDING,
            "CANCELLED": PaymentStatus.CANCELLED,
            "REFUNDED": PaymentStatus.REFUNDED,
        }
        new_status = status_map.get(live_status, PaymentStatus.PENDING)

        # ✅ Update payment
        payment.status = new_status
        payment.transaction_id = confirmation_code or payment.transaction_id
        payment.pesapal_reference = tracking_id
        payment.method = payment_method or payment.method
        if new_status == PaymentStatus.SUCCESS:
            payment.amount_paid = data.get("amount", payment.amount)
            payment.paid_on = timezone.now()
        payment.updated_at = timezone.now()
        payment.save()

        # Remove duplicate records
        Payment.objects.filter(pesapal_reference=tracking_id).exclude(id=payment.id).delete()

        # ✅ Send admin email
        subject = f"Pesapal Payment Update: {payment.status} - {payment.pesapal_reference}"
        message = f"""
Payment Details:

Booking: {payment.booking or '-'}
Tour: {payment.tour or '-'}
Amount: {payment.amount} {payment.currency}
Provider: {payment.provider}
Status: {payment.status}
Pesapal Reference: {payment.pesapal_reference}
Transaction ID: {payment.transaction_id}
Payment Method: {payment.method}
Guest Email: {payment.guest_email or '-'}
Guest Phone: {payment.guest_phone or '-'}
Description: {payment.description or '-'}
Created At: {payment.created_at}
"""
        send_mail(subject, message,
                  settings.DEFAULT_FROM_EMAIL,
                  [settings.ADMIN_EMAIL],
                  fail_silently=False)

    except Exception as e:
        logger.exception("Pesapal callback failed: %s", e)

        # ✅ Redirect user straight to receipt page
    return redirect("receipt", pk=payment.id)


@csrf_exempt
def pesapal_ipn(request):
    """
    Handle Pesapal Instant Payment Notifications (IPN).
    - GET: Pesapal may ping the endpoint to check if it's alive.
    - POST: Pesapal sends actual payment notifications.
    """
    if request.method == "GET":
        return JsonResponse({"success": True, "message": "IPN endpoint is alive"}, status=200)

    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
            tracking_id = data.get("OrderTrackingId") or data.get("order_tracking_id")
            merchant_ref = data.get("OrderMerchantReference") or data.get("order_reference")
            confirmation_code = data.get("PaymentConfirmationCode") or data.get("confirmation_code")
            payment_method = data.get("PaymentMethod") or data.get("payment_method")

            if not tracking_id or not merchant_ref:
                return JsonResponse({"success": False, "message": "Missing required parameters"}, status=400)

            # ✅ FIX coming later in Step 2 (use POST instead of GET)
            headers = {
                "Authorization": f"Bearer {settings.PESAPAL_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {"OrderTrackingId": tracking_id, "OrderMerchantReference": merchant_ref}

            response = requests.get(   # ← will update this to POST in the next step
                "https://www.pesapal.com/API/REST/v3/Transactions/GetTransactionStatus",
                params=payload, headers=headers, timeout=10
            )
            response.raise_for_status()
            status_data = response.json()
            status = status_data.get("Status", "").upper()

            # Update Payment
            payment = Payment.objects.filter(reference=merchant_ref, provider="PESAPAL").first()
            if payment:
                payment.status = status
                payment.transaction_id = confirmation_code or tracking_id
                payment.method = payment_method or payment.method
                if status == "COMPLETED":
                    payment.amount_paid = status_data.get("Amount", payment.amount)
                    payment.paid_on = timezone.now()
                payment.save()

            # Update Booking if exists
            booking = Booking.objects.filter(reference=merchant_ref).first()
            if booking:
                booking.status = status
                booking.transaction_id = confirmation_code or tracking_id
                booking.save()

            return JsonResponse({"success": True, "message": "IPN processed"})

        except Exception as e:
            logger.exception("Pesapal IPN error: %s", e)
            return JsonResponse({"success": False, "message": "Server error"}, status=500)

    return JsonResponse({"success": False, "message": "Method not allowed"}, status=405)

# ==========================================================
# MPESA PAYMENT
# ==========================================================
@csrf_exempt
@login_required
@require_http_methods(["POST"])
def mpesa_payment(request, tour_id):
    """
    Initiates Mpesa STK Push payment for a given tour.
    """
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
                status=PaymentStatus.PENDING,
            )
            return JsonResponse({"success": True, "message": "STK Push sent", "response": response})
        else:
            return JsonResponse({"success": False, "message": "Failed to initiate Mpesa payment"}, status=500)

    except Exception as e:
        logger.exception("Mpesa payment error: %s", e)
        return JsonResponse({"success": False, "message": "Unexpected error"}, status=500)

# ==========================================================
# PAYMENT PAGES
# ==========================================================
def payment_success(request):
    return render(request, "payments/success.html")


def payment_failed(request):
    return render(request, "payments/failed.html")


# ==========================================================
# DRIVER DASHBOARD & TOUR MANAGEMENT
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


@login_required
def add_tour(request):
    if not hasattr(request.user, "driver"):
        messages.error(request, "You must log in as a driver.")
        return redirect("driver_login")

    if request.method == "POST":
        title = request.POST.get("title", "").strip() or "Untitled Tour"
        description = request.POST.get("description", "").strip()
        itinerary = request.POST.get("itinerary", "").strip()
        duration_days = max(1, int(request.POST.get("duration_days", "1")))
        price_per_person = Decimal(request.POST.get("price_per_person", "0.00"))

        tour = Tour.objects.create(
            title=title,
            description=description,
            itinerary=itinerary,
            duration_days=duration_days,
            price_per_person=price_per_person,
            available=True,
            created_by=request.user,
            is_approved=True,
        )

        if "image" in request.FILES:
            tour.image = request.FILES["image"]
        if "video" in request.FILES:
            tour.video = request.FILES["video"]
        tour.save()
        messages.success(request, f'Tour "{tour.title}" added successfully ✅')

    return redirect("driver_dashboard")


@login_required
def edit_tour(request, tour_id):
    tour = get_object_or_404(Tour, id=tour_id)
    if tour.created_by != request.user and not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect("driver_dashboard")

    if request.method == "POST":
        tour.title = request.POST.get("title", tour.title)
        tour.description = request.POST.get("description", tour.description)
        tour.itinerary = request.POST.get("itinerary", tour.itinerary)
        tour.duration_days = int(request.POST.get("duration_days", tour.duration_days))
        tour.price_per_person = Decimal(request.POST.get("price_per_person", tour.price_per_person))
        if "image" in request.FILES:
            tour.image = request.FILES["image"]
        if "video" in request.FILES:
            tour.video = request.FILES["video"]
        tour.save()
        messages.success(request, f'Tour "{tour.title}" updated.')
        return redirect("driver_dashboard")

    return render(request, "edit_tour.html", {"tour": tour})


@login_required
def delete_tour(request, tour_id):
    tour = get_object_or_404(Tour, id=tour_id)
    if tour.created_by != request.user and not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect("driver_dashboard")
    tour.delete()
    messages.success(request, "Tour deleted.")
    return redirect("driver_dashboard")


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
# STAFF / DEBUG UTILITIES
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
# GUEST CHECKOUT & SESSION PESAPAL
# ==========================================================
def guest_checkout(request, tour_id):
    """
    Handle guest form submission, save booking details,
    and create a Payment record for receipt.
    """
    tour = get_object_or_404(Tour, id=tour_id)

    if request.method == "POST":
        # Capture guest form data
        full_name = request.POST.get("full_name")
        email = request.POST.get("email")
        phone = f"{request.POST.get('country_code')}{request.POST.get('phone')}"
        adults = int(request.POST.get("adults", 0))
        children = int(request.POST.get("children", 0))
        days = int(request.POST.get("days", 1))
        travel_date = request.POST.get("travel_date")

        # Calculate costs
        adult_cost = adults * tour.price
        child_cost = children * (tour.price * Decimal("0.5"))  # Example: half price for kids
        total = adult_cost + child_cost

        # Save Payment object
        payment = Payment.objects.create(
            tour=tour,
            guest_full_name=full_name,
            guest_email=email,
            guest_phone=phone,
            adults=adults,
            children=children,
            days=days,
            travel_date=travel_date,
            amount_paid=total,
        )

        # Redirect to receipt page
        return redirect("receipt", pk=payment.pk)

    return HttpResponse(status=405)  # Method not allowed

@csrf_exempt
def process_guest_info(request):
    """Store guest email and phone in session."""
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
    """Create Pesapal order for guests."""
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Invalid request method."})

    try:
        data = json.loads(request.body.decode("utf-8"))
        amount = data.get("amount")
        description = data.get("description", "Payment for tour/booking")
        email = request.session.get("guest_email")
        phone = request.session.get("guest_phone")

        if not email or not phone:
            return JsonResponse({"success": False, "message": "Missing guest email or phone."})

        order_id = f"GUEST-{uuid.uuid4().hex[:10]}"
        redirect_url, unique_code, order_tracking_id = create_pesapal_order(
            order_id=order_id,
            amount=amount,
            description=description,
            email=email,
            phone=normalize_phone_number(phone),
            first_name="Guest",
            last_name="User",
        )

        request.session["guest_order_tracking_id"] = order_tracking_id
        request.session["guest_order_merchant_ref"] = unique_code
        request.session["guest_order_amount"] = amount
        request.session["guest_order_description"] = description

        return JsonResponse({"success": True, "redirect_url": redirect_url})

    except Exception as e:
        logger.exception("Guest Pesapal order creation error: %s", e)
        return JsonResponse({"success": False, "message": str(e)})


@csrf_exempt
@require_http_methods(["POST"])
def guest_pesapal_callback(request):
    """Update guest payment status."""
    try:
        data = json.loads(request.body.decode("utf-8"))
        tracking_id = data.get("order_tracking_id")
        status = data.get("status")

        if tracking_id != request.session.get("guest_order_tracking_id"):
            return JsonResponse({"success": False, "message": "Order not found"}, status=404)

        request.session["guest_payment_status"] = status.upper()
        return JsonResponse({"success": True, "message": "Guest payment updated"})

    except Exception as e:
        logger.exception("Guest Pesapal callback error: %s", e)
        return JsonResponse({"success": False, "message": "Server error"}, status=500)


def guest_payment_success(request):
    """Render guest payment success page."""
    status = request.session.get("guest_payment_status")
    return render(request, "payments/guest_success.html" if status == "COMPLETED" else "payments/guest_failed.html")


def guest_payment_failed(request):
    """Render guest payment failure page."""
    return render(request, "payments/guest_failed.html")


@staff_member_required
def modern_admin_dashboard(request):
    """
    Renders the modern custom admin dashboard at /admin/brymax/
    Only accessible by staff users.
    """
    return render(request, "admin/brymax_dashboard.html")


import requests, logging
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse
from django.contrib.admin.views.decorators import staff_member_required

logger = logging.getLogger(__name__)

@staff_member_required
def register_pesapal_ipn(request):
    """
    Register our IPN URL with Pesapal and return the IPN ID.
    Run this once and copy IPN_ID to settings.
    """
    try:
        # Get access token
        auth_url = f"{settings.PESAPAL_BASE_URL}/api/Auth/RequestToken"
        auth_payload = {
            "consumer_key": settings.PESAPAL_CONSUMER_KEY,
            "consumer_secret": settings.PESAPAL_CONSUMER_SECRET,
        }
        token_res = requests.post(auth_url, json=auth_payload, timeout=15)
        token_res.raise_for_status()
        token_json = token_res.json()
        access_token = token_json.get("token") or token_json.get("access_token")

        # Build IPN registration request
        ipn_url = request.build_absolute_uri(reverse("pesapal_ipn"))
        payload = {"url": ipn_url, "ipn_notification_type": "GET"}
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        res = requests.post(f"{settings.PESAPAL_BASE_URL}/api/URLSetup/RegisterIPN",
                            json=payload, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()

        ipn_id = data.get("ipn_id")
        return JsonResponse({"success": True, "ipn_id": ipn_id, "data": data})

    except Exception as e:
        logger.exception("IPN registration failed: %s", e)
        return JsonResponse({"success": False, "message": str(e)}, status=500)

from django.views.generic import DetailView
from .models import Payment

class ReceiptView(DetailView):
    model = Payment
    template_name = 'payments/receipt.html'
    context_object_name = 'payment'