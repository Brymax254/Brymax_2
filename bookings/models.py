from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.conf import settings
from decimal import Decimal
import uuid
from .utils.pesapal import PesapalAPI


# =====================================================
# DESTINATIONS & CUSTOMERS
# =====================================================

class Destination(models.Model):
    """
    Represents airport destinations, safari parks, excursions, or tour locations.
    """
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

    # Media
    image = models.ImageField(upload_to="destinations/", blank=True, null=True)
    video = models.FileField(upload_to="destinations/videos/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Customer(models.Model):
    """
    Customer making a booking (used for registered customers).
    """
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


# =====================================================
# DRIVERS & BOOKINGS
# =====================================================

class Driver(models.Model):
    """
    Drivers assigned to bookings.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="driver", null=True, blank=True)
    name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20)
    license_number = models.CharField(max_length=50, unique=True)
    available = models.BooleanField(default=True)

    # Extended profile
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
    """
    Bookings for transfers, excursions, or tours.
    """
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

    pesapal_reference = models.CharField(max_length=100, blank=True, null=True, unique=True)

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


# =====================================================
# PAYMENTS
# =====================================================

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
    """
    Unified payment model for both registered users and guest checkouts.
    Captures guest info, travel date, optional billing address, and
    integrates with Pesapal / M-Pesa.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    # --------------------
    # Who is paying
    # --------------------
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payments",
        help_text="Registered user (if logged in)."
    )
    guest_full_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Full name entered by guest during checkout."
    )
    guest_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Email address entered by guest during checkout."
    )
    guest_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Phone number entered by guest during checkout."
    )

    # --------------------
    # Booking context
    # --------------------
    booking = models.OneToOneField(
        "Booking",
        on_delete=models.CASCADE,
        related_name="payment",
        null=True,
        blank=True,
        help_text="Link to a booking if this is a booking payment."
    )
    tour = models.ForeignKey(
        "Tour",
        on_delete=models.CASCADE,
        related_name="payments",
        null=True,
        blank=True,
        help_text="Link to a tour if this is a direct tour payment."
    )

    # --------------------
    # Trip details
    # --------------------
    travel_date = models.DateField(
        null=False,
        blank=False,
        help_text="Date of travel as selected by the guest."
    )

    # --------------------
    # Optional billing address (for card payments)
    # --------------------
    billing_line1 = models.CharField(
        max_length=255,
        blank=False,
        default="Nairobi",
        help_text="Billing street address (line 1)."
    )
    billing_city = models.CharField(
        max_length=100,
        blank=False,
        default="Nairobi",
        help_text="Billing city or town."
    )
    billing_state = models.CharField(
        max_length=100,
        blank=False,
        default="Nairobi",
        help_text="Billing state or region."
    )
    billing_postal_code = models.CharField(
        max_length=20,
        blank=False,
        default="00100",
        help_text="Billing postal / ZIP code."
    )
    billing_country_code = models.CharField(
        max_length=3,
        blank=False,
        default="KE",
        help_text="Billing country code (ISO 3166-1 alpha-3)."
    )

    # --------------------
    # Payment parameters
    # --------------------
    provider = models.CharField(
        max_length=20,
        choices=PaymentProvider.choices,
        default=PaymentProvider.PESAPAL,
        help_text="The payment gateway."
    )
    method = models.CharField(
        max_length=20,
        choices=PaymentProvider.choices,
        default=PaymentProvider.MPESA,
        help_text="The payment method selected by the guest."
    )
    currency = models.CharField(
        max_length=10,
        default="KES",
        help_text="Currency code."
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        help_text="Calculated total amount due."
    )
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        help_text="Amount actually paid (returned by the gateway)."
    )
    phone_number = models.CharField(
        max_length=20,
        blank=False,
        default="",
        help_text="Phone used for mobile payments."
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        help_text="Current status of the payment."
    )

    # --------------------
    # Transaction references
    # --------------------
    reference = models.CharField(
        max_length=100,
        blank=False,
        default="",
        db_index=True,
        help_text="Merchant reference for this transaction."
    )
    pesapal_reference = models.CharField(
        max_length=255,
        blank=False,
        default="",
        help_text="Pesapal OrderTrackingId."
    )
    confirmation_code = models.CharField(
        max_length=100,
        blank=False,
        default="",
        help_text="Confirmation code returned by the gateway."
    )
    transaction_id = models.CharField(
        max_length=100,
        blank=False,
        default="",
        help_text="Transaction ID returned by the gateway."
    )

    # --------------------
    # Optional description & raw response
    # --------------------
    description = models.TextField(
        blank=False,
        default="Payment for Tour",
        help_text="Free-form description or notes."
    )
    raw_response = models.JSONField(
        blank=True,
        null=True,
        help_text="Full JSON response from the payment gateway."
    )

    # --------------------
    # Timestamps
    # --------------------
    paid_on = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Datetime when payment was confirmed."
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Record created at this timestamp."
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Record last updated at this timestamp."
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        if self.booking:
            return f"Booking {self.booking.id} - {self.amount} {self.currency} ({self.status})"
        if self.tour:
            return f"Tour {self.tour.title} - {self.amount} {self.currency} ({self.status})"
        identity = (
            self.user.get_full_name() if self.user and self.user.is_authenticated
            else self.guest_email or "Guest"
        )
        return f"{identity} - {self.amount} {self.currency} ({self.status})"

    # --- Helper methods ---
    def save(self, *args, **kwargs):
        """
        Auto-fill amount_paid and paid_on when payment is successful.
        """
        if self.status == PaymentStatus.SUCCESS:
            if not self.amount_paid:
                self.amount_paid = self.amount
            if not self.paid_on:
                self.paid_on = timezone.now()
        super().save(*args, **kwargs)

    # --- Utility properties ---
    @property
    def is_successful(self):
        return self.status == PaymentStatus.SUCCESS

    @property
    def is_pending(self):
        return self.status == PaymentStatus.PENDING

    @property
    def is_failed(self):
        return self.status == PaymentStatus.FAILED


# =====================================================
# CONTENT & MISC
# =====================================================

class ContactMessage(models.Model):
    """
    Messages from the contact page.
    """
    name = models.CharField(max_length=150)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()

    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f"Message from {self.name} - {self.subject}"

from cloudinary.models import CloudinaryField


class Tour(models.Model):
    """
    Extended model for multi-day safaris/tours.
    """
    title = models.CharField(max_length=200)
    description = models.TextField()
    itinerary = models.TextField(blank=True, null=True)
    price_per_person = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    duration_days = models.PositiveIntegerField(default=1)
    available = models.BooleanField(default=True)

    # Media (Cloudinary)
    image = CloudinaryField("image", blank=True, null=True)
    video = CloudinaryField("video", resource_type="video", blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)  # optional fallback

    # Meta
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_tours")
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_image_src(self):
        """Return Cloudinary image URL if available, else fallback to image_url."""
        if self.image:
            return getattr(self.image, "url", None)
        if self.image_url:
            return self.image_url
        return None

class Video(models.Model):
    """
    Standalone videos (optional paid content).
    """
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
    """
    Represents a trip completed by a driver.
    """
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

