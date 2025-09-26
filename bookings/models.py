# =============================================================================
# IMPORTS
# =============================================================================
import uuid
import logging
import hmac
import hashlib
import re
from decimal import Decimal
from datetime import date, datetime, time, timedelta
from typing import Optional, List, Dict, Any, Tuple, Union

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
from cloudinary.models import CloudinaryField

# Logger
logger = logging.getLogger(__name__)


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
# BOOKING CUSTOMER MODEL
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
# DRIVER MODEL (concrete model with profile fields included)
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
    def age(self):
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


# =============================================================================
# VEHICLE MODEL (unchanged)
# =============================================================================
class Vehicle(TimeStampedModel):
    """Model for vehicles used by drivers."""
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

    make = models.CharField(max_length=50, help_text="Vehicle make (e.g., Toyota)")
    model = models.CharField(max_length=50, help_text="Vehicle model (e.g., Hilux)")
    year = models.PositiveIntegerField(help_text="Year of manufacture")
    color = models.CharField(max_length=30, blank=True, null=True)
    license_plate = models.CharField(max_length=20, unique=True)
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_TYPES)
    fuel_type = models.CharField(max_length=20, choices=FUEL_TYPES)
    capacity = models.PositiveIntegerField(help_text="Passenger capacity")

    # Features
    features = models.JSONField(
        default=dict, blank=True,
        help_text="Vehicle features (AC, WiFi, etc.)"
    )
    accessibility_features = models.JSONField(
        default=dict, blank=True,
        help_text="Accessibility features (wheelchair access, etc.)"
    )

    # Documents
    logbook_copy = CloudinaryField(
        "raw", blank=True, null=True, help_text="Copy of vehicle logbook"
    )
    insurance_copy = CloudinaryField(
        "raw", blank=True, null=True, help_text="Copy of insurance certificate"
    )
    inspection_certificate = CloudinaryField(
        "raw", blank=True, null=True, help_text="Vehicle inspection certificate"
    )

    # Dates
    insurance_expiry = models.DateField(null=True, blank=True)
    inspection_expiry = models.DateField(null=True, blank=True)

    # Status
    is_active = models.BooleanField(default=True)
    carbon_footprint_per_km = models.DecimalField(
        max_digits=6, decimal_places=3, default=Decimal('0.120'),
        help_text="CO2 emissions per km in kg"
    )

    class Meta:
        verbose_name = "Vehicle"
        verbose_name_plural = "Vehicles"
        indexes = [
            models.Index(fields=['license_plate']),
            models.Index(fields=['vehicle_type']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.year} {self.make} {self.model} ({self.license_plate})"

    @property
    def insurance_status(self):
        """Check if insurance is valid."""
        if self.insurance_expiry:
            return self.insurance_expiry > timezone.now().date()
        return True

    @property
    def inspection_status(self):
        """Check if inspection is valid."""
        if self.inspection_expiry:
            return self.inspection_expiry > timezone.now().date()
        return True


# =============================================================================
# DESTINATIONS & TOURS
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
    image = CloudinaryField("image", blank=True, null=True)
    video = CloudinaryField("video", resource_type="video", blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    gallery_images = models.JSONField(
        default=list, blank=True, help_text="List of additional image URLs"
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
    image = CloudinaryField("image", blank=True, null=True)

    # Managers
    objects = models.Manager()
    active = ActiveManager()

    class Meta:
        verbose_name = "Tour Category"
        verbose_name_plural = "Tour Categories"
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Override save to auto-generate slug."""
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
        """Get the absolute URL for this category."""
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
    image = CloudinaryField("image", blank=True, null=True)
    video = CloudinaryField("video", resource_type="video", blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    gallery_images = models.JSONField(
        default=list, blank=True, help_text="List of additional image URLs"
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
        """Get the absolute URL for this tour."""
        return reverse('tour_detail', kwargs={'slug': self.slug})

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
# BOOKINGS & TRIPS
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
# PAYMENTS
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
    """Model for payments."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Payer info
    user = models.ForeignKey(
        'auth.User', on_delete=models.CASCADE, null=True, blank=True,
        related_name="payments"
    )
    guest_full_name = models.CharField(max_length=200, blank=True, null=True)
    guest_email = models.EmailField(blank=True, null=True)
    guest_phone = models.CharField(max_length=20, blank=True, null=True)
    normalized_guest_phone = models.CharField(max_length=20, blank=True)

    # Booking details
    booking = models.OneToOneField(
        "Booking", on_delete=models.CASCADE, null=True, blank=True,
        related_name="payment"
    )
    tour = models.ForeignKey(
        "Tour", on_delete=models.CASCADE, null=True, blank=True,
        related_name="payments"
    )
    travel_date = models.DateField(default=timezone.now)

    # Passenger details
    adults = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField(default=0)
    days = models.PositiveIntegerField(default=1)

    # Billing
    billing_line1 = models.CharField(max_length=255, default="Nairobi")
    billing_city = models.CharField(max_length=100, default="Nairobi")
    billing_state = models.CharField(max_length=100, default="Nairobi")
    billing_postal_code = models.CharField(max_length=20, default="00100")
    billing_country_code = models.CharField(max_length=3, default="KE")

    # Payment details
    provider = models.CharField(
        max_length=20, choices=PaymentProvider.choices,
        default=PaymentProvider.PAYSTACK
    )
    method = models.CharField(
        max_length=20, choices=PaymentProvider.choices,
        default=PaymentProvider.PAYSTACK
    )
    currency = models.CharField(max_length=10, default="KES")
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0.00,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    amount_paid = models.DecimalField(
        max_digits=12, decimal_places=2, default=0.00,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    phone_number = models.CharField(max_length=20, blank=True, default="")
    status = models.CharField(
        max_length=20, choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING
    )

    # Paystack transaction
    reference = models.CharField(max_length=100, db_index=True, default="")
    access_code = models.CharField(max_length=255, blank=True, null=True)
    paystack_transaction_id = models.CharField(max_length=255, blank=True, null=True)
    transaction_id = models.CharField(max_length=100, blank=True, default="")
    authorization_code = models.CharField(max_length=100, blank=True, default="")
    raw_response = models.JSONField(blank=True, null=True)

    # Webhook verification
    webhook_verified = models.BooleanField(default=False)
    webhook_received_at = models.DateTimeField(null=True, blank=True)

    # Additional
    description = models.TextField(default="Payment for Tour")
    paid_on = models.DateTimeField(blank=True, null=True)
    failure_reason = models.TextField(blank=True, null=True)
    payment_channel = models.CharField(max_length=50, blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)

    # Refunds
    refund_reference = models.CharField(max_length=100, blank=True, null=True)
    refund_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    refund_reason = models.TextField(blank=True, null=True)
    refunded_on = models.DateTimeField(null=True, blank=True)

    # Managers
    objects = PaymentManager()

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['paystack_transaction_id']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        identity = self.guest_full_name or (
            self.user.get_full_name() if self.user else "Guest"
        )
        return f"{identity} - {self.amount} {self.currency} ({self.status})"

    def save(self, *args, **kwargs):
        if self.guest_phone and not self.normalized_guest_phone:
            self.normalized_guest_phone = normalize_phone_number(self.guest_phone)
        if self.status == PaymentStatus.SUCCESS:
            if not self.amount_paid:
                self.amount_paid = self.amount
            if not self.paid_on:
                self.paid_on = timezone.now()
        super().save(*args, **kwargs)

    # ==============================
    # PAYSTACK WEBHOOK HANDLING
    # ==============================
    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        secret = settings.PAYSTACK_SECRET_KEY
        computed_signature = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
        return hmac.compare_digest(computed_signature, signature)

    def process_paystack_webhook(self, payload: dict) -> bool:
        try:
            event = payload.get('event')
            data = payload.get('data', {})

            if event == 'charge.success':
                self.reference = data.get('reference')
                self.paystack_transaction_id = str(data.get('id'))
                self.amount_paid = Decimal(data.get('amount', 0)) / 100
                self.payment_channel = data.get('channel')
                self.ip_address = data.get('ip_address')
                self.authorization_code = data.get('authorization', {}).get('authorization_code', '')
                self.webhook_verified = True
                self.webhook_received_at = timezone.now()
                self.status = PaymentStatus.SUCCESS
                self.paid_on = timezone.now()
                self.raw_response = payload

                self.save()

                if self.booking:
                    self.booking.status = 'CONFIRMED'
                    self.booking.save()

                self.send_confirmation_email()
                logger.info(f"Processed Paystack webhook successfully for payment {self.id}")
                return True

            elif event == 'charge.failed':
                self.status = PaymentStatus.FAILED
                self.failure_reason = data.get('message', 'Payment failed')
                self.webhook_verified = True
                self.webhook_received_at = timezone.now()
                self.raw_response = payload
                self.save()
                logger.warning(f"Payment {self.id} failed via webhook: {self.failure_reason}")
                return False

        except Exception as e:
            logger.error(f"Error processing Paystack webhook for payment {self.id}: {e}")
            return False

    # ==============================
    # VERIFY PAYSTACK TRANSACTION
    # ==============================
    def verify_paystack_transaction(self) -> bool:
        if not self.reference:
            logger.error(f"Cannot verify payment without reference: {self.id}")
            return False
        try:
            url = f"https://api.paystack.co/transaction/verify/{self.reference}"
            headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
            response = requests.get(url, headers=headers)
            resp_data = response.json()

            if resp_data.get('status'):
                data = resp_data.get('data', {})
                self.paystack_transaction_id = str(data.get('id'))
                self.amount_paid = Decimal(data.get('amount', 0)) / 100
                self.payment_channel = data.get('channel')
                self.ip_address = data.get('ip_address')
                self.raw_response = data

                if data.get('status') == 'success':
                    self.status = PaymentStatus.SUCCESS
                    self.paid_on = timezone.now()
                    if self.booking:
                        self.booking.status = 'CONFIRMED'
                        self.booking.save()
                    self.send_confirmation_email()
                else:
                    self.status = PaymentStatus.FAILED
                    self.failure_reason = data.get('gateway_response', 'Payment failed')

                self.save()
                logger.info(f"Verified Paystack transaction for payment {self.id}")
                return True

            else:
                self.status = PaymentStatus.FAILED
                self.failure_reason = resp_data.get('message', 'Verification failed')
                self.save()
                logger.error(f"Paystack verification failed for payment {self.id}")
                return False

        except Exception as e:
            logger.error(f"Error verifying Paystack transaction for payment {self.id}: {e}")
            return False

    # ==============================
    # INITIATE REFUND
    # ==============================
    def initiate_refund(self, amount: Decimal = None, reason: str = "") -> bool:
        if not self.is_successful:
            logger.error(f"Cannot refund unsuccessful payment {self.id}")
            return False
        if amount is None:
            amount = self.amount_paid
        try:
            url = "https://api.paystack.co/refund"
            headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
            payload = {
                "transaction": self.paystack_transaction_id,
                "amount": int(amount * 100),
                "currency": self.currency,
                "reason": reason or "Customer requested refund"
            }
            response = requests.post(url, json=payload, headers=headers)
            resp_data = response.json()

            if resp_data.get('status'):
                refund = resp_data.get('data', {})
                self.refund_reference = refund.get('reference')
                self.refund_amount = amount
                self.refund_reason = reason
                self.refunded_on = timezone.now()
                self.status = PaymentStatus.REFUNDED if amount == self.amount_paid else PaymentStatus.PARTIAL_REFUND
                self.save()
                logger.info(f"Refund initiated for payment {self.id} with reference {self.refund_reference}")
                return True
            else:
                logger.error(f"Refund failed for payment {self.id}: {resp_data.get('message')}")
                return False

        except Exception as e:
            logger.error(f"Error initiating refund for payment {self.id}: {e}")
            return False

    # ==============================
    # EMAIL NOTIFICATIONS
    # ==============================
    def send_confirmation_email(self):
        email = self.payer_email
        if not email:
            logger.warning(f"No email available for payment {self.id}")
            return
        context = {'payment': self, 'tour': self.tour, 'booking': self.booking}
        subject = render_to_string('payments/email/confirmation_subject.txt', context).strip()
        text_body = render_to_string('payments/email/confirmation_email.txt', context)
        html_body = render_to_string('payments/email/confirmation_email.html', context)
        send_mail(subject, text_body, settings.DEFAULT_FROM_EMAIL, [email], html_message=html_body)
        logger.info(f"Confirmation email sent to {email} for payment {self.id}")

    # ==============================
    # HELPER PROPERTIES
    # ==============================
    @property
    def is_successful(self):
        return self.status == PaymentStatus.SUCCESS

    @property
    def payer_email(self):
        if self.guest_email:
            return self.guest_email
        elif self.booking and self.booking.booking_customer:
            return self.booking.booking_customer.email
        elif self.user:
            return self.user.email
        return None


# =============================================================================
# REVIEWS
# =============================================================================
class Review(TimeStampedModel):
    """Model for customer reviews for tours and drivers."""
    RATING_CHOICES = [
        (1, '1 - Poor'),
        (2, '2 - Fair'),
        (3, '3 - Good'),
        (4, '4 - Very Good'),
        (5, '5 - Excellent'),
    ]

    booking = models.ForeignKey(
        'Booking', on_delete=models.CASCADE, related_name='reviews'
    )
    tour = models.ForeignKey(
        'Tour', on_delete=models.CASCADE, related_name='reviews',
        null=True, blank=True
    )
    driver = models.ForeignKey(
        'Driver', on_delete=models.CASCADE, related_name='reviews',
        null=True, blank=True
    )

    # Overall rating
    rating = models.PositiveIntegerField(
        choices=RATING_CHOICES, validators=[validate_rating]
    )

    # Detailed ratings
    safety_rating = models.PositiveIntegerField(
        choices=RATING_CHOICES, null=True, blank=True
    )
    cleanliness_rating = models.PositiveIntegerField(
        choices=RATING_CHOICES, null=True, blank=True
    )
    value_rating = models.PositiveIntegerField(
        choices=RATING_CHOICES, null=True, blank=True
    )
    comfort_rating = models.PositiveIntegerField(
        choices=RATING_CHOICES, null=True, blank=True
    )
    punctuality_rating = models.PositiveIntegerField(
        choices=RATING_CHOICES, null=True, blank=True
    )

    # Content
    title = models.CharField(max_length=200)
    comment = models.TextField()

    # Status
    is_public = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)

    # Response
    response = models.TextField(blank=True, null=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    responded_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="review_responses"
    )

    class Meta:
        verbose_name = "Review"
        verbose_name_plural = "Reviews"
        unique_together = ['booking', 'tour', 'driver']
        indexes = [
            models.Index(fields=['rating']),
            models.Index(fields=['is_public']),
            models.Index(fields=['is_verified']),
            models.Index(fields=['tour', 'rating']),
            models.Index(fields=['driver', 'rating']),
        ]

    def __str__(self):
        return f"Review by {self.booking.booking_customer} - {self.rating}/5"

    def verify(self):
        """Mark review as verified."""
        self.is_verified = True
        self.verified_at = timezone.now()
        self.save(update_fields=['is_verified', 'verified_at'])

    def respond(self, response, user):
        """Add a response to the review."""
        self.response = response
        self.responded_at = timezone.now()
        self.responded_by = user
        self.save(update_fields=['response', 'responded_at', 'responded_by'])

    def get_rating_text(self):
        """Get human-readable rating text."""
        rating_map = {
            1: "Poor",
            2: "Fair",
            3: "Good",
            4: "Very Good",
            5: "Excellent"
        }
        return rating_map.get(self.rating, "Unknown")

    @property
    def review_target(self):
        """Get the target of the review (tour or driver)."""
        if self.tour:
            return self.tour
        elif self.driver:
            return self.driver
        return None

    @property
    def review_target_name(self):
        """Get the name of the review target."""
        target = self.review_target
        if target:
            return str(target)
        return "Unknown"

    @property
    def average_detailed_rating(self):
        """Calculate average of detailed ratings."""
        ratings = [
            self.safety_rating, self.cleanliness_rating, self.value_rating,
            self.comfort_rating, self.punctuality_rating
        ]
        valid_ratings = [r for r in ratings if r is not None]
        if valid_ratings:
            return sum(valid_ratings) / len(valid_ratings)
        return None


# =============================================================================
# CONTENT & MISC
# =============================================================================
class ContactMessage(TimeStampedModel):
    """Model for messages from the contact page."""
    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    ]

    INQUIRY_TYPES = [
        ('GENERAL', 'General Inquiry'),
        ('BOOKING', 'Booking Question'),
        ('PAYMENT', 'Payment Issue'),
        ('COMPLAINT', 'Complaint'),
        ('PARTNERSHIP', 'Partnership Opportunity'),
        ('FEEDBACK', 'Feedback'),
        ('TECHNICAL', 'Technical Support'),
    ]

    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(
        max_length=20, blank=True, null=True,
        validators=[validate_phone_number]
    )
    inquiry_type = models.CharField(
        max_length=20, choices=INQUIRY_TYPES, default='GENERAL'
    )
    subject = models.CharField(max_length=200)
    message = models.TextField()
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM'
    )
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="resolved_messages"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    assigned_to = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_messages"
    )

    class Meta:
        verbose_name = "Contact Message"
        verbose_name_plural = "Contact Messages"
        indexes = [
            models.Index(fields=['priority']),
            models.Index(fields=['is_resolved']),
            models.Index(fields=['assigned_to']),
        ]

    def __str__(self):
        return f"Message from {self.name} - {self.subject}"

    def mark_resolved(self, user):
        """Mark message as resolved by the given user."""
        self.is_resolved = True
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.save(update_fields=['is_resolved', 'resolved_by', 'resolved_at'])

    def assign_to(self, user):
        """Assign message to a user."""
        self.assigned_to = user
        self.save(update_fields=['assigned_to'])

    @property
    def is_assigned(self):
        """Check if message is assigned to someone."""
        return self.assigned_to is not None

    @property
    def is_overdue(self):
        """Check if message is overdue for resolution."""
        if self.is_resolved:
            return False

        # Messages older than 3 days with high or urgent priority are overdue
        if self.priority in ['HIGH', 'URGENT']:
            return (timezone.now() - self.created_at).days > 3

        # Messages older than 7 days with medium priority are overdue
        if self.priority == 'MEDIUM':
            return (timezone.now() - self.created_at).days > 7

        return False