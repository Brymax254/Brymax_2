from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpRequest
from urllib.parse import quote
from decimal import Decimal, InvalidOperation
from django.contrib.auth import authenticate, login
from django.contrib import messages
from .models import Tour, Destination, Video, Booking, Payment, ContactMessage, Trip
from django.utils import timezone

WHATSAPP_NUMBER = "254759234580"


# ---------------- FRONTEND PAGES ------------------
def home(request: HttpRequest):
    return render(request, "home.html")


def _wa_redirect_from_form(request: HttpRequest):
    service = request.POST.get("service", "Service")
    date = request.POST.get("date", "")
    time = request.POST.get("time", "")
    from_loc = request.POST.get("from_location", "")
    to_loc = request.POST.get("to_location", "")
    passengers = request.POST.get("passengers", "1")
    name = request.POST.get("name", "")
    note = request.POST.get("note", "")

    msg = (
        f"Hello Mantra Booking Agencies,%0a"
        f"I would like to book: {service}%0a"
        f"Date: {date}%0aTime: {time}%0a"
        f"From: {from_loc}%0aTo: {to_loc}%0a"
        f"Passengers: {passengers}%0a"
        f"Name: {name}%0a"
        f"Notes: {note}"
    )
    wa_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(msg, safe='')}"
    return redirect(wa_url)


def book_online(request: HttpRequest):
    if request.method == "POST":
        return _wa_redirect_from_form(request)
    return render(request, "book_online.html")


def nairobi_transfers(request: HttpRequest):
    if request.method == "POST":
        return _wa_redirect_from_form(request)
    return render(request, "nairobi_transfers.html")


def excursions(request: HttpRequest):
    if request.method == "POST":
        return _wa_redirect_from_form(request)
    return render(request, "excursions.html")


def tours(request: HttpRequest):
    """Public tours page (shows tours + trips + videos + destinations)."""
    tours_qs = Tour.objects.filter(is_approved=True, available=True).order_by("-created_at")
    trips_qs = Trip.objects.all().order_by("-created_at")
    videos_qs = Video.objects.all().order_by("-created_at")
    destinations_qs = Destination.objects.all().order_by("-created_at")

    if request.method == "POST":
        return _wa_redirect_from_form(request)

    return render(request, "tours.html", {
        "tours": tours_qs,
        "trips": trips_qs,
        "videos": videos_qs,
        "destinations": destinations_qs,
    })


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

            # safe parsing
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
                is_approved=True,  # auto-approve driver tours
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

    # ---------- GET DATA ----------
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
    """Dedicated endpoint (optional) for AJAX or external forms."""
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
    """
    Add tour endpoint for drivers.
    Drivers' tours are automatically approved.
    """
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

        # ---- Safe parsing ----
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

        # ---- Create tour (auto-approve for drivers) ----
        tour = Tour.objects.create(
            title=title or "Untitled Tour",
            description=description,
            itinerary=itinerary,
            duration_days=duration_days,
            price_per_person=price_per_person,
            available=True,
            created_by=request.user,   # ✅ track who made it
            is_approved=True,          # ✅ auto-approved for drivers
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
            tour.duration_days = tour.duration_days

        try:
            tour.price_per_person = Decimal(request.POST.get("price_per_person", tour.price_per_person))
        except (InvalidOperation, TypeError):
            tour.price_per_person = tour.price_per_person

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


def book_tour(request, tour_id):
    tour = get_object_or_404(Tour, id=tour_id)

    # Generate unique booking reference
    now = timezone.now()
    ref_number = f"AIRTOURS{tour.id:04d}/{now.year}"  # e.g., AIRTOURS0008/2025

    msg = (
        f"Hello Safari Adventures Team,%0a"
        f"I would like to book this tour:%0a"
        f"Tour: {tour.title}%0a"
        f"Duration: {tour.duration_days} day(s)%0a"
        f"Price per person: USD {tour.price_per_person}%0a"
        f"Booking Ref: {ref_number}%0a"
        f"Please confirm availability. 🚀"
    )

    wa_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(msg, safe='')}"
    return redirect(wa_url)


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


