# ==========================================================
# DJANGO IMPORTS
# ==========================================================
import json
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_http_methods
from django.core.mail import send_mail

# ==========================================================
# PROJECT IMPORTS
# ==========================================================
from .models import (
    Tour, Destination, Video, Booking,
    Payment, ContactMessage, Trip
)
from .services import PesaPalService, MpesaSTKPush
from .utils.pesapal_auth import PesapalAuth
from .pesapal import create_pesapal_order

# Logger setup
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
    """Public tours page (tours + trips + videos + destinations)."""
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
# PAYMENT FLOW (Pesapal + Mpesa)
# ==========================================================
@login_required
def book_tour(request, tour_id):
    """Redirect authenticated user to payment page."""
    tour = get_object_or_404(Tour, id=tour_id)
    return redirect("tour_payment", tour_id=tour.id)

@login_required
def tour_payment(request, tour_id):
    """Show Pesapal iframe for tour payment."""
    tour = get_object_or_404(Tour, id=tour_id)
    context = {"tour": tour, "pesapal_iframe_url": None, "error": None}

    try:
        # Build callback URL
        callback_url = request.build_absolute_uri(reverse("pesapal_callback"))

        # Create Pesapal order
        redirect_url, order_reference, tracking_id = create_pesapal_order(
            order_id=tour.id,
            amount=tour.price_per_person,
            description=f"Payment for Tour {tour.title}",
            email=request.user.email,
            phone=normalize_phone_number(getattr(request.user, "phone", "0700000000")),
        )

        if redirect_url:
            # Create local Payment record (without callback_url)
            payment = Payment.objects.create(
                user=request.user,
                tour=tour,
                amount=tour.price_per_person,
                reference=tracking_id,   # 🔑 Save tracking_id
                provider="PESAPAL",
                status="PENDING",
                description=f"Payment for Tour {tour.title}"
            )

            # Register order with Pesapal (updates payment with pesapal_reference)
            payment.create_pesapal_order(callback_url)

            context["pesapal_iframe_url"] = redirect_url
        else:
            context["error"] = "Payment service unavailable."

    except Exception as e:
        logger.error(f"Payment initiation error: {str(e)}")
        context["error"] = "Error initializing payment."

    return render(request, "payments/tour_payment.html", context)


@require_http_methods(["POST"])
@csrf_exempt
def pesapal_callback(request):
    """Pesapal callback - updates payment status."""
    try:
        data = json.loads(request.body.decode("utf-8"))
        tracking_id = data.get("order_tracking_id")
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

            return JsonResponse({"success": True, "message": "Payment updated"})
        except Payment.DoesNotExist:
            logger.error("Callback for non-existent payment: %s", tracking_id)
            return JsonResponse({"success": False, "message": "Payment not found"}, status=404)

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.exception("Pesapal callback error: %s", str(e))
        return JsonResponse({"success": False, "message": "Server error"}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def pesapal_ipn(request):
    """Pesapal IPN (server-to-server notification)."""
    try:
        data = json.loads(request.body.decode("utf-8"))
        reference = data.get("order_reference")
        status = data.get("status")

        if not reference or not status:
            return JsonResponse({"success": False, "message": "Missing parameters"}, status=400)

        Payment.objects.filter(reference=reference, provider="PESAPAL").update(
            status=status.upper(),
            updated_at=timezone.now(),
        )
        return JsonResponse({"success": True, "message": "IPN processed"})

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.exception("Pesapal IPN error: %s", str(e))
        return JsonResponse({"success": False, "message": "Server error"}, status=500)


@require_http_methods(["POST"])
@csrf_protect
@login_required
def mpesa_payment(request, tour_id):
    """Mpesa STK Push with validation and error handling."""
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

        if response and response.get("CheckoutRequestID"):
            Payment.objects.create(
                user=request.user,
                tour=tour,
                amount=tour.price_per_person,
                reference=response.get("CheckoutRequestID", ""),
                provider="MPESA",
                status="PENDING",
            )
            return JsonResponse({
                "success": True,
                "message": "STK Push sent. Check your phone.",
                "response": response,
            })
        else:
            logger.error("Mpesa STK push failed: %s", response)
            return JsonResponse({"success": False, "message": "Failed to initiate Mpesa payment."}, status=500)

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.exception("Mpesa payment error: %s", str(e))
        return JsonResponse({"success": False, "message": "Unexpected error"}, status=500)


# ---------------- PAYMENT RESULT PAGES ------------------
def payment_success(request):
    return render(request, "payments/success.html")


def payment_failed(request):
    return render(request, "payments/failed.html")


# ==========================================================
# DRIVER DASHBOARD + ACTIONS
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
# HELPERS
# ==========================================================
def normalize_phone_number(phone):
    """Convert to E.164 (+254...) format."""
    if not phone:
        return None
    phone = str(phone).strip()
    if phone.startswith("0"):
        return "+254" + phone[1:]
    elif phone.startswith("+"):
        return phone
    return None


def verify_pesapal_ip(ip_address):
    """Verify Pesapal IP ranges (example)."""
    pesapal_ips = ["52.15.185.146", "52.15.178.181"]
    return ip_address in pesapal_ips


def send_payment_confirmation_email(payment):
    """Send email confirmation after payment success."""
    subject = f"Payment Confirmation - {payment.tour.title}"
    message = f"Dear {payment.user.get_full_name()},\n\n" \
              f"We have received your payment of KES {payment.amount} for {payment.tour.title}.\n" \
              f"Thank you for booking with us!"
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [payment.user.email])
