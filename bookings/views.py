# views.py

import json
import uuid
import logging
from decimal import Decimal, InvalidOperation

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
from django.views.decorators.http import (
    require_GET, require_POST, require_http_methods
)
from django.views.generic import DetailView

from .models import (
    Tour, Destination, Video, Booking, Payment,
    ContactMessage, Trip, PaymentStatus
)
from .services import PesaPalService, MpesaSTKPush
from .pesapal_utils import create_pesapal_order
from .forms import GuestCheckoutForm

logger = logging.getLogger(__name__)


# =============================================================================
# UTILITIES & DECORATORS
# =============================================================================

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


def send_payment_confirmation_email(payment: Payment) -> None:
    """Send payment confirmation to guest email."""
    subject = f"Payment Confirmation - {payment.tour.title}"
    message = (
        f"Dear {payment.guest_full_name},\n\n"
        f"We have received your payment of KES {payment.amount_paid} "
        f"for \"{payment.tour.title}\".\n\n"
        "Thank you for booking with Safari Adventures Kenya!"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [payment.guest_email])


def driver_required(view_func):
    """Decorator to ensure user is a logged-in driver."""
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
    """Homepage."""
    return render(request, "home.html")


def book_online(request):
    """Book Online landing page."""
    return render(request, "book_online.html")


def nairobi_transfers(request):
    """Nairobi Transfers information page."""
    return render(request, "nairobi_transfers.html")


def excursions(request):
    """Excursions page."""
    return render(request, "excursions.html")


def tours(request):
    """Public tours listing with trips, videos, and destinations."""
    context = {
        "tours":   Tour.objects.filter(is_approved=True, available=True)
                               .order_by("-created_at"),
        "trips":   Trip.objects.all().order_by("-created_at"),
        "videos":  Video.objects.all().order_by("-created_at"),
        "destinations": Destination.objects.all().order_by("-created_at"),
    }
    return render(request, "tours.html", context)


def contact(request):
    """Contact page."""
    return render(request, "contact.html")


def terms(request):
    """Terms and Conditions page."""
    return render(request, "terms.html")


def about(request):
    """About Us page."""
    return render(request, "about.html")


# =============================================================================
# TOUR PAYMENT (PESAPAL)
# =============================================================================

@require_http_methods(["GET", "POST"])
def tour_payment(request, tour_id):
    """
    Show checkout form on GET; initiate Pesapal order on POST.
    """
    tour = get_object_or_404(Tour, id=tour_id)

    if request.method == "POST":
        form = GuestCheckoutForm(request.POST)
        if form.is_valid():
            full_name  = form.cleaned_data["full_name"]
            email      = form.cleaned_data["email"]
            phone      = normalize_phone_number(form.cleaned_data["phone"])
            adults     = form.cleaned_data.get("adults", 1)
            children   = form.cleaned_data.get("children", 0)
            travel_date = form.cleaned_data.get(
                "travel_date", timezone.now().date()
            )

            total_amount = tour.price_per_person * (adults + children)

            with transaction.atomic():
                payment, created = Payment.objects.get_or_create(
                    tour=tour,
                    guest_email=email,
                    pesapal_reference__isnull=True,
                    defaults={
                        "amount": total_amount,
                        "currency": "KES",
                        "provider": "PESAPAL",
                        "status":   PaymentStatus.PENDING,
                        "guest_full_name": full_name,
                        "guest_phone":      phone,
                        "adults":     adults,
                        "children":   children,
                        "travel_date": travel_date,
                        "description": f"Tour {tour.title} booking",
                    }
                )

                if created:
                    try:
                        redirect_url, order_ref, tracking_id = create_pesapal_order(
                            order_id=str(uuid.uuid4()),
                            amount=total_amount,
                            description=f"Tour {tour.title}",
                            email=email,
                            phone=phone,
                            first_name=full_name.split()[0],
                            last_name=" ".join(full_name.split()[1:]) or "Guest",
                        )
                        payment.transaction_id   = order_ref
                        payment.pesapal_reference = tracking_id
                        payment.save()
                    except Exception:
                        logger.exception("Pesapal initialization failed")
                        messages.error(
                            request,
                            "Payment service unavailable. Please try again later."
                        )
                        redirect_url = None
                else:
                    messages.info(request, "You already have a pending payment.")
                    redirect_url = None

            return render(
                request,
                "payments/tour_payment.html",
                {
                    "tour": tour,
                    "form": form,
                    "pesapal_iframe_url": redirect_url,
                },
            )

    else:
        form = GuestCheckoutForm()

    return render(
        request, "payments/tour_payment.html", {"tour": tour, "form": form}
    )


@require_GET
def pesapal_redirect(request):
    """
    Handle browser redirect from Pesapal.
    Update status and redirect to receipt.
    """
    tracking_id = request.GET.get("OrderTrackingId")
    if not tracking_id:
        return HttpResponse("Missing tracking ID", status=400)

    payment = get_object_or_404(Payment, pesapal_reference=tracking_id)
    return _update_pesapal_status_and_redirect(payment)


@csrf_exempt
@require_GET
def pesapal_health(request):
    """Pesapal IPN health-check (liveness)."""
    return HttpResponse("OK", status=200)


@csrf_exempt
@require_POST
def pesapal_ipn(request):
    """
    Handle Pesapal server-to-server IPN notifications.
    Expects JSON with OrderTrackingId.
    """
    try:
        payload = json.loads(request.body)
        tracking_id = payload.get("OrderTrackingId") or payload.get("order_tracking_id")
        if not tracking_id:
            return HttpResponse("Missing tracking ID", status=400)

        payment = get_object_or_404(Payment, pesapal_reference=tracking_id)
        return _update_pesapal_status_and_redirect(payment)

    except Exception as exc:
        logger.exception("Pesapal IPN error: %s", exc)
        return HttpResponse("Server error", status=500)


def _update_pesapal_status_and_redirect(payment: Payment):
    """
    Shared logic to call Pesapal status API,
    update Payment model, send email, and redirect.
    """
    try:
        access_token = PesaPalService.get_token()
        res = requests.get(
            f"{settings.PESAPAL_BASE_URL}/v3/api/Transactions/GetTransactionStatus",
            params={"orderTrackingId": payment.pesapal_reference},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        res.raise_for_status()
        data = res.json()

        STATUS_MAP = {
            "COMPLETED": PaymentStatus.SUCCESS,
            "FAILED":    PaymentStatus.FAILED,
            "PENDING":   PaymentStatus.PENDING,
            "CANCELLED": PaymentStatus.CANCELLED,
            "REFUNDED":  PaymentStatus.REFUNDED,
        }
        live_status = data.get("status", "").upper()
        new_status  = STATUS_MAP.get(live_status, PaymentStatus.PENDING)

        with transaction.atomic():
            if payment.status != new_status:
                payment.status = new_status
                if new_status == PaymentStatus.SUCCESS:
                    payment.amount_paid = Decimal(data.get("amount", payment.amount))
                    payment.paid_on     = timezone.now()
                    if not payment.confirmation_sent:
                        send_payment_confirmation_email(payment)
                        payment.confirmation_sent = True

                payment.transaction_id = data.get("confirmation_code", payment.transaction_id)
                payment.method         = data.get("payment_method", payment.method)
                payment.updated_at     = timezone.now()
                payment.save()

        return redirect("receipt", pk=payment.id)

    except Exception as exc:
        logger.exception("Error updating Pesapal status: %s", exc)
        return redirect("receipt", pk=payment.id)


# =============================================================================
# MPESA STK PUSH PAYMENT
# =============================================================================

@csrf_exempt
@login_required
@require_POST
def mpesa_payment(request, tour_id):
    """
    Initiate Mpesa STK Push payment for a tour.
    """
    try:
        body = json.loads(request.body)
        phone = normalize_phone_number(body.get("phone_number"))
        if not phone:
            return JsonResponse(
                {"success": False, "message": "Invalid phone number"},
                status=400,
            )

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
            return JsonResponse(
                {"success": False, "message": "STK Push initiation failed"},
                status=500,
            )

        payment, _ = Payment.objects.get_or_create(
            user=request.user,
            tour=tour,
            transaction_id=checkout_id,
            provider="MPESA",
            defaults={
                "amount": tour.price_per_person,
                "currency": "KES",
                "status":   PaymentStatus.PENDING,
                "method":   "MPESA",
                "description": f"Tour {tour.title}",
                "travel_date": timezone.now().date(),
            },
        )

        return JsonResponse(
            {"success": True, "message": "STK Push sent", "checkout_id": checkout_id}
        )

    except Exception as exc:
        logger.exception("Mpesa STK Push error: %s", exc)
        return JsonResponse(
            {"success": False, "message": "Error processing payment"},
            status=500,
        )


# =============================================================================
# PAYMENT RESULT PAGES
# =============================================================================

@require_GET
def payment_success(request):
    """Render payment success page."""
    return render(request, "payments/success.html")


@require_GET
def payment_failed(request):
    """Render payment failed page."""
    return render(request, "payments/failed.html")


# =============================================================================
# GUEST CHECKOUT & SESSION-BASED PESAPAL
# =============================================================================

@require_POST
def guest_checkout(request, tour_id):
    """
    Save provisional Booking & Payment for guest, then redirect to receipt.
    """
    tour = get_object_or_404(Tour, id=tour_id)
    try:
        data       = request.POST
        full_name  = data["full_name"]
        email      = data["email"]
        phone      = normalize_phone_number(data["phone"])
        adults     = int(data.get("adults", 1))
        children   = int(data.get("children", 0))
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

        return redirect("receipt", pk=payment.pk)

    except (KeyError, InvalidOperation) as exc:
        logger.exception("Guest checkout error: %s", exc)
        return HttpResponse(status=400)


@csrf_exempt
@require_POST
def process_guest_info(request):
    """Store guest email & phone in session for AJAX checkout."""
    email = request.POST.get("email")
    phone = request.POST.get("phone")
    if not email or not phone:
        return JsonResponse(
            {"success": False, "message": "Email and phone required."},
            status=400,
        )
    request.session["guest_email"] = email
    request.session["guest_phone"] = phone
    return JsonResponse({"success": True})


@csrf_exempt
@require_POST
def create_guest_pesapal_order(request):
    """Initiate Pesapal order for a guest via AJAX."""
    try:
        payload     = json.loads(request.body)
        amount      = payload["amount"]
        description = payload.get("description", "Tour booking")
        email       = request.session.get("guest_email")
        phone       = normalize_phone_number(request.session.get("guest_phone"))

        if not email or not phone:
            return JsonResponse(
                {"success": False, "message": "Guest info missing."},
                status=400,
            )

        order_id = f"GUEST-{uuid.uuid4().hex[:10]}"
        redirect_url, merchant_ref, tracking_id = create_pesapal_order(
            order_id=order_id,
            amount=amount,
            description=description,
            email=email,
            phone=phone,
            first_name="Guest",
            last_name="User",
        )

        request.session.update({
            "guest_order_tracking_id": tracking_id,
            "guest_order_merchant_ref": merchant_ref,
        })

        return JsonResponse(
            {"success": True, "redirect_url": redirect_url}
        )

    except Exception as exc:
        logger.exception("Guest Pesapal order creation error: %s", exc)
        return JsonResponse(
            {"success": False, "message": str(exc)},
            status=500,
        )


@csrf_exempt
@require_POST
def guest_pesapal_callback(request):
    """
    AJAX endpoint to update guest payment status.
    Expects JSON: {order_tracking_id, status}.
    """
    try:
        payload     = json.loads(request.body)
        tracking_id = payload.get("order_tracking_id")
        status      = payload.get("status", "").upper()

        if tracking_id != request.session.get("guest_order_tracking_id"):
            return JsonResponse(
                {"success": False, "message": "Order not found"},
                status=404,
            )

        request.session["guest_payment_status"] = status
        return JsonResponse({"success": True})

    except Exception as exc:
        logger.exception("Guest Pesapal callback error: %s", exc)
        return JsonResponse(
            {"success": False, "message": "Server error"},
            status=500,
        )


@require_GET
def guest_payment_success(request):
    """
    Render guest payment result based on session status.
    """
    status   = request.session.get("guest_payment_status", "")
    template = (
        "payments/guest_success.html"
        if status == "COMPLETED"
        else "payments/guest_failed.html"
    )
    return render(request, template)


# =============================================================================
# DRIVER DASHBOARD & MANAGEMENT
# =============================================================================

@driver_required
@require_GET
def driver_dashboard(request):
    driver = request.user.driver
    context = {
        "driver":      driver,
        "trip_history": Trip.objects.filter(driver=driver).order_by("-date"),
        "tours":        Tour.objects.filter(created_by=request.user).order_by("-created_at"),
        "bookings":     Booking.objects.filter(driver=driver)
                                         .select_related("customer", "destination"),
        "payments":     Payment.objects.filter(booking__driver=driver)
                                         .select_related("booking", "booking__customer"),
        "messages":     ContactMessage.objects.all() if request.user.is_staff else ContactMessage.objects.none(),
    }
    return render(request, "driver_dashboard.html", context)


@driver_required
@require_POST
def create_trip(request):
    Trip.objects.create(
        driver= request.user.driver,
        destination=request.POST.get("destination"),
        date=request.POST.get("date"),
        earnings=request.POST.get("earnings") or 0,
        status=request.POST.get("status") or "Scheduled",
    )
    messages.success(request, "Trip added successfully.")
    return redirect("driver_dashboard")


@driver_required
@require_POST
def create_tour(request):
    try:
        title = request.POST.get("title", "").strip() or "Untitled Tour"
        price = Decimal(request.POST.get("price_per_person", "0.00"))
        tour  = Tour.objects.create(
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


@driver_required
@require_http_methods(["GET", "POST"])
def edit_tour(request, tour_id):
    tour = get_object_or_404(Tour, id=tour_id)
    if tour.created_by != request.user and not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect("driver_dashboard")

    if request.method == "POST":
        tour.title            = request.POST.get("title", tour.title)
        tour.description      = request.POST.get("description", tour.description)
        tour.itinerary        = request.POST.get("itinerary", tour.itinerary)
        tour.duration_days    = int(request.POST.get("duration_days", tour.duration_days))
        tour.price_per_person = Decimal(request.POST.get("price_per_person", tour.price_per_person))
        if "image" in request.FILES:
            tour.image = request.FILES["image"]
        if "video" in request.FILES:
            tour.video = request.FILES["video"]
        tour.save()
        messages.success(request, f'Tour "{tour.title}" updated.')
        return redirect("driver_dashboard")

    return render(request, "edit_tour.html", {"tour": tour})


@driver_required
@require_POST
def delete_tour(request, tour_id):
    tour = get_object_or_404(Tour, id=tour_id)
    if tour.created_by != request.user and not request.user.is_staff:
        messages.error(request, "Permission denied.")
    else:
        tour.delete()
        messages.success(request, "Tour deleted.")
    return redirect("driver_dashboard")


# =============================================================================
# DRIVER AUTHENTICATION
# =============================================================================

@require_http_methods(["GET", "POST"])
def driver_login(request):
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username"),
            password=request.POST.get("password"),
        )
        if user and hasattr(user, "driver"):
            login(request, user)
            return redirect("driver_dashboard")
        messages.error(request, "Invalid credentials or not a driver.")
    return render(request, "driver_login.html")


# =============================================================================
# STAFF UTILITIES & RECEIPTS
# =============================================================================

@staff_member_required
@require_POST
def register_pesapal_ipn(request):
    """
    One-off endpoint to register IPN URL with Pesapal.
    Consider migrating to a management command after initial run.
    """
    try:
        auth_res = requests.post(
            f"{settings.PESAPAL_BASE_URL}/api/Auth/RequestToken",
            json={
                "consumer_key": settings.PESAPAL_CONSUMER_KEY,
                "consumer_secret": settings.PESAPAL_CONSUMER_SECRET,
            },
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

        return JsonResponse({"success": True, "ipn_id": ipn_id})
    except Exception as exc:
        logger.exception("IPN registration failed: %s", exc)
        return JsonResponse({"success": False, "message": str(exc)}, status=500)


class ReceiptView(DetailView):
    """
    Shows the receipt page for a Payment.
    Staff users see all; guests/users see only their own.
    """
    model = Payment
    template_name = "payments/receipt.html"
    context_object_name = "payment"

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.request.user.is_staff:
            return (
                qs.filter(guest_email=self.request.session.get("guest_email"))
                | qs.filter(user=self.request.user)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        p = self.object
        context.update({
            "days":             p.days or p.tour.duration_days,
            "adults":           p.adults,
            "children":         p.children,
            "amount_paid":      p.amount_paid or p.amount,
            "guest_full_name":  p.guest_full_name or "Guest",
            "guest_email":      p.guest_email or "N/A",
            "guest_phone":      p.guest_phone or "N/A",
            "reference":        p.pesapal_reference or p.transaction_id,
        })
        return context


@staff_member_required
def modern_admin_dashboard(request):
    """
    Custom modern admin dashboard at /brymax-admin/.
    Accessible to staff users only.
    """
    return render(request, "admin/brymax_dashboard.html")

@require_GET
def guest_payment_failed(request):
    """Render guest payment failure page."""
    return render(request, "payments/guest_failed.html")
