from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpRequest, JsonResponse, HttpResponse
from django.urls import reverse
from decimal import Decimal, InvalidOperation
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
import json

from .models import Tour, Destination, Video, Booking, Payment, ContactMessage, Trip
from .services import PesaPalService, MpesaSTKPush   # ✅ make sure you have services.py


# ---------------- FRONTEND PAGES ------------------
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

from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
import logging

logger = logging.getLogger(__name__)


# ---------------- MODERNIZED PAYMENT FLOW ------------------


def book_tour(request, tour_id):
    """Redirect authenticated user to the payment page."""
    tour = get_object_or_404(Tour, id=tour_id)
    return redirect("tour_payment", tour_id=tour.id)


# In your views.py
def tour_payment(request: HttpRequest, tour_id):
    """Modernized payment page"""
    tour = get_object_or_404(Tour, id=tour_id)

    context = {
        "tour": tour,
        "pesapal_iframe_url": None,
        "error": None
    }

    try:
        service = PesaPalService()
        callback_url = request.build_absolute_uri(reverse("pesapal_callback"))

        pesapal_response = service.initiate_payment(
            amount=str(tour.price_per_person),
            description=f"Payment for Tour {tour.title}",
            callback_url=callback_url,
            email=request.user.email if request.user.is_authenticated else None,
            first_name=request.user.first_name if request.user.is_authenticated else None,
            last_name=request.user.last_name if request.user.is_authenticated else None
        )

        if pesapal_response and pesapal_response.get("iframe_url"):
            # Save pending Pesapal payment
            Payment.objects.create(
                user=request.user if request.user.is_authenticated else None,
                tour=tour,
                amount=tour.price_per_person,
                reference=pesapal_response.get("order_tracking_id", ""),
                provider="PESAPAL",
                status="PENDING"
            )
            context["pesapal_iframe_url"] = pesapal_response.get("iframe_url")
        else:
            context["error"] = "Payment service is temporarily unavailable."

    except Exception as e:
        context["error"] = "An error occurred while initializing payment."
        # Log the error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Payment initiation error: {str(e)}")

    return render(request, "payments/tour_payment.html", context)

def pesapal_callback(request):
    # Called after payment completion
    return HttpResponse("Payment completed. Thank you!")

def pesapal_ipn(request):
    # Pesapal posts status updates here
    return HttpResponse("IPN received")

@require_http_methods(["POST"])
@csrf_protect
def mpesa_payment(request, tour_id):
    """Modernized Mpesa STK Push with better validation and error handling"""
    try:
        data = json.loads(request.body)
        phone_number = data.get("phone_number")

        if not phone_number:
            return JsonResponse(
                {"success": False, "message": "Phone number is required"},
                status=400
            )

        # Validate phone number format
        if not validate_phone_number(phone_number):
            return JsonResponse(
                {"success": False, "message": "Invalid phone number format"},
                status=400
            )

        tour = get_object_or_404(Tour, id=tour_id)

        mpesa = MpesaSTKPush()
        response = mpesa.stk_push(
            phone_number=phone_number,
            amount=tour.price_per_person,
            account_reference=f"Tour-{tour.id}",
            transaction_desc=f"Payment for Tour {tour.title}"
        )

        if response and response.get("CheckoutRequestID"):
            Payment.objects.create(
                user=request.user,
                tour=tour,
                amount=tour.price_per_person,
                reference=response.get("CheckoutRequestID", ""),
                provider="MPESA",
                status="PENDING"
            )

            return JsonResponse({
                "success": True,
                "message": "STK Push sent. Check your phone to complete payment.",
                "response": response
            })
        else:
            logger.error("Mpesa STK push failed for tour %s: %s", tour_id, response)
            return JsonResponse({
                "success": False,
                "message": "Failed to initiate Mpesa payment. Please try again."
            }, status=500)

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON data"}, status=400)
    except Exception as e:
        logger.exception("Error processing Mpesa payment for tour %s: %s", tour_id, str(e))
        return JsonResponse({
            "success": False,
            "message": "An unexpected error occurred. Please try again later."
        }, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def pesapal_callback(request):
    """Modernized Pesapal callback with better validation"""
    try:
        # Verify the request is from Pesapal (implement based on Pesapal docs)
        if not verify_pesapal_ip(request.META.get('REMOTE_ADDR')):
            logger.warning("Pesapal callback from unauthorized IP: %s", request.META.get('REMOTE_ADDR'))
            return JsonResponse({"success": False, "message": "Unauthorized"}, status=403)

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

            # Additional actions based on payment status
            if status.upper() == "COMPLETED":
                # Send confirmation email, update booking status, etc.
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


# Helper functions (add to your utils.py)
def validate_phone_number(phone_number):
    """Validate phone number format (customize for your region)"""
    # Simple validation - extend based on your requirements
    return phone_number and len(phone_number) >= 9 and phone_number.startswith('+')


def verify_pesapal_ip(ip_address):
    """Verify that the callback is from Pesapal's servers"""
    # Implement based on Pesapal's documented IP ranges
    pesapal_ips = ["52.15.185.146", "52.15.178.181"]  # Example IPs - check Pesapal docs
    return ip_address in pesapal_ips


def send_payment_confirmation_email(payment):
    """Send payment confirmation email"""
    # Implement your email sending logic here
    pass


# ---------------- DRIVER DASHBOARD ------------------
def driver_dashboard(request: HttpRequest):
    driver = getattr(request.user, "driver", None)
    if not driver:
        messages.error(request, "You must be logged in as a driver to access this page.")
        return redirect("driver_login")

    if request.method == "POST":
        # ---------- Add New Trip ----------
        if "new_trip" in request.POST:
            Trip.objects.create(
                driver=driver,
                destination=request.POST.get("destination"),
                date=request.POST.get("date"),
                earnings=request.POST.get("earnings") or 0,
                status=request.POST.get("status") or "Scheduled"
            )
            messages.success(request, "Trip added successfully.")
            return redirect("driver_dashboard")

        # ---------- Add New Tour ----------
        if "new_tour" in request.POST:
            title = request.POST.get("title", "").strip() or "Untitled Tour"
            description = request.POST.get("description", "").strip()
            itinerary = request.POST.get("itinerary", "").strip()
            duration_raw = request.POST.get("duration_days", "1")
            price_raw = request.POST.get("price_per_person", "0")
            image_file = request.FILES.get("image") or request.FILES.get("image_file")
            video_file = request.FILES.get("video")
            image_url = request.POST.get("image_url", "").strip()

            try:
                duration_days = int(duration_raw)
                if duration_days <= 0:
                    duration_days = 1
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

            if image_file:
                tour.image = image_file
            elif image_url and hasattr(tour, "image_url"):
                tour.image_url = image_url

            if video_file:
                tour.video = video_file

            tour.save()
            messages.success(request, f'Tour "{tour.title}" added successfully.')
            return redirect("driver_dashboard")

    trip_qs = Trip.objects.filter(driver=driver).order_by("-date")
    tours_qs = Tour.objects.filter(created_by=request.user).order_by("-created_at")
    bookings_qs = Booking.objects.filter(driver=driver).select_related("customer", "destination")
    payments_qs = Payment.objects.filter(booking__driver=driver).select_related("booking", "booking__customer")
    contact_messages = ContactMessage.objects.all()

    context = {
        "driver": driver,
        "tripHistory": trip_qs,
        "total_trips": trip_qs.count(),
        "tours": tours_qs,
        "bookings": bookings_qs,
        "payments": payments_qs,
        "messages": contact_messages,
    }
    return render(request, "driver_dashboard.html", context)


# ---------------- DRIVER ACTIONS ------------------
def add_trip(request: HttpRequest):
    driver = getattr(request.user, "driver", None)
    if request.method == "POST" and driver:
        Trip.objects.create(
            driver=driver,
            destination=request.POST.get("destination"),
            date=request.POST.get("date"),
            earnings=request.POST.get("earnings") or 0,
            status=request.POST.get("status") or "Scheduled"
        )
        messages.success(request, "Trip added.")
    return redirect("driver_dashboard")


def add_tour(request: HttpRequest):
    driver = getattr(request.user, "driver", None)
    if request.method == "POST" and driver:
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        itinerary = request.POST.get("itinerary", "").strip()
        duration_raw = request.POST.get("duration_days", "1")
        price_raw = request.POST.get("price_per_person", "0")
        image_file = request.FILES.get("image_file") or request.FILES.get("image")
        video_file = request.FILES.get("video")
        image_url = request.POST.get("image_url", "").strip()

        try:
            duration_days = int(duration_raw)
            if duration_days <= 0:
                duration_days = 1
        except (ValueError, TypeError):
            duration_days = 1

        try:
            price_per_person = Decimal(price_raw)
        except (InvalidOperation, TypeError):
            price_per_person = Decimal("0.00")

        tour = Tour.objects.create(
            title=title or "Untitled Tour",
            description=description,
            itinerary=itinerary,
            duration_days=duration_days,
            price_per_person=price_per_person,
            available=True,
            created_by=request.user,
            is_approved=True,
        )

        if image_file:
            tour.image = image_file
        elif image_url and hasattr(tour, "image_url"):
            try:
                tour.image_url = image_url
            except Exception:
                pass

        if video_file:
            tour.video = video_file

        tour.save()
        messages.success(request, f'Tour "{tour.title}" added and published immediately ✅')

    return redirect("driver_dashboard")


# ---------------- OTHER PAGES ------------------
def contact(request: HttpRequest):
    return render(request, "contact.html")


def terms(request: HttpRequest):
    return render(request, "terms.html")


def about(request: HttpRequest):
    return render(request, 'about.html')


# ---------------- TOUR MANAGEMENT ------------------
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


# ---------------- DRIVER LOGIN ------------------
def driver_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)

        if user:
            if hasattr(user, "driver"):
                login(request, user)
                return redirect("driver_dashboard")
            else:
                messages.error(request, "This account is not linked to a driver.")
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "driver_login.html")
