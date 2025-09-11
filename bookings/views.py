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
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, csrf_protect
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
# PAYMENT FLOW
# ==========================================================
def tour_payment(request, tour_id):
    """
    Render payment page for logged-in users or redirect guests to guest checkout.
    Handles Pesapal payments.
    """
    tour = get_object_or_404(Tour, id=tour_id)

    # Redirect unauthenticated users to guest checkout
    if not request.user.is_authenticated:
        return redirect("guest_checkout", tour_id=tour.id)

    context = {"tour": tour, "pesapal_iframe_url": None, "error": None}

    try:
        callback_url = request.build_absolute_uri(reverse("pesapal_callback"))

        # 🔹 Call pesapal.py helper
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
            # 🔹 Save payment in DB
            Payment.objects.create(
                user=request.user,
                tour=tour,
                amount=tour.price_per_person,
                reference=tracking_id,   # store Pesapal order_tracking_id
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

# ===============================
# 🌍 Browser Redirect Callback (GET) - Live Status Query
# ===============================
@csrf_exempt
def pesapal_callback(request):
    """
    Handle Pesapal browser callback after payment.
    Queries Pesapal API for live payment status and redirects to user-friendly page.
    """
    if request.method != "GET":
        return HttpResponse("Method not allowed", status=405)

    tracking_id = request.GET.get("OrderTrackingId")
    merchant_ref = request.GET.get("OrderMerchantReference")

    if not tracking_id or not merchant_ref:
        return HttpResponse("❌ Missing required payment parameters.", status=400)

    try:
        payment = Payment.objects.get(reference=tracking_id, provider="PESAPAL")
        is_guest = merchant_ref.startswith("GUEST-")

        # 🔹 Query Pesapal live
        status = payment.status.upper()  # fallback
        try:
            access_token = PesapalAuth.get_token()
            pesapal_url = f"https://www.pesapal.com/API/QueryPaymentStatus?tracking_id={tracking_id}"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            response = requests.get(pesapal_url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            live_status = data.get("status", "").upper()

            if live_status and live_status != status:
                payment.status = live_status
                payment.updated_at = timezone.now()
                payment.save()

                if live_status == "COMPLETED":
                    send_payment_confirmation_email(payment)

            status = payment.status.upper()

        except Exception as e:
            logger.exception("Pesapal live status query failed: %s", e)
            # fallback to DB status

        # 🔹 Redirect to user-friendly progress page
        return render(
            request,
            "payments/payment_progress.html",  # page shows a spinner/progress bar
            {
                "payment": payment,
                "status": status,
                "is_guest": is_guest,
            }
        )

    except Payment.DoesNotExist:
        template = "payments/guest_failed.html" if merchant_ref.startswith("GUEST-") else "payments/failed.html"
        return render(request, template, {"error": "Payment not found"})
# ===============================
# 🔔 Server-to-Server IPN (POST JSON)
# ===============================
@csrf_exempt
@require_http_methods(["POST"])
def pesapal_ipn(request):
    """Pesapal server-to-server notification (IPN)."""
    try:
        data = json.loads(request.body.decode("utf-8"))
        tracking_id = data.get("order_tracking_id") or data.get("order_reference")
        status = data.get("status")

        if not tracking_id or not status:
            return JsonResponse({"success": False, "message": "Missing parameters"}, status=400)

        try:
            payment = Payment.objects.get(reference=tracking_id, provider="PESAPAL")
            payment.status = status.upper()
            payment.updated_at = timezone.now()
            payment.save()

            if status.upper() == "COMPLETED":
                send_payment_confirmation_email(payment)

            return JsonResponse({"success": True, "message": "IPN processed"})

        except Payment.DoesNotExist:
            return JsonResponse({"success": False, "message": "Payment not found"}, status=404)

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.exception("Pesapal IPN error: %s", e)
        return JsonResponse({"success": False, "message": "Server error"}, status=500)


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


def payment_success(request):
    return render(request, "payments/success.html")


def payment_failed(request):
    return render(request, "payments/failed.html")


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


@login_required
def add_tour(request):
    if not hasattr(request.user, "driver"):
        messages.error(request, "You must log in as a driver.")
        return redirect("driver_login")

    if request.method == "POST":
        title = request.POST.get("title", "").strip() or "Untitled Tour"
        description = request.POST.get("description", "").strip()
        itinerary = request.POST.get("itinerary", "").strip()
        duration_raw = request.POST.get("duration_days", "1")
        price_raw = request.POST.get("price_per_person", "0")

        try:
            duration_days = max(1, int(duration_raw))
        except (ValueError, TypeError):
            duration_days = 1

        try:
            price_per_person = Decimal(price_raw)
        except (InvalidOperation, TypeError):
            price_per_person = Decimal("0.00")

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

        try:
            tour.duration_days = int(request.POST.get("duration_days", tour.duration_days))
        except (ValueError, TypeError):
            pass

        try:
            tour.price_per_person = Decimal(request.POST.get("price_per_person", tour.price_per_person))
        except (InvalidOperation, TypeError):
            pass

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
# GUEST CHECKOUT & SESSION-BASED PESAPAL PAYMENTS
# ==========================================================
from django.views.decorators.csrf import csrf_exempt
import uuid

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

    context = {
        "booking": booking,
        "tour": tour,
        "pesapal_iframe_url": None,
        "error": None,
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
    Create a Pesapal order for guests and return the redirect URL
    """
    if request.method == "POST":
        data = json.loads(request.body.decode("utf-8"))
        amount = data.get("amount")
        description = data.get("description", "Payment for tour/booking")

        email = request.session.get("guest_email")
        phone = request.session.get("guest_phone")

        if not email or not phone:
            return JsonResponse({"success": False, "message": "Missing guest email or phone."})

        try:
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

            # Store guest payment in session
            request.session["guest_order_tracking_id"] = order_tracking_id
            request.session["guest_order_amount"] = amount
            request.session["guest_order_description"] = description

            return JsonResponse({"success": True, "redirect_url": redirect_url})

        except Exception as e:
            logger.exception("Guest Pesapal order creation error: %s", e)
            return JsonResponse({"success": False, "message": str(e)})

    return JsonResponse({"success": False, "message": "Invalid request method."})


@csrf_exempt
@require_http_methods(["POST"])
def guest_pesapal_callback(request):
    """
    Pesapal callback for guest payments
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
        tracking_id = data.get("order_tracking_id")
        status = data.get("status")

        if not tracking_id or not status:
            return JsonResponse({"success": False, "message": "Missing parameters"}, status=400)

        # Only process if it matches the session's guest order
        if tracking_id != request.session.get("guest_order_tracking_id"):
            return JsonResponse({"success": False, "message": "Order not found"}, status=404)

        # Mark session as completed
        request.session["guest_payment_status"] = status.upper()
        return JsonResponse({"success": True, "message": "Guest payment updated"})

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.exception("Guest Pesapal callback error: %s", e)
        return JsonResponse({"success": False, "message": "Server error"}, status=500)


def guest_payment_success(request):
    """
    Display guest payment success page
    """
    status = request.session.get("guest_payment_status")
    if status == "COMPLETED":
        return render(request, "payments/guest_success.html")
    return render(request, "payments/guest_failed.html")


def guest_payment_failed(request):
    """
    Display guest payment failure page
    """
    return render(request, "payments/guest_failed.html")