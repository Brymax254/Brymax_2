from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.conf import settings
from decimal import Decimal
import uuid


# ===============================
# Core Models
# ===============================

class Destination(models.Model):
    """Represents airport destinations, safari parks, excursions, or tour locations."""
    DESTINATION_TYPES = [
        ('TRANSFER', 'Airport Transfer'),
        ('EXCURSION', 'Excursion'),
        ('TOUR', 'Tour / Safari'),
    ]

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True, null=True)
    location = models.CharField(max_length=200, blank=True, null=True)
    price_per_person = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    destination_type = models.CharField(max_length=20, choices=DESTINATION_TYPES, default='TOUR')
    image = models.ImageField(upload_to="destinations/", blank=True, null=True)
    video = models.FileField(upload_to="destinations/videos/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Customer(models.Model):
    """Customer making a booking."""
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Driver(models.Model):
    """Drivers assigned to bookings."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="driver", null=True, blank=True)
    name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20)
    license_number = models.CharField(max_length=50, unique=True)
    available = models.BooleanField(default=True)

    # Rich profile
    profile_picture = models.ImageField(upload_to="drivers/", blank=True, null=True)
    experience_years = models.PositiveIntegerField(default=0)
    vehicle = models.CharField(max_length=150, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Booking(models.Model):
    """Bookings for transfers, excursions, or tours."""
    BOOKING_TYPE_CHOICES = [
        ('TRANSFER', 'Airport Transfer'),
        ('EXCURSION', 'Excursion'),
        ('TOUR', 'Tour / Safari'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="bookings")
    destination = models.ForeignKey(Destination, on_delete=models.SET_NULL, null=True, related_name="bookings")
    booking_type = models.CharField(max_length=20, choices=BOOKING_TYPE_CHOICES)
    num_passengers = models.PositiveIntegerField(default=1)
    pickup_location = models.CharField(max_length=200, blank=True, null=True)
    dropoff_location = models.CharField(max_length=200, blank=True, null=True)
    travel_date = models.DateField()
    special_requests = models.TextField(blank=True, null=True)
    booking_date = models.DateTimeField(default=timezone.now)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_confirmed = models.BooleanField(default=False)
    is_cancelled = models.BooleanField(default=False)
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings")

    class Meta:
        ordering = ['-booking_date']

    def __str__(self):
        return f"{self.customer} - {self.destination} ({self.booking_type})"

    @property
    def calculate_total_price(self):
        """Calculate total price based on destination price and number of passengers."""
        if self.destination:
            return self.num_passengers * self.destination.price_per_person
        return Decimal('0.00')


# ===============================
# Unified Payment Models
# ===============================

class PaymentProvider(models.TextChoices):
    MPESA = "MPESA", "M-PESA"
    PESAPAL = "PESAPAL", "Pesapal"
    PAYPAL = "PAYPAL", "PayPal"
    CARD = "CARD", "Card Payment"
    AIRTEL = "AIRTEL", "Airtel Money"
    CASH = "CASH", "Cash"
    BANK = "BANK", "Bank Transfer"
    OTHER = "OTHER", "Other"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"
    REFUNDED = "REFUNDED", "Refunded"


class Payment(models.Model):
    """Unified payment model that works for both Bookings and Tours."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Who made the payment
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payments"
    )

    # Can link to either Booking or Tour
    booking = models.OneToOneField(
        Booking, on_delete=models.CASCADE, related_name="payment", null=True, blank=True
    )
    tour = models.ForeignKey(
        "Tour", on_delete=models.CASCADE, related_name="payments", null=True, blank=True
    )

    # Payment details
    provider = models.CharField(
        max_length=20, choices=PaymentProvider.choices, default=PaymentProvider.PESAPAL
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=10, default="KES")
    phone_number = models.CharField(
        max_length=20, blank=True, null=True,
        help_text="Phone number used for M-PESA/Airtel transactions"
    )
    status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )

    # Transaction references
    reference = models.CharField(
        max_length=100, blank=True, null=True, db_index=True,
        help_text="Unique reference from provider or generated internally"
    )
    pesapal_reference = models.CharField(
        max_length=255, blank=True, null=True, help_text="Pesapal transaction reference"
    )
    transaction_id = models.CharField(max_length=100, blank=True, null=True)

    # Extra
    description = models.TextField(blank=True, null=True)
    raw_response = models.JSONField(blank=True, null=True)

    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        if self.booking:
            return f"Booking {self.booking.id} - {self.amount} {self.currency} ({self.status})"
        elif self.tour:
            return f"Tour {self.tour.title} - {self.amount} {self.currency} ({self.status})"
        return f"{self.user} - {self.amount} {self.currency} ({self.status})"

    # --- Admin-friendly aliases ---
    @property
    def amount_paid(self):
        return self.amount

    @property
    def method(self):
        return self.provider

    @property
    def paid_on(self):
        return self.created_at

    @property
    def is_successful(self):
        return self.status == PaymentStatus.SUCCESS

    @property
    def is_pending(self):
        return self.status == PaymentStatus.PENDING

    @property
    def is_failed(self):
        return self.status == PaymentStatus.FAILED

# ===============================
# Other Models
# ===============================

class ContactMessage(models.Model):
    """Messages from the contact page."""
    name = models.CharField(max_length=150)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f"Message from {self.name} - {self.subject}"


class Tour(models.Model):
    """Extended model for multi-day safari/tours."""
    title = models.CharField(max_length=200)
    description = models.TextField()
    itinerary = models.TextField(blank=True, null=True)
    price_per_person = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    duration_days = models.PositiveIntegerField(default=1)
    available = models.BooleanField(default=True)

    # Media
    image = models.ImageField(upload_to="tours/", blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    video = models.FileField(upload_to="tours/videos/", blank=True, null=True)

    # Track creator
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_tours")

    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_image_src(self):
        """Return appropriate image src (file URL preferred, then image_url)."""
        if self.image:
            return getattr(self.image, "url", None)
        if self.image_url:
            return self.image_url
        return None


class Video(models.Model):
    """Standalone videos (optional paid content)."""
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="videos/")
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class Trip(models.Model):
    """Represents a trip completed by a driver."""
    STATUS_CHOICES = [
        ('Completed', 'Completed'),
        ('In Progress', 'In Progress'),
        ('Scheduled', 'Scheduled'),
    ]

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='trips')
    destination = models.CharField(max_length=200)
    date = models.DateField()
    earnings = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Scheduled')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.destination} ({self.status}) - {self.driver.name}"
