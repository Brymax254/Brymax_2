from cloudinary.models import CloudinaryField
import uuid
import logging
import hmac
import hashlib
import re
import json
from decimal import Decimal
from datetime import date, datetime, time, timedelta
from typing import Optional, List, Dict, Any, Tuple, Union
from django.contrib.postgres.fields import ArrayField
from django.conf import settings
from django.core.mail import send_mail
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
import requests
from django.template.loader import render_to_string

# Logger
logger = logging.getLogger(__name__)


# =============================================================================
# IMAGE VALIDATION
# =============================================================================

def validate_image_file_extension(value):
    """
    Validate that the uploaded file has a valid image extension.
    """
    import os
    from django.core.exceptions import ValidationError

    ext = os.path.splitext(value.name)[1]
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    if not ext.lower() in valid_extensions:
        raise ValidationError('Unsupported file extension. Allowed extensions are: %s.' % ', '.join(valid_extensions))


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def normalize_phone_number(phone_number: str) -> str:
    """Normalize a phone number to E.164 format."""
    if not phone_number:
        return ""

    # Remove all non-digit characters
    cleaned = re.sub(r'[^\d]', '', phone_number)

    # Handle Kenyan numbers
    if cleaned.startswith('0') and len(cleaned) == 10:
        return '+254' + cleaned[1:]
    elif cleaned.startswith('7') and len(cleaned) == 9:
        return '+254' + cleaned
    elif cleaned.startswith('254') and len(cleaned) == 12:
        return '+' + cleaned
    elif cleaned.startswith('+254') and len(cleaned) == 13:
        return cleaned

    # For other countries
    if len(cleaned) >= 10 and not cleaned.startswith('+'):
        return '+' + cleaned

    return phone_number


def validate_phone_number(value: str) -> None:
    """Validate that a phone number is in a valid format."""
    normalized = normalize_phone_number(value)
    if not re.match(r'^\+\d{6,15}$', normalized):
        raise ValidationError(
            'Please enter a valid phone number in international format (e.g., +254712345678)'
        )


def validate_future_date(value: date) -> None:
    """Validate that a date is not in the past."""
    if value < date.today():
        raise ValidationError("Date cannot be in the past.")


def validate_rating(value: int) -> None:
    """Validate that a rating is between 1 and 5."""
    if not (1 <= value <= 5):
        raise ValidationError("Rating must be between 1 and 5.")


# =============================================================================
# BASE ABSTRACT MODELS
# =============================================================================

class TimeStampedModel(models.Model):
    """Abstract base model with created_at and updated_at fields."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']


class LocationModel(models.Model):
    """Abstract model with location fields."""
    location = models.CharField(max_length=200, blank=True, help_text="Physical location")
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal('-90')), MaxValueValidator(Decimal('90'))],
        help_text="GPS latitude coordinate"
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal('-180')), MaxValueValidator(Decimal('180'))],
        help_text="GPS longitude coordinate"
    )

    class Meta:
        abstract = True

    @property
    def has_coordinates(self):
        """Check if coordinates are set."""
        return self.latitude is not None and self.longitude is not None


# =============================================================================
# CUSTOM MANAGERS
# =============================================================================

class ActiveManager(models.Manager):
    """Manager for models with an is_active field."""

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class FeaturedManager(models.Manager):
    """Manager for featured items."""

    def get_queryset(self):
        return super().get_queryset().filter(is_featured=True)


class BookingManager(models.Manager):
    """Custom manager for Booking model."""

    def pending(self):
        return self.filter(status='PENDING')

    def confirmed(self):
        return self.filter(status='CONFIRMED')

    def upcoming(self):
        today = timezone.now().date()
        return self.filter(travel_date__gte=today)

    def past(self):
        today = timezone.now().date()
        return self.filter(travel_date__lt=today)

    def cancelled(self):
        return self.filter(status='CANCELLED')

    def completed(self):
        return self.filter(status='COMPLETED')


class TourManager(models.Manager):
    """Custom manager for Tour model."""

    def available(self):
        return self.filter(available=True, is_approved=True)

    def featured(self):
        return self.filter(featured=True, available=True, is_approved=True)

    def popular(self):
        return self.filter(is_popular=True, available=True, is_approved=True)

    def by_category(self, category):
        return self.filter(category=category, available=True, is_approved=True)


class PaymentManager(models.Manager):
    """Custom manager for Payment model."""

    def successful(self):
        return self.filter(status=PaymentStatus.SUCCESS)

    def pending(self):
        return self.filter(status=PaymentStatus.PENDING)

    def failed(self):
        return self.filter(status=PaymentStatus.FAILED)

    def refunded(self):
        return self.filter(status__in=[PaymentStatus.REFUNDED, PaymentStatus.PARTIAL_REFUND])


# =============================================================================
# CUSTOMER MODELS
# =============================================================================

class BookingCustomer(TimeStampedModel):
    """Model to store customer information for individual bookings without user accounts."""
    full_name = models.CharField(max_length=200)
    email = models.EmailField()
    phone_number = models.CharField(max_length=20)
    country_code = models.CharField(max_length=5, default='+254')
    normalized_phone = models.CharField(max_length=20, blank=True)
    adults = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField(default=0)
    travel_date = models.DateField()
    days = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Booking Customer"
        verbose_name_plural = "Booking Customers"
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['normalized_phone']),
        ]

    def save(self, *args, **kwargs):
        """Override save to normalize phone number."""
        if self.phone_number and not self.normalized_phone:
            self.normalized_phone = normalize_phone_number(self.country_code + self.phone_number)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name


# =============================================================================
# DRIVER AND VEHICLE MODELS
# =============================================================================

class Driver(TimeStampedModel):
    """Model for drivers who log in and update their profiles."""
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
        ('P', 'Prefer not to say'),
    ]

    LICENSE_TYPES = [
        ('PROFESSIONAL', 'Professional'),
        ('COMMERCIAL', 'Commercial'),
    ]

    # User authentication
    user = models.OneToOneField(
        'auth.User', on_delete=models.CASCADE, related_name="driver_profile"
    )

    # Profile fields (from original UserProfile)
    phone_number = models.CharField(
        max_length=20, validators=[validate_phone_number],
        help_text="Phone number"
    )
    normalized_phone = models.CharField(
        max_length=20, blank=True, help_text="E.164 formatted phone number"
    )
    gender = models.CharField(
        max_length=1, choices=GENDER_CHOICES, blank=True, null=True
    )
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=100, blank=True, null=True)
    profile_picture = CloudinaryField(
        "image", blank=True, null=True, help_text="Profile picture"
    )
    bio = models.TextField(blank=True, null=True)
    preferred_language = models.CharField(
        max_length=10, default="en", help_text="ISO language code"
    )
    communication_preferences = models.JSONField(
        default=dict, blank=True,
        help_text="Communication preferences (email, SMS, WhatsApp, etc.)"
    )
    is_verified = models.BooleanField(default=False)
    verification_document = CloudinaryField(
        "raw", blank=True, null=True,
        help_text="Document for identity verification"
    )

    # Driver-specific fields
    license_number = models.CharField(max_length=50, unique=True)
    license_type = models.CharField(
        max_length=20, choices=LICENSE_TYPES, default='COMMERCIAL'
    )
    license_expiry = models.DateField(null=True, blank=True)
    available = models.BooleanField(default=True)
    experience_years = models.PositiveIntegerField(default=0)

    # Rating and stats
    rating = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal('0.0'),
        validators=[MinValueValidator(Decimal('0.0')), MaxValueValidator(Decimal('5.0'))]
    )
    total_trips = models.PositiveIntegerField(default=0)
    total_earnings = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00')
    )

    # Vehicle
    vehicle = models.ForeignKey(
        'Vehicle', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="drivers"
    )

    # Documents
    driver_license_copy = CloudinaryField(
        "raw", blank=True, null=True, help_text="Copy of driver's license"
    )
    police_clearance = CloudinaryField(
        "raw", blank=True, null=True, help_text="Police clearance certificate"
    )

    # Bank details
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    bank_account = models.CharField(max_length=50, blank=True, null=True)
    bank_branch = models.CharField(max_length=100, blank=True, null=True)

    # Payment preferences
    payment_methods = models.JSONField(
        default=dict, blank=True,
        help_text="Preferred payment methods (M-Pesa, bank transfer, etc.)"
    )

    # Managers
    objects = models.Manager()
    active = ActiveManager()
    available_drivers = models.Manager()

    class Meta:
        verbose_name = "Driver"
        verbose_name_plural = "Drivers"
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['license_number']),
            models.Index(fields=['normalized_phone']),
            models.Index(fields=['rating']),
            models.Index(fields=['available']),
        ]

    def __str__(self):
        return self.full_name

    def save(self, *args, **kwargs):
        """Override save to normalize phone number."""
        if self.phone_number and not self.normalized_phone:
            self.normalized_phone = normalize_phone_number(self.phone_number)
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        """Return the user's full name."""
        if self.user.get_full_name():
            return self.user.get_full_name()
        return self.user.username

    @property
    def person_age(self):
        """Calculate age from date of birth."""
        if self.date_of_birth:
            today = timezone.now().date()
            return today.year - self.date_of_birth.year - (
                    (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        return None

    @property
    def is_adult(self):
        """Check if user is an adult (18+)."""
        age = self.age
        return age is not None and age >= 18

    @property
    def license_status(self):
        """Check if license is valid."""
        if self.license_expiry:
            return self.license_expiry > timezone.now().date()
        return True

    @property
    def license_status_text(self):
        """Get human-readable license status."""
        if self.license_expiry:
            days_until_expiry = (self.license_expiry - date.today()).days
            if days_until_expiry < 0:
                return "Expired"
            elif days_until_expiry < 30:
                return f"Expiring in {days_until_expiry} days"
            else:
                return "Valid"
        return "Unknown"

    def update_trip_stats(self, amount: Decimal) -> None:
        """Update driver trip statistics."""
        self.total_trips += 1
        self.total_earnings += amount
        self.save(update_fields=['total_trips', 'total_earnings'])

    def update_rating(self, new_rating: int) -> None:
        """Update driver's average rating."""
        if not (1 <= new_rating <= 5):
            raise ValueError("Rating must be between 1 and 5")

        reviews = self.reviews.all()
        if not reviews:
            self.rating = Decimal(str(new_rating))
        else:
            total_rating = sum(review.rating for review in reviews) + new_rating
            self.rating = Decimal(str(total_rating / (len(reviews) + 1)))

        self.save(update_fields=['rating'])

    def get_upcoming_trips(self):
        """Get upcoming trips for this driver."""
        today = timezone.now().date()
        return self.trips.filter(date__gte=today, status='SCHEDULED')
from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from cloudinary.models import CloudinaryField
from django.core.validators import validate_image_file_extension

# =============================================================================
# Exchange Rate Model
# =============================================================================
class ExchangeRate(models.Model):
    """
    Stores the current USD to KES exchange rate.
    Only the latest rate is used in Vehicle calculations.
    """
    usd_to_kes = models.DecimalField(max_digits=12, decimal_places=4, help_text="Current USD to KES rate")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Exchange Rate"
        verbose_name_plural = "Exchange Rates"

    def __str__(self):
        return f"1 USD = {self.usd_to_kes} KES (updated {self.updated_at})"

    @staticmethod
    def get_current_rate():
        """Return the latest exchange rate, fallback to 128.95 KES."""
        rate = ExchangeRate.objects.order_by('-updated_at').first()
        return rate.usd_to_kes if rate else Decimal('128.95')

# =============================================================================
# Vehicle Model
# =============================================================================
class Vehicle(models.Model):
    """
    Represents a vehicle used for bookings and transfers.
    Includes pricing in KES with admin-controlled USD conversion,
    images, documents, accessibility features, and sustainability metrics.
    """

    VEHICLE_TYPES = [
        ('SEDAN', 'Sedan'),
        ('SUV', 'SUV'),
        ('VAN', 'Van'),
        ('MINIBUS', 'Minibus'),
        ('BUS', 'Bus'),
        ('LUXURY', 'Luxury Vehicle'),
        ('ELECTRIC', 'Electric Vehicle'),
        ('HYBRID', 'Hybrid Vehicle'),
    ]

    FUEL_TYPES = [
        ('PETROL', 'Petrol'),
        ('DIESEL', 'Diesel'),
        ('ELECTRIC', 'Electric'),
        ('HYBRID', 'Hybrid'),
        ('CNG', 'Compressed Natural Gas'),
    ]

    # -------------------------
    # Basic Information
    # -------------------------
    make = models.CharField(max_length=50, help_text="Vehicle make (e.g., Toyota)")
    model = models.CharField(max_length=50, help_text="Vehicle model (e.g., Noah)")
    year = models.PositiveIntegerField(help_text="Year of manufacture")
    color = models.CharField(max_length=30, blank=True, null=True)
    license_plate = models.CharField(max_length=20, unique=True)
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_TYPES)
    fuel_type = models.CharField(max_length=20, choices=FUEL_TYPES)
    capacity = models.PositiveIntegerField(help_text="Passenger capacity")

    # -------------------------
    # Pricing
    # -------------------------
    price_ksh = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Base price in Ksh (converted from USD using admin-set rate)"
    )

    # -------------------------
    # Images
    # -------------------------
    image = models.ImageField(
        upload_to='vehicles/%Y/%m/',
        blank=True, null=True,
        validators=[validate_image_file_extension],
        help_text="Upload main vehicle image (max 100MB)"
    )
    external_image_url = models.URLField(
        max_length=255, blank=True, null=True,
        help_text="External URL for vehicle image (alternative to upload)"
    )

    # -------------------------
    # Features
    # -------------------------
    features = models.JSONField(default=list, blank=True, null=True, help_text="Vehicle features (AC, WiFi, Bluetooth, etc.)")
    accessibility_features = models.JSONField(default=list, blank=True, null=True, help_text="Accessibility features (wheelchair access, ramp, etc.)")

    # -------------------------
    # Documents
    # -------------------------
    logbook_copy = CloudinaryField("logbook_copy", blank=True, null=True, help_text="Scanned logbook copy")
    insurance_copy = CloudinaryField("insurance_copy", blank=True, null=True, help_text="Insurance certificate")
    inspection_certificate = CloudinaryField("inspection_certificate", blank=True, null=True, help_text="Inspection certificate")

    # -------------------------
    # Dates & Status
    # -------------------------
    insurance_expiry = models.DateField(null=True, blank=True)
    inspection_expiry = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    # -------------------------
    # Sustainability
    # -------------------------
    carbon_footprint_per_km = models.DecimalField(
        max_digits=6, decimal_places=3, default=Decimal('0.120'),
        help_text="CO₂ emissions per km (kg)"
    )

    class Meta:
        verbose_name = "Vehicle"
        verbose_name_plural = "Vehicles"
        ordering = ['id']
        indexes = [
            models.Index(fields=['license_plate']),
            models.Index(fields=['vehicle_type']),
            models.Index(fields=['is_active']),
            models.Index(fields=['fuel_type']),
        ]

    # -------------------------
    # String Representation
    # -------------------------
    def __str__(self):
        return f"{self.year} {self.make} {self.model} ({self.license_plate})"

    # -------------------------
    # Validation
    # -------------------------
    def clean(self):
        if self.year < 1980:
            raise ValidationError({"year": "Vehicle year is unrealistically old."})
        if self.year > timezone.now().year:
            raise ValidationError({"year": "Year of manufacture cannot be in the future."})

        if self.image and self.image.size > 100 * 1024 * 1024:
            raise ValidationError({"image": "Image file size cannot exceed 100MB."})

        if self.is_active and not self.image and not self.external_image_url:
            raise ValidationError("Active vehicles must have either an uploaded image or an external image URL.")

        if self.insurance_expiry and self.insurance_expiry <= timezone.now().date():
            raise ValidationError({"insurance_expiry": "Insurance expiry must be in the future."})

        if self.inspection_expiry and self.inspection_expiry <= timezone.now().date():
            raise ValidationError({"inspection_expiry": "Inspection expiry must be in the future."})

    # -------------------------
    # Properties
    # -------------------------
    @property
    def image_url(self):
        return self.image.url if self.image else self.external_image_url

    @property
    def full_name(self):
        return f"{self.year} {self.make} {self.model}"

    @property
    def vehicle_age(self):
        return timezone.now().year - self.year if self.year else None

    @property
    def documents_valid(self):
        return self.insurance_status and self.inspection_status

    @property
    def insurance_status(self):
        return not self.insurance_expiry or self.insurance_expiry > timezone.now().date()

    @property
    def inspection_status(self):
        return not self.inspection_expiry or self.inspection_expiry > timezone.now().date()

    def get_carbon_footprint(self, distance_km):
        return self.carbon_footprint_per_km * distance_km

    # -------------------------
    # USD Price
    # -------------------------
    @property
    def price_usd(self):
        rate = ExchangeRate.get_current_rate()
        if self.price_ksh:
            return round(Decimal(self.price_ksh) / Decimal(rate), 2)
        return None

    # -------------------------
    # Save Override
    # -------------------------
    def save(self, *args, **kwargs):
        self.features = self.features if isinstance(self.features, list) else []
        self.accessibility_features = self.accessibility_features if isinstance(self.accessibility_features, list) else []
        super().save(*args, **kwargs)


# =============================================================================
# DESTINATIONS & TOURS MODELS
# =============================================================================

class Destination(TimeStampedModel, LocationModel):
    """Model for travel destinations."""
    DESTINATION_TYPES = [
        ('TRANSFER', 'Airport Transfer'),
        ('EXCURSION', 'Excursion'),
        ('TOUR', 'Tour / Safari'),
        ('ATTRACTION', 'Attraction'),
        ('ACCOMMODATION', 'Accommodation'),
    ]

    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    description = models.TextField(blank=True)
    destination_type = models.CharField(
        max_length=20, choices=DESTINATION_TYPES, default='TOUR'
    )

    # Pricing
    price_per_person = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    currency = models.CharField(max_length=10, default="KES")

    # Status
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    # Media
    image = models.ImageField(
        upload_to='uploads/images/%Y/%m/',
        blank=True,
        null=True,
        help_text="Main image (stored locally)"
    )

    video = models.FileField(
        upload_to='uploads/videos/%Y/%m/',
        blank=True,
        null=True,
        help_text="Upload video file (stored locally, up to 500MB)"
    )

    image_url = models.URLField(
        blank=True,
        null=True,
        help_text="Optional external image URL"
    )

    gallery_images = models.JSONField(
        default=list,
        blank=True,
        help_text="List of additional image file paths or URLs"
    )

    # Sustainability
    eco_friendly = models.BooleanField(default=False)
    carbon_footprint_per_visit = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text="Estimated carbon footprint per visit in kg CO2"
    )
    sustainability_certifications = models.JSONField(
        default=list, blank=True,
        help_text="List of sustainability certifications"
    )

    # Accessibility
    wheelchair_accessible = models.BooleanField(default=False)
    accessibility_features = models.JSONField(
        default=dict, blank=True,
        help_text="Detailed accessibility features"
    )

    # Health & Safety
    health_safety_measures = models.JSONField(
        default=dict, blank=True,
        help_text="Health and safety measures implemented"
    )
    covid19_protocols = models.JSONField(
        default=dict, blank=True,
        help_text="COVID-19 specific protocols"
    )

    # Managers
    objects = models.Manager()
    active = ActiveManager()
    featured = FeaturedManager()

    class Meta:
        verbose_name = "Destination"
        verbose_name_plural = "Destinations"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Override save to auto-generate slug."""
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Destination.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        """Get the absolute URL for this destination."""
        return reverse('destination_detail', kwargs={'slug': self.slug})

    @property
    def primary_image(self):
        """Return the primary image URL."""
        if self.image:
            return self.image.url
        return self.image_url or "/static/img/destination-placeholder.jpg"




class TourCategory(TimeStampedModel):
    """Model for tour categories."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    image = models.ImageField(
        upload_to='uploads/tour_categories/%Y/%m/',
        blank=True,
        null=True,
        help_text="Upload category image (stored locally, max 100MB)"
    )

    # Managers
    objects = models.Manager()
    active = ActiveManager()

    class Meta:
        verbose_name = "Tour Category"
        verbose_name_plural = "Tour Categories"
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        """Validate uploaded image size."""
        super().clean()
        if self.image and self.image.size > 100 * 1024 * 1024:  # 100MB limit
            raise ValidationError({"image": "Image size cannot exceed 100MB."})

    def save(self, *args, **kwargs):
        """Auto-generate unique slug if missing."""
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while TourCategory.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        """Return the absolute URL for this category."""
        return reverse('category_detail', kwargs={'slug': self.slug})

class Tour(TimeStampedModel):
    """Model for multi-day safaris/tours."""
    DIFFICULTY_CHOICES = [
        ('EASY', 'Easy'),
        ('MODERATE', 'Moderate'),
        ('CHALLENGING', 'Challenging'),
        ('EXTREME', 'Extreme'),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    tagline = models.CharField(max_length=300, blank=True, null=True)
    description = models.TextField(default="No description available")

    # Itinerary details
    highlights = models.TextField(blank=True, null=True)
    itinerary = models.JSONField(default=list, blank=True)
    inclusions = models.JSONField(default=list, blank=True)
    exclusions = models.JSONField(default=list, blank=True)

    # Pricing
    price_per_person = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    discount_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    currency = models.CharField(max_length=10, default="KES")

    # Duration
    duration_days = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)]
    )
    duration_nights = models.PositiveIntegerField(default=0)

    # Group size
    max_group_size = models.PositiveIntegerField(
        default=10, validators=[MinValueValidator(1)]
    )
    min_group_size = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)]
    )

    # Other details
    difficulty = models.CharField(
        max_length=20, choices=DIFFICULTY_CHOICES, default='EASY'
    )
    category = models.ForeignKey(
        'TourCategory', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tours'
    )
    available = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    is_popular = models.BooleanField(default=False)
    max_advance_booking_days = models.PositiveIntegerField(
        default=365, validators=[MinValueValidator(1)]
    )

    # Media
    image = models.ImageField(
        upload_to='uploads/media/images/%Y/%m/',
        blank=True,
        null=True,
        help_text="Main image (stored locally, max 500MB)"
    )

    video = models.FileField(
        upload_to='uploads/media/videos/%Y/%m/',
        blank=True,
        null=True,
        help_text="Upload video file (stored locally, max 500MB)"
    )

    image_url = models.URLField(
        blank=True,
        null=True,
        help_text="Optional external image URL"
    )

    gallery_images = models.JSONField(
        default=list,
        blank=True,
        help_text="List of additional local image paths or URLs"
    )

    # Location
    departure_point = models.CharField(max_length=200, default="Nairobi")
    destinations_visited = models.TextField(blank=True, null=True)
    destinations = models.ManyToManyField(
        'Destination', blank=True, related_name='tours'
    )

    # Sustainability
    eco_friendly = models.BooleanField(default=False)
    carbon_footprint_per_person = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text="Estimated carbon footprint per person in kg CO2"
    )
    sustainability_certifications = models.JSONField(
        default=list, blank=True,
        help_text="List of sustainability certifications"
    )

    # Accessibility
    wheelchair_accessible = models.BooleanField(default=False)
    accessibility_features = models.JSONField(
        default=dict, blank=True,
        help_text="Detailed accessibility features"
    )

    # Health & Safety
    health_safety_measures = models.JSONField(
        default=dict, blank=True,
        help_text="Health and safety measures implemented"
    )
    covid19_protocols = models.JSONField(
        default=dict, blank=True,
        help_text="COVID-19 specific protocols"
    )

    # Relations
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_tours"
    )
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_tours"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Managers
    objects = TourManager()

    class Meta:
        verbose_name = "Tour"
        verbose_name_plural = "Tours"
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['difficulty']),
            models.Index(fields=['is_popular']),
            models.Index(fields=['featured']),
            models.Index(fields=['is_approved']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        """Override save to auto-generate slug and set duration nights."""
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Tour.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        if self.duration_days > 0 and not self.duration_nights:
            self.duration_nights = self.duration_days - 1

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        # Only generate URL if slug exists
        if self.slug:
            return reverse("bookings:tour_detail", kwargs={"tour_slug": self.slug})
        # Return a fallback URL if slug is empty
        return reverse("admin:bookings_tour_change", args=[self.pk]) if self.pk else "#"

    def get_image_src(self):
        """Return Cloudinary image URL if available, else fallback to image_url."""
        if self.image:
            return getattr(self.image, "url", None)
        if self.image_url:
            return self.image_url
        return "/static/img/tour-placeholder.jpg"

    @property
    def is_available(self):
        """Check if tour is available and approved."""
        return self.available and self.is_approved

    @property
    def has_discount(self):
        """Check if tour has a discount."""
        return self.discount_price > 0 and self.discount_price < self.price_per_person

    @property
    def current_price(self):
        """Get the current price (discounted if applicable)."""
        return self.discount_price if self.has_discount else self.price_per_person

    @property
    def total_duration(self):
        """Get formatted duration string."""
        if self.duration_days == 1:
            return "1 day"
        else:
            return f"{self.duration_days} days, {self.duration_nights} nights"

    @property
    def discount_percentage(self):
        """Calculate discount percentage."""
        if self.has_discount:
            discount = self.price_per_person - self.discount_price
            return int((discount / self.price_per_person) * 100)
        return 0

    def approve(self, user):
        """Approve the tour."""
        self.is_approved = True
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['is_approved', 'approved_by', 'approved_at'])

    def get_similar_tours(self, limit=3):
        """Get similar tours based on category and difficulty."""
        return Tour.objects.filter(
            category=self.category,
            difficulty=self.difficulty,
            is_approved=True,
            available=True
        ).exclude(pk=self.pk).order_by('-featured', '-is_popular')[:limit]


# =============================================================================
# BOOKINGS & TRIPS MODELS
# =============================================================================

def generate_booking_reference():
    """Generate a unique booking reference."""
    timestamp = timezone.now().strftime("%Y%m%d")
    random_str = uuid.uuid4().hex[:4].upper()
    return f"SAF-{timestamp}-{random_str}"


class Booking(TimeStampedModel):
    """Model for bookings of transfers, excursions, or tours."""
    BOOKING_TYPE_CHOICES = [
        ('TRANSFER', 'Airport Transfer'),
        ('EXCURSION', 'Excursion'),
        ('TOUR', 'Tour / Safari'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('CONFIRMED', 'Confirmed'),
        ('CANCELLED', 'Cancelled'),
        ('COMPLETED', 'Completed'),
        ('NO_SHOW', 'No Show'),
        ('IN_PROGRESS', 'In Progress'),
    ]

    booking_customer = models.ForeignKey(
        'BookingCustomer', on_delete=models.CASCADE, related_name='bookings',
        null=True, blank=True
    )
    destination = models.ForeignKey(
        'Destination', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bookings'
    )
    tour = models.ForeignKey(
        'Tour', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bookings'
    )
    booking_type = models.CharField(
        max_length=20, choices=BOOKING_TYPE_CHOICES
    )

    booking_reference = models.CharField(
        max_length=50, unique=True, default=generate_booking_reference,
        editable=False
    )

    # Passengers
    num_adults = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)]
    )
    num_children = models.PositiveIntegerField(default=0)
    num_infants = models.PositiveIntegerField(default=0)

    # Locations
    pickup_location = models.CharField(max_length=200, blank=True, null=True)
    pickup_latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal('-90')), MaxValueValidator(Decimal('90'))]
    )
    pickup_longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal('-180')), MaxValueValidator(Decimal('180'))]
    )
    dropoff_location = models.CharField(max_length=200, blank=True, null=True)
    dropoff_latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal('-90')), MaxValueValidator(Decimal('90'))]
    )
    dropoff_longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal('-180')), MaxValueValidator(Decimal('180'))]
    )

    # Dates and times
    travel_date = models.DateField(validators=[validate_future_date])
    travel_time = models.TimeField(default=timezone.now)
    return_date = models.DateField(null=True, blank=True)
    return_time = models.TimeField(null=True, blank=True)

    # Status
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='PENDING'
    )

    # Additional information
    special_requests = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    booking_date = models.DateTimeField(default=timezone.now)

    # Pricing
    total_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    currency = models.CharField(max_length=10, default="KES")

    # Payment
    is_paid = models.BooleanField(default=False)
    is_cancelled = models.BooleanField(default=False)
    cancellation_reason = models.TextField(blank=True, null=True)

    # Carbon offset
    carbon_offset_option = models.BooleanField(default=False)
    carbon_offset_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00')
    )

    # Foreign keys
    driver = models.ForeignKey(
        'Driver', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bookings'
    )
    vehicle = models.ForeignKey(
        'Vehicle', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bookings'
    )

    # Managers
    objects = BookingManager()

    class Meta:
        verbose_name = "Booking"
        verbose_name_plural = "Bookings"
        indexes = [
            models.Index(fields=['booking_reference']),
            models.Index(fields=['travel_date']),
            models.Index(fields=['status']),
            models.Index(fields=['booking_customer', 'travel_date']),
        ]

    def __str__(self):
        return f"{self.booking_reference} - {self.booking_customer} - {self.destination or self.tour}"

    def save(self, *args, **kwargs):
        """Override save to auto-calculate price and update status."""
        # Auto-fill total price on save
        if self.destination:
            self.total_price = (self.num_adults + self.num_children) * self.destination.price_per_person
        elif self.tour:
            self.total_price = (self.num_adults + self.num_children) * self.tour.current_price

        # Calculate carbon offset if selected
        if self.carbon_offset_option:
            if self.destination:
                carbon_per_person = self.destination.carbon_footprint_per_visit
            elif self.tour:
                carbon_per_person = self.tour.carbon_footprint_per_person
            else:
                carbon_per_person = Decimal('0.00')

            total_carbon = carbon_per_person * (self.num_adults + self.num_children)
            # Assume $0.02 per kg of CO2 offset
            self.carbon_offset_amount = total_carbon * Decimal('0.02')
            self.total_price += self.carbon_offset_amount

        # Update is_paid status based on payment status
        if hasattr(self, 'payment') and self.payment:
            self.is_paid = self.payment.is_successful

        # Update cancellation status
        self.is_cancelled = self.status == 'CANCELLED'

        super().save(*args, **kwargs)

    @property
    def total_passengers(self):
        """Calculate total number of passengers."""
        return self.num_adults + self.num_children + self.num_infants

    @property
    def is_upcoming(self):
        """Check if booking is for a future date."""
        return self.travel_date >= timezone.now().date()

    @property
    def is_past(self):
        """Check if booking is for a past date."""
        return self.travel_date < timezone.now().date()

    @property
    def is_today(self):
        """Check if booking is for today."""
        return self.travel_date == timezone.now().date()

    @property
    def can_be_cancelled(self):
        """Check if booking can be cancelled."""
        return self.status in ['PENDING', 'CONFIRMED'] and self.is_upcoming

    @property
    def service_name(self):
        """Get the name of the service being booked."""
        if self.destination:
            return self.destination.name
        elif self.tour:
            return self.tour.title
        return "Unknown Service"

    def cancel(self, reason=""):
        """Cancel booking and update status."""
        if not self.can_be_cancelled:
            raise ValueError("This booking cannot be cancelled.")

        self.status = 'CANCELLED'
        self.is_cancelled = True
        self.cancellation_reason = reason
        self.save()

        # If payment exists, process refund
        if hasattr(self, 'payment') and self.payment.is_successful:
            self.payment.initiate_refund(reason=reason)

    def assign_driver(self, driver):
        """Assign a driver to this booking."""
        if not driver.available:
            raise ValueError("Driver is not available.")

        self.driver = driver
        self.vehicle = driver.vehicle
        self.save(update_fields=['driver', 'vehicle'])

    def confirm(self):
        """Confirm the booking."""
        if self.status != 'PENDING':
            raise ValueError("Only pending bookings can be confirmed.")

        self.status = 'CONFIRMED'
        self.save(update_fields=['status'])


class Trip(TimeStampedModel):
    """Model for trips completed by drivers."""
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    driver = models.ForeignKey(
        'Driver', on_delete=models.CASCADE, related_name='trips'
    )
    booking = models.ForeignKey(
        'Booking', on_delete=models.CASCADE, null=True, blank=True,
        related_name='trips'
    )
    vehicle = models.ForeignKey(
        'Vehicle', on_delete=models.CASCADE, related_name='trips'
    )
    destination = models.CharField(max_length=200)

    # Dates and times
    date = models.DateField()
    start_time = models.TimeField(default=timezone.now)
    end_time = models.TimeField(null=True, blank=True)

    # Metrics
    earnings = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    distance = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    fuel_consumed = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    carbon_emissions = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )

    # Status
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='SCHEDULED'
    )
    notes = models.TextField(blank=True, null=True)

    # Feedback
    customer_rating = models.PositiveIntegerField(
        null=True, blank=True, validators=[validate_rating]
    )
    customer_feedback = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Trip"
        verbose_name_plural = "Trips"
        indexes = [
            models.Index(fields=['driver', 'date']),
            models.Index(fields=['status']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"{self.destination} ({self.status}) - {self.driver.full_name}"

    @property
    def duration(self):
        """Calculate trip duration if start and end times are available."""
        if self.start_time and self.end_time:
            start = datetime.combine(self.date, self.start_time)
            end = datetime.combine(self.date, self.end_time)
            if end < start:  # Handle overnight trips
                end += timedelta(days=1)
            return end - start
        return None

    @property
    def fuel_efficiency(self):
        """Calculate fuel efficiency in km/l."""
        if self.distance and self.fuel_consumed and self.fuel_consumed > 0:
            return self.distance / self.fuel_consumed
        return None

    def complete(self, end_time=None, distance=None, fuel=None):
        """Mark trip as completed with optional details."""
        self.status = 'COMPLETED'
        if end_time:
            self.end_time = end_time
        if distance:
            self.distance = distance
        if fuel:
            self.fuel_consumed = fuel

        # Calculate carbon emissions if vehicle is available
        if self.vehicle and distance:
            self.carbon_emissions = distance * self.vehicle.carbon_footprint_per_km

        self.save()

        # Update driver stats
        self.driver.update_trip_stats(self.earnings)

    def start(self):
        """Mark trip as in progress."""
        if self.status != 'SCHEDULED':
            raise ValueError("Only scheduled trips can be started.")

        self.status = 'IN_PROGRESS'
        self.save(update_fields=['status'])

    def cancel(self, reason=""):
        """Cancel the trip."""
        if self.status == 'COMPLETED':
            raise ValueError("Cannot cancel a completed trip.")

        self.status = 'CANCELLED'
        if reason:
            self.notes = f"{self.notes}\n\nCancellation reason: {reason}" if self.notes else f"Cancellation reason: {reason}"
        self.save()


# =============================================================================
# PAYMENT MODELS
# =============================================================================

class PaymentProvider(models.TextChoices):
    MPESA = "MPESA", "M-PESA"
    PAYSTACK = "PAYSTACK", "Paystack"
    PAYPAL = "PAYPAL", "PayPal"
    CARD = "CARD", "Card Payment"
    AIRTEL = "AIRTEL", "Airtel Money"
    CASH = "CASH", "Cash"
    BANK = "BANK", "Bank Transfer"
    OTHER = "OTHER", "Other"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PROCESSING = "PROCESSING", "Processing"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"
    REFUNDED = "REFUNDED", "Refunded"
    PARTIAL_REFUND = "PARTIAL_REFUND", "Partial Refund"


class Payment(TimeStampedModel):
    """Model for payment records."""
    booking = models.OneToOneField(
        'Booking', on_delete=models.CASCADE, related_name='payment'
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    currency = models.CharField(max_length=10, default="KES")
    provider = models.CharField(
        max_length=20, choices=PaymentProvider.choices, default=PaymentProvider.MPESA
    )
    status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    provider_response = models.JSONField(default=dict, blank=True)

    # Refund fields
    refund_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    refund_reason = models.TextField(blank=True, null=True)
    refund_transaction_id = models.CharField(max_length=100, blank=True, null=True)
    refund_date = models.DateTimeField(null=True, blank=True)

    # Managers
    objects = PaymentManager()

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        indexes = [
            models.Index(fields=['booking']),
            models.Index(fields=['status']),
            models.Index(fields=['provider']),
            models.Index(fields=['transaction_id']),
        ]

    def __str__(self):
        return f"Payment {self.id} - {self.booking.booking_reference} - {self.amount} {self.currency}"

    @property
    def is_successful(self):
        """Check if payment was successful."""
        return self.status == PaymentStatus.SUCCESS

    @property
    def is_refunded(self):
        """Check if payment was refunded."""
        return self.status in [PaymentStatus.REFUNDED, PaymentStatus.PARTIAL_REFUND]

    @property
    def is_pending(self):
        """Check if payment is pending."""
        return self.status == PaymentStatus.PENDING

    def mark_successful(self, transaction_id=None, response_data=None):
        """Mark payment as successful."""
        self.status = PaymentStatus.SUCCESS
        if transaction_id:
            self.transaction_id = transaction_id
        if response_data:
            self.provider_response = response_data
        self.save()

        # Update booking payment status
        if self.booking:
            self.booking.is_paid = True
            self.booking.save(update_fields=['is_paid'])

    def mark_failed(self, response_data=None):
        """Mark payment as failed."""
        self.status = PaymentStatus.FAILED
        if response_data:
            self.provider_response = response_data
        self.save()

    def initiate_refund(self, amount=None, reason=""):
        """Initiate a refund for this payment."""
        if not self.is_successful:
            raise ValueError("Only successful payments can be refunded.")

        refund_amount = amount if amount else self.amount
        if refund_amount <= 0:
            raise ValueError("Refund amount must be greater than zero.")

        if refund_amount > self.amount:
            raise ValueError("Refund amount cannot exceed the original payment amount.")

        self.refund_amount = refund_amount
        self.refund_reason = reason

        # Determine refund status
        if refund_amount == self.amount:
            self.status = PaymentStatus.REFUNDED
        else:
            self.status = PaymentStatus.PARTIAL_REFUND

        self.refund_date = timezone.now()
        self.save()

        # Update booking payment status if fully refunded
        if self.status == PaymentStatus.REFUNDED:
            if self.booking:
                self.booking.is_paid = False
                self.booking.save(update_fields=['is_paid'])

        return True


# =============================================================================
# REVIEW MODELS
# =============================================================================

class Review(TimeStampedModel):
    """Model for customer reviews."""
    RATING_CHOICES = [
        (1, '1 - Poor'),
        (2, '2 - Fair'),
        (3, '3 - Good'),
        (4, '4 - Very Good'),
        (5, '5 - Excellent'),
    ]

    booking = models.OneToOneField(
        'Booking', on_delete=models.CASCADE, related_name='review'
    )
    driver = models.ForeignKey(
        'Driver', on_delete=models.CASCADE, related_name='reviews', null=True, blank=True
    )
    tour = models.ForeignKey(
        'Tour', on_delete=models.CASCADE, related_name='reviews', null=True, blank=True
    )
    destination = models.ForeignKey(
        'Destination', on_delete=models.CASCADE, related_name='reviews', null=True, blank=True
    )

    rating = models.PositiveIntegerField(choices=RATING_CHOICES)
    title = models.CharField(max_length=100, blank=True)
    comment = models.TextField(blank=True)

    # Approval
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_reviews"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Review"
        verbose_name_plural = "Reviews"
        indexes = [
            models.Index(fields=['rating']),
            models.Index(fields=['is_approved']),
            models.Index(fields=['driver']),
            models.Index(fields=['tour']),
            models.Index(fields=['destination']),
        ]

    def __str__(self):
        return f"Review for {self.booking.booking_reference} - {self.rating}/5"

    def approve(self, user):
        """Approve the review."""
        self.is_approved = True
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['is_approved', 'approved_by', 'approved_at'])

        # Update driver rating if applicable
        if self.driver:
            self.driver.update_rating(self.rating)


# =============================================================================
# CONTACT & INQUIRY MODELS
# =============================================================================

class ContactMessage(TimeStampedModel):
    """Model for contact form submissions."""
    INQUIRY_TYPES = [
        ('GENERAL', 'General Inquiry'),
        ('BOOKING', 'Booking Question'),
        ('PAYMENT', 'Payment Issue'),
        ('COMPLAINT', 'Complaint'),
        ('PARTNERSHIP', 'Partnership'),
        ('OTHER', 'Other'),
    ]

    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    ]

    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    inquiry_type = models.CharField(max_length=20, choices=INQUIRY_TYPES, default='GENERAL')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    subject = models.CharField(max_length=200)
    message = models.TextField()

    # Status
    is_read = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    assigned_to = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_messages"
    )
    resolved_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="resolved_messages"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    # Notes for admin
    admin_notes = models.TextField(blank=True)

    # IP address for tracking
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "Contact Message"
        verbose_name_plural = "Contact Messages"
        indexes = [
            models.Index(fields=['is_read']),
            models.Index(fields=['is_resolved']),
            models.Index(fields=['inquiry_type']),
            models.Index(fields=['priority']),
            models.Index(fields=['assigned_to']),
        ]

    def __str__(self):
        return f"{self.name} - {self.subject}"

    def mark_as_read(self):
        """Mark message as read."""
        self.is_read = True
        self.save(update_fields=['is_read'])

    def mark_as_resolved(self, user):
        """Mark message as resolved."""
        self.is_resolved = True
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.save(update_fields=['is_resolved', 'resolved_by', 'resolved_at'])

    def assign_to(self, user):
        """Assign message to a user."""
        self.assigned_to = user
        self.save(update_fields=['assigned_to'])


# =============================================================================
# NEWSLETTER MODELS
# =============================================================================

class NewsletterSubscription(TimeStampedModel):
    """Model for newsletter subscriptions."""
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Newsletter Subscription"
        verbose_name_plural = "Newsletter Subscriptions"
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.email

    def unsubscribe(self):
        """Unsubscribe from newsletter."""
        self.is_active = False
        self.save(update_fields=['is_active'])

    def subscribe(self):
        """Subscribe to newsletter."""
        self.is_active = True
        self.save(update_fields=['is_active'])


# =============================================================================
# SETTINGS MODELS
# =============================================================================

class SiteSettings(models.Model):
    """Model for site-wide settings."""
    site_name = models.CharField(max_length=100, default="Safari Tours")
    site_description = models.TextField(blank=True)
    contact_email = models.EmailField(default="info@safaritours.com")
    contact_phone = models.CharField(max_length=20, default="+254712345678")
    address = models.TextField(blank=True)

    # Social media links
    facebook_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)

    # Payment settings
    mpesa_paybill = models.CharField(max_length=10, blank=True)
    mpesa_account_number = models.CharField(max_length=20, blank=True)
    paystack_public_key = models.CharField(max_length=100, blank=True)
    paystack_secret_key = models.CharField(max_length=100, blank=True)

    # Email settings
    email_host = models.CharField(max_length=100, blank=True)
    email_port = models.PositiveIntegerField(default=587)
    email_host_user = models.EmailField(blank=True)
    email_host_password = models.CharField(max_length=100, blank=True)
    email_use_tls = models.BooleanField(default=True)

    # Other settings
    maintenance_mode = models.BooleanField(default=False)
    maintenance_message = models.TextField(blank=True)

    class Meta:
        verbose_name = "Site Settings"
        verbose_name_plural = "Site Settings"

    def __str__(self):
        return self.site_name

    def save(self, *args, **kwargs):
        # Ensure there's only one instance of SiteSettings
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        """Load the site settings, creating a default instance if needed."""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


# =============================================================================
# FAQ MODELS
# =============================================================================

class FAQCategory(TimeStampedModel):
    """Model for FAQ categories."""
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "FAQ Category"
        verbose_name_plural = "FAQ Categories"
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Override save to auto-generate slug."""
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while FAQCategory.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)


class FAQ(TimeStampedModel):
    """Model for frequently asked questions."""
    question = models.CharField(max_length=200)
    answer = models.TextField()
    category = models.ForeignKey(
        'FAQCategory', on_delete=models.CASCADE, related_name='faqs'
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"
        ordering = ['category', 'order', 'question']

    def __str__(self):
        return self.question


# =============================================================================
# BLOG MODELS
# =============================================================================

class BlogCategory(TimeStampedModel):
    """Model for blog categories."""
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Blog Category"
        verbose_name_plural = "Blog Categories"
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Override save to auto-generate slug."""
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while BlogCategory.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)


class BlogPost(TimeStampedModel):
    """Model for blog posts."""
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    excerpt = models.TextField(max_length=300, help_text="Brief summary of the post")
    content = models.TextField()

    featured_image = models.ImageField(
        upload_to='uploads/blog/%Y/%m/',
        blank=True,
        null=True,
        help_text="Upload featured image (stored locally, max 100MB)"
    )

    image_url = models.URLField(
        blank=True,
        null=True,
        help_text="Optional external image URL for featured image"
    )

    # Metadata
    meta_description = models.CharField(max_length=160, blank=True)
    meta_keywords = models.CharField(max_length=255, blank=True)

    # Status and visibility
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    # Relationships
    author = models.ForeignKey(
        'auth.User', on_delete=models.CASCADE, related_name='blog_posts'
    )
    category = models.ForeignKey(
        'BlogCategory', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='blog_posts'
    )
    tags = models.ManyToManyField('BlogTag', blank=True, related_name='blog_posts')

    # SEO
    seo_title = models.CharField(max_length=60, blank=True)

    class Meta:
        verbose_name = "Blog Post"
        verbose_name_plural = "Blog Posts"
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['is_published']),
            models.Index(fields=['is_featured']),
            models.Index(fields=['published_at']),
            models.Index(fields=['author']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        """Override save to auto-generate slug and set published_at."""
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while BlogPost.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        # Set published_at when publishing for the first time
        if self.is_published and not self.published_at:
            self.published_at = timezone.now()

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        """Get the absolute URL for this blog post."""
        return reverse('blog_detail', kwargs={'slug': self.slug})

    @property
    def primary_image(self):
        """Return the primary image URL."""
        if self.featured_image:
            return self.featured_image.url
        return self.image_url or "/static/img/blog-placeholder.jpg"

    @property
    def reading_time(self):
        """Estimate reading time in minutes."""
        word_count = len(self.content.split())
        return max(1, round(word_count / 200))  # Assuming 200 words per minute


class BlogTag(TimeStampedModel):
    """Model for blog tags."""
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=60, unique=True, blank=True)

    class Meta:
        verbose_name = "Blog Tag"
        verbose_name_plural = "Blog Tags"
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Override save to auto-generate slug."""
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while BlogTag.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)


# =============================================================================
# TESTIMONIAL MODELS
# =============================================================================

class Testimonial(TimeStampedModel):
    """Model for customer testimonials."""
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField(blank=True)
    customer_photo = CloudinaryField("image", blank=True, null=True)
    photo_url = models.URLField(blank=True, null=True)
    rating = models.PositiveIntegerField(
        choices=[(i, f"{i} Stars") for i in range(1, 6)],
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    testimonial = models.TextField()
    tour = models.ForeignKey(
        'Tour', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='testimonials'
    )
    destination = models.ForeignKey(
        'Destination', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='testimonials'
    )
    is_featured = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Testimonial"
        verbose_name_plural = "Testimonials"
        ordering = ['-is_featured', '-created_at']
        indexes = [
            models.Index(fields=['is_featured']),
            models.Index(fields=['is_approved']),
            models.Index(fields=['rating']),
        ]

    def __str__(self):
        return f"Testimonial by {self.customer_name}"

    @property
    def customer_photo_url(self):
        """Return the customer photo URL."""
        if self.customer_photo:
            return self.customer_photo.url
        return self.photo_url or "/static/img/avatar-placeholder.jpg"

    def approve(self):
        """Approve the testimonial."""
        self.is_approved = True
        self.save(update_fields=['is_approved'])

    def feature(self):
        """Feature the testimonial."""
        self.is_featured = True
        self.save(update_fields=['is_featured'])


# =============================================================================
# BANNER MODELS
# =============================================================================

class Banner(TimeStampedModel):
    """Model for homepage banners."""
    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)

    # Desktop Image
    image = models.ImageField(
        upload_to='uploads/banners/images/%Y/%m/',
        blank=True,
        null=True,
        help_text="Upload main banner image (stored locally, max 100MB)"
    )

    image_url = models.URLField(
        blank=True,
        null=True,
        help_text="Optional external image URL for desktop view"
    )

    # Mobile Image
    mobile_image = models.ImageField(
        upload_to='uploads/banners/mobile/%Y/%m/',
        blank=True,
        null=True,
        help_text="Upload mobile banner image (stored locally, max 100MB)"
    )

    mobile_image_url = models.URLField(
        blank=True,
        null=True,
        help_text="Optional external image URL for mobile view"
    )

    # Link
    link_url = models.URLField(blank=True)
    link_text = models.CharField(max_length=50, default="Learn More")

    # Display options
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    # Banner type
    BANNER_TYPES = [
        ('HERO', 'Hero Banner'),
        ('PROMOTION', 'Promotion Banner'),
        ('FEATURED', 'Featured Tour Banner'),
        ('ANNOUNCEMENT', 'Announcement Banner'),
    ]
    banner_type = models.CharField(max_length=20, choices=BANNER_TYPES, default='HERO')

    # Related content
    tour = models.ForeignKey(
        'Tour', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='banners'
    )
    destination = models.ForeignKey(
        'Destination', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='banners'
    )

    class Meta:
        verbose_name = "Banner"
        verbose_name_plural = "Banners"
        ordering = ['order', '-created_at']
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['banner_type']),
            models.Index(fields=['order']),
        ]

    def __str__(self):
        return self.title

    @property
    def primary_image(self):
        """Return the primary image URL."""
        if self.image:
            return self.image.url
        return self.image_url or "/static/img/banner-placeholder.jpg"

    @property
    def primary_mobile_image(self):
        """Return the mobile image URL."""
        if self.mobile_image:
            return self.mobile_image.url
        return self.mobile_image_url or self.primary_image


# =============================================================================
# PARTNER MODELS
# =============================================================================

class Partner(TimeStampedModel):
    """Model for partners and affiliates."""
    name = models.CharField(max_length=100)
    logo = CloudinaryField("image", blank=True, null=True)
    logo_url = models.URLField(blank=True, null=True)
    website_url = models.URLField(blank=True)
    description = models.TextField(blank=True)

    # Partner type
    PARTNER_TYPES = [
        ('HOTEL', 'Hotel'),
        ('AIRLINE', 'Airline'),
        ('ACTIVITY', 'Activity Provider'),
        ('TRANSPORT', 'Transport Provider'),
        ('INSURANCE', 'Insurance'),
        ('OTHER', 'Other'),
    ]
    partner_type = models.CharField(max_length=20, choices=PARTNER_TYPES, default='OTHER')

    # Display options
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Partner"
        verbose_name_plural = "Partners"
        ordering = ['order', 'name']
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['is_featured']),
            models.Index(fields=['partner_type']),
        ]

    def __str__(self):
        return self.name

    @property
    def logo_image_url(self):
        """Return the logo URL."""
        if self.logo:
            return self.logo.url
        return self.logo_url or "/static/img/partner-placeholder.png"

