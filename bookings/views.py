# =======================
# DJANGO IMPORTS
# =======================
import json
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.http import (
    HttpRequest,
    JsonResponse,
    HttpResponse,
)
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_http_methods

# =======================
# PROJECT IMPORTS
# =======================
from .models import (
    Tour, Destination, Video, Booking, Payment, ContactMessage, Trip
)
from .services import PesaPalService, MpesaSTKPush
from .utils.pesapal_auth import PesapalAuth

# Setup logger
logger = logging.getLogger(__name__)


# ==========================================================
#  FRONTEND PAGES
# ==========================================================
def home(request: HttpRequest):
    return render(request, "home.html")


def book_online(request: HttpRequest):
    return render(request, "book_online.html")


def nairobi_transfers(request: HttpRequest):
    return render(request, "nairobi_transfers.html")


def excursions(request: HttpRequest):
    return render(request, "excursions.html")


def tours(request: HttpRequest):
    """Public tours page (shows tours + trips + videos + destinations)."""
    tours_qs = Tour.objects.filter(is_approved=True, available=True).order_by("-created_at")
    trips_qs = Trip.objects.all().order_by("-created_at")
    videos_qs = Video.objects.all().order_by("-created_at")
    destinations_qs = Destination.objects.all().order_by("-created_at")

    return render(request, "tours.html", {
        "tours": tours_qs,
        "trips": trips_qs,
        "videos": videos_qs,
        "destinations": destinations_qs,
    })


def contact(request: HttpRequest):
    return render(request, "contact.html")


def terms(request: HttpRequest):
    return render(request, "terms.html")


def about(request: HttpRequest):
    return render(request, "about.html")


# ==========================================================
#  PAYMENT FLOW (Pesapal + Mpesa)
# ==========================================================
def book_tour(request, tour_id):
    """Redirect authenticated user to the payment page."""
    tour = get_object_or_404(Tour, id=tour_id)
    return redirect("tour_payment", tour_id=tour.id)


def tour_payment(request: HttpRequest, tour_id):
    """Show Pesapal iframe for tour payment."""
    tour = get_object_or_404(Tour, id=tour_id)

    context = {"tour": tour, "pesapal_iframe_url": None, "error": None}

    try:
        service = PesaPalService()
        callback_url = request.build_absolute_uri(reverse("pesapal_callback"))

        pesapal_response = service.initiate_payment(
            amount=str(tour.price_per_person),
            description=f"Payment for Tour {tour.title}",
            callback_url=callback_url,
            email=request.user.email if request.user.is_authenticated else None,
            first_name=request.user.first_name if request.user.is_authenticated else None,
            last_name=request.user.last_name if request.user.is_authenticated else None,
        )

        if pesapal_response and pesapal_response.get("iframe_url"):
            Payment.objects.create(
                user=request.user if request.user.is_authenticated else None,
                tour=tour,
                amount=tour.price_per_person,
                reference=pesapal_response.get("order_tracking_id", ""),
                provider="PESAPAL",
                status="PENDING",
            )
            context["pesapal_iframe_url"] = pesapal_response["iframe_url"]
        else:
            context["error"] = "Payment service is temporarily unavailable."
    except Exception as e:
        logger.error(f"Payment initiation error: {str(e)}")
        context["error"] = "An error occurred while initializing payment."

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
            logger.error("Pesapal callback for non-existent payment: %s", tracking_id)
            return JsonResponse({"success": False, "message": "Payment not found"}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.exception("Error processing Pesapal callback: %s", str(e))
        return JsonResponse({"success": False, "message": "Server error"}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def pesapal_ipn(request):
    """Pesapal IPN endpoint (server-to-server notification)."""
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
def mpesa_payment(request, tour_id):
    """Mpesa STK Push with validation and error handling."""
    try:
        data = json.loads(request.body)
        phone_number = data.get("phone_number")

        if not phone_number:
            return JsonResponse({"success": False, "message": "Phone number is required"}, status=400)
        if not validate_phone_number(phone_number):
            return JsonResponse({"success": False, "message": "Invalid phone number format"}, status=400)

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
                "message": "STK Push sent. Check your phone to complete payment.",
                "response": response,
            })
        else:
            logger.error("Mpesa STK push failed for tour %s: %s", tour_id, response)
            return JsonResponse({"success": False, "message": "Failed to initiate Mpesa payment."}, status=500)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON data"}, status=400)
    except Exception as e:
        logger.exception("Error processing Mpesa payment for tour %s: %s", tour_id, str(e))
        return JsonResponse({"success": False, "message": "Unexpected error"}, status=500)


# ---------------- PAYMENT RESULT PAGES ------------------
def payment_success(request):
    return render(request, "payments/success.html")


def payment_failed(request):
    return render(request, "payments/failed.html")


# ==========================================================
#  DRIVER DASHBOARD + ACTIONS
# ==========================================================
def driver_dashboard(request: HttpRequest):
    driver = getattr(request.user, "driver", None)
    if not driver:
        messages.error(request, "You must be logged in as a driver.")
        return redirect("driver_login")

    if request.method == "POST":
        # Add new trip
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

        # Add new tour
        if "new_tour" in request.POST:
            return add_tour(request)

    context = {
        "driver": driver,
        "tripHistory": Trip.objects.filter(driver=driver).order_by("-date"),
        "tours": Tour.objects.filter(created_by=request.user).order_by("-created_at"),
        "bookings": Booking.objects.filter(driver=driver).select_related("customer", "destination"),
        "payments": Payment.objects.filter(booking__driver=driver).select_related("booking", "booking__customer"),
        "messages": ContactMessage.objects.all(),
    }
    return render(request, "driver_dashboard.html", context)


def add_trip(request: HttpRequest):
    driver = getattr(request.user, "driver", None)
    if request.method == "POST" and driver:
        Trip.objects.create(
            driver=driver,
            destination=request.POST.get("destination"),
            date=request.POST.get("date"),
            earnings=request.POST.get("earnings") or 0,
            status=request.POST.get("status") or "Scheduled",
        )
        messages.success(request, "Trip added.")
    return redirect("driver_dashboard")


def add_tour(request: HttpRequest):
    driver = getattr(request.user, "driver", None)
    if request.method == "POST" and driver:
        # --- parsing & defaults ---
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


def edit_tour(request, tour_id):
    tour = get_object_or_404(Tour, id=tour_id)
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


def delete_tour(request, tour_id):
    tour = get_object_or_404(Tour, id=tour_id)
    tour.delete()
    messages.success(request, "Tour deleted.")
    return redirect("driver_dashboard")


# ==========================================================
#  DRIVER LOGIN
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
#  STAFF / DEBUG UTILITIES
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
#  HELPERS
# ==========================================================
def validate_phone_number(phone_number):
    """Validate phone number format (basic check)."""
    return phone_number and len(phone_number) >= 9 and phone_number.startswith("+")


def verify_pesapal_ip(ip_address):
    """Verify Pesapal IP ranges (customize with real docs)."""
    pesapal_ips = ["52.15.185.146", "52.15.178.181"]  # Example
    return ip_address in pesapal_ips


def send_payment_confirmation_email(payment):
    """Send email confirmation after payment success."""
    # TODO: implement your email logic
    pass
