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
from typing import Optional, List, Dict, Any

from django.conf import settings
from django.core.mail import send_mail
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.core.validators import RegexValidator
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
    """
    Normalize a phone number to E.164 format.

    Args:
        phone_number: The phone number to normalize

    Returns:
        The normalized phone number in E.164 format
    """
    if not phone_number:
        return ""

    # Remove all non-digit characters
    cleaned = re.sub(r'[^\d]', '', phone_number)

    # Handle Kenyan numbers (assume Kenya if country code not specified)
    if cleaned.startswith('0') and len(cleaned) == 10:  # Local format like 0712345678
        return '+254' + cleaned[1:]
    elif cleaned.startswith('7') and len(cleaned) == 9:  # Local format without leading 0
        return '+254' + cleaned
    elif cleaned.startswith('254') and len(cleaned) == 12:  # International format without +
        return '+' + cleaned
    elif cleaned.startswith('+254') and len(cleaned) == 13:  # Already in E.164 format
        return cleaned

    # For other countries, just add + if it's missing and seems to be a full number
    if len(cleaned) >= 10 and not cleaned.startswith('+'):
        return '+' + cleaned

    return phone_number


def validate_phone_number(value: str) -> None:
    """
    Validate that a phone number is in a valid format.

    Args:
        value: The phone number to validate

    Raises:
        ValidationError: If the phone number is invalid
    """
    normalized = normalize_phone_number(value)
    if not re.match(r'^\+\d{6,15}$', normalized):
        raise ValidationError(
            'Please enter a valid phone number in international format (e.g., +254712345678)'
        )


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
        """Return pending bookings."""
        return self.filter(status='PENDING')

    def confirmed(self):
        """Return confirmed bookings."""
        return self.filter(status='CONFIRMED')

    def upcoming(self):
        """Return upcoming bookings."""
        today = timezone.now().date()
        return self.filter(travel_date__gte=today)

    def past(self):
        """Return past bookings."""
        today = timezone.now().date()
        return self.filter(travel_date__lt=today)


# =============================================================================
# BASE ABSTRACT MODEL
# =============================================================================
class TimeStampedModel(models.Model):
    """Abstract base model with created_at and updated_at fields."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']


# =============================================================================
# DESTINATIONS & CUSTOMERS
# =============================================================================
class Destination(TimeStampedModel):
    """Model for travel destinations."""
    DESTINATION_TYPES = [
        ('TRANSFER', 'Airport Transfer'),
        ('EXCURSION', 'Excursion'),
        ('TOUR', 'Tour / Safari'),
    ]

    name = models.CharField(
        max_length=150,
        unique=True,
        help_text="Name of the destination"
    )
    slug = models.SlugField(
        max_length=170,
        unique=True,
        blank=True,
        help_text="URL-friendly version of name"
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed description of the destination"
    )
    location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Physical location of the destination"
    )
    price_per_person = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Price per person in KES"
    )
    destination_type = models.CharField(
        max_length=20,
        choices=DESTINATION_TYPES,
        default='TOUR',
        help_text="Type of destination"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this destination is currently available"
    )
    is_featured = models.BooleanField(
        default=False,
        help_text="Feature this destination on homepage"
    )

    # Media
    image = models.ImageField(
        upload_to="destinations/",
        blank=True,
        null=True,
        help_text="Primary image for the destination"
    )
    video = models.FileField(
        upload_to="destinations/videos/",
        blank=True,
        null=True,
        help_text="Promotional video for the destination"
    )
    image_url = models.URLField(
        blank=True,
        null=True,
        help_text="External image URL as fallback"
    )

    # Location data
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="GPS latitude coordinate"
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="GPS longitude coordinate"
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

    def clean(self):
        """Validate model fields."""
        if self.price_per_person < 0:
            raise ValidationError("Price per person cannot be negative.")

        if self.latitude and not (-90 <= float(self.latitude) <= 90):
            raise ValidationError("Latitude must be between -90 and 90.")

        if self.longitude and not (-180 <= float(self.longitude) <= 180):
            raise ValidationError("Longitude must be between -180 and 180.")

    def save(self, *args, **kwargs):
        """Override save to auto-generate slug and validate."""
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Destination.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        self.full_clean()
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

    @property
    def has_coordinates(self):
        """Check if both latitude and longitude are set."""
        return self.latitude is not None and self.longitude is not None


class Customer(TimeStampedModel):
    """Model for customers who make bookings."""
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
        ('P', 'Prefer not to say'),
    ]

    first_name = models.CharField(
        max_length=100,
        help_text="Customer's first name"
    )
    last_name = models.CharField(
        max_length=100,
        help_text="Customer's last name"
    )
    email = models.EmailField(
        unique=True,
        help_text="Customer's email address"
    )
    phone_number = models.CharField(
        max_length=20,
        validators=[validate_phone_number],
        help_text="Customer's phone number"
    )
    normalized_phone = models.CharField(
        max_length=20,
        blank=True,
        help_text="E.164 formatted phone number"
    )
    gender = models.CharField(
        max_length=1,
        choices=GENDER_CHOICES,
        blank=True,
        null=True,
        help_text="Customer's gender"
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        help_text="Customer's date of birth"
    )
    nationality = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Customer's nationality"
    )
    passport_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Customer's passport number"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this customer account is active"
    )
    is_vip = models.BooleanField(
        default=False,
        help_text="VIP customer status"
    )

    # Managers
    objects = models.Manager()
    active = ActiveManager()

    class Meta:
        verbose_name = "Customer"
        verbose_name_plural = "Customers"

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    def clean(self):
        """Validate model fields."""
        if self.date_of_birth and self.date_of_birth > date.today():
            raise ValidationError("Date of birth cannot be in the future.")

        if self.passport_number and len(self.passport_number) < 5:
            raise ValidationError("Passport number seems too short.")

    def save(self, *args, **kwargs):
        """Override save to normalize phone number."""
        if self.phone_number and not self.normalized_phone:
            self.normalized_phone = normalize_phone_number(self.phone_number)

        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        """Return the customer's full name."""
        return f"{self.first_name} {self.last_name}"

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
        """Check if customer is an adult (18+)."""
        age = self.age
        return age is not None and age >= 18

    def get_booking_history(self):
        """Get all bookings for this customer."""
        return self.bookings.all().order_by('-travel_date')


# =============================================================================
# DRIVERS & BOOKINGS
# =============================================================================
class Driver(TimeStampedModel):
    """
    Model for drivers assigned to bookings.
    Enhanced with better profile information and status tracking.
    """
    LICENSE_TYPES = [
        ('PROFESSIONAL', 'Professional'),
        ('COMMERCIAL', 'Commercial'),
    ]

    user = models.OneToOneField(
        'auth.User',
        on_delete=models.CASCADE,
        related_name="driver",
        null=True,
        blank=True,
        help_text="Linked user account for the driver"
    )
    name = models.CharField(
        max_length=150,
        help_text="Driver's full name"
    )
    phone_number = models.CharField(
        max_length=20,
        validators=[validate_phone_number],
        help_text="Driver's phone number"
    )
    normalized_phone = models.CharField(
        max_length=20,
        blank=True,
        help_text="E.164 formatted phone number"
    )
    license_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="Driver's license number"
    )
    license_type = models.CharField(
        max_length=20,
        choices=LICENSE_TYPES,
        default='COMMERCIAL',
        help_text="Type of driving license"
    )
    license_expiry = models.DateField(
        null=True,
        blank=True,
        help_text="License expiry date"
    )
    available = models.BooleanField(
        default=True,
        help_text="Whether the driver is currently available"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this driver account is active"
    )
    is_verified = models.BooleanField(
        default=False,
        help_text="Driver has been verified by admin"
    )

    # Extended profile
    profile_picture = models.ImageField(
        upload_to="drivers/",
        blank=True,
        null=True,
        help_text="Driver's profile picture"
    )
    experience_years = models.PositiveIntegerField(
        default=0,
        help_text="Years of driving experience"
    )
    vehicle = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Vehicle model"
    )
    vehicle_plate = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Vehicle license plate number"
    )
    vehicle_capacity = models.PositiveIntegerField(
        default=4,
        help_text="Vehicle passenger capacity"
    )
    bio = models.TextField(
        blank=True,
        null=True,
        help_text="Driver's professional bio"
    )
    rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal('0.0'),
        help_text="Average customer rating (0.0-5.0)"
    )
    total_trips = models.PositiveIntegerField(
        default=0,
        help_text="Total number of completed trips"
    )
    total_earnings = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total earnings from all trips"
    )

    # Managers
    objects = models.Manager()
    active = ActiveManager()
    available_drivers = models.Manager()

    class Meta:
        verbose_name = "Driver"
        verbose_name_plural = "Drivers"

    def __str__(self):
        return self.name

    def clean(self):
        """Validate model fields."""
        if self.license_expiry and self.license_expiry < date.today():
            raise ValidationError("License has already expired.")

        if self.rating and not (0 <= float(self.rating) <= 5):
            raise ValidationError("Rating must be between 0.0 and 5.0.")

        if self.experience_years < 0:
            raise ValidationError("Experience years cannot be negative.")

        if self.vehicle_capacity <= 0:
            raise ValidationError("Vehicle capacity must be at least 1.")

    def save(self, *args, **kwargs):
        """Override save to normalize phone number."""
        if self.phone_number and not self.normalized_phone:
            self.normalized_phone = normalize_phone_number(self.phone_number)

        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        """Return the driver's full name."""
        if self.user and self.user.get_full_name():
            return self.user.get_full_name()
        return self.name

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
        """Update driver trip statistics.

        Args:
            amount: The amount earned from the trip
        """
        self.total_trips += 1
        self.total_earnings += amount
        self.save(update_fields=['total_trips', 'total_earnings'])

    def update_rating(self, new_rating: int) -> None:
        """Update driver's average rating.

        Args:
            new_rating: The new rating (1-5)
        """
        if not (1 <= new_rating <= 5):
            raise ValueError("Rating must be between 1 and 5")

        # Get all reviews for this driver
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


def generate_booking_reference():
    """Generate a unique booking reference."""
    timestamp = timezone.now().strftime("%Y%m%d")
    random_str = uuid.uuid4().hex[:4].upper()
    return f"SAF-{timestamp}-{random_str}"


class Booking(TimeStampedModel):
    """
    Model for bookings of transfers, excursions, or tours.
    Enhanced with better status tracking and relationships.
    """
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
    ]

    customer = models.ForeignKey(
        'Customer',
        on_delete=models.CASCADE,
        related_name='bookings',
        help_text="Customer who made the booking"
    )
    destination = models.ForeignKey(
        'Destination',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings',
        help_text="Destination for the booking"
    )
    tour = models.ForeignKey(
        'Tour',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings',
        help_text="Tour for the booking"
    )
    booking_type = models.CharField(
        max_length=20,
        choices=BOOKING_TYPE_CHOICES,
        help_text="Type of booking"
    )

    booking_reference = models.CharField(
        max_length=50,
        unique=True,
        default=generate_booking_reference,
        editable=False,
        help_text="Unique booking reference"
    )

    num_adults = models.PositiveIntegerField(
        default=1,
        help_text="Number of adult passengers"
    )
    num_children = models.PositiveIntegerField(
        default=0,
        help_text="Number of child passengers"
    )
    num_infants = models.PositiveIntegerField(
        default=0,
        help_text="Number of infant passengers"
    )
    pickup_location = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Pickup location"
    )
    dropoff_location = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Drop-off location"
    )
    travel_date = models.DateField(
        help_text="Date of travel"
    )
    travel_time = models.TimeField(
        default=timezone.now,
        help_text="Preferred pickup time"
    )
    return_date = models.DateField(
        null=True,
        blank=True,
        help_text="Return date for multi-day trips"
    )
    return_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Return time for multi-day trips"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING',
        help_text="Current status of the booking"
    )

    special_requests = models.TextField(
        blank=True,
        null=True,
        help_text="Special customer requests"
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Internal notes about the booking"
    )
    booking_date = models.DateTimeField(
        default=timezone.now,
        help_text="When the booking was made"
    )
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total price for the booking"
    )
    is_paid = models.BooleanField(
        default=False,
        help_text="Whether payment has been completed"
    )
    is_cancelled = models.BooleanField(
        default=False,
        help_text="Whether the booking has been cancelled"
    )
    cancellation_reason = models.TextField(
        blank=True,
        null=True,
        help_text="Reason for cancellation"
    )

    # Foreign keys
    driver = models.ForeignKey(
        'Driver',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings',
        help_text="Driver assigned to this booking"
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
            models.Index(fields=['customer', 'travel_date']),
        ]

    def __str__(self):
        return f"{self.booking_reference} - {self.customer} - {self.destination or self.tour}"

    def clean(self):
        """Validate model fields."""
        if self.travel_date < date.today():
            raise ValidationError("Travel date cannot be in the past.")

        if self.return_date and self.return_date < self.travel_date:
            raise ValidationError("Return date cannot be before travel date.")

        if self.num_adults < 1:
            raise ValidationError("At least one adult is required.")

        if not self.destination and not self.tour:
            raise ValidationError("Either a destination or tour must be selected.")

        if self.destination and self.tour:
            raise ValidationError("A booking cannot have both a destination and a tour.")

    def save(self, *args, **kwargs):
        """Override save to auto-calculate price and update status."""
        self.full_clean()

        # Auto-fill total price on save
        if self.destination:
            self.total_price = (self.num_adults + self.num_children) * self.destination.price_per_person
        elif self.tour:
            self.total_price = (self.num_adults + self.num_children) * self.tour.price_per_person

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
        """Cancel booking and update status.

        Args:
            reason: Reason for cancellation
        """
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
        """Assign a driver to this booking.

        Args:
            driver: The driver to assign
        """
        if not driver.available:
            raise ValueError("Driver is not available.")

        self.driver = driver
        self.save(update_fields=['driver'])

    def confirm(self):
        """Confirm the booking."""
        if self.status != 'PENDING':
            raise ValueError("Only pending bookings can be confirmed.")

        self.status = 'CONFIRMED'
        self.save(update_fields=['status'])


# =============================================================================
# TOURS
# =============================================================================
class Tour(TimeStampedModel):
    """
    Model for multi-day safaris/tours.
    Enhanced with better categorization and media handling.
    """
    CATEGORY_CHOICES = [
        ('ADVENTURE', 'Adventure Safari'),
        ('WILDLIFE', 'Wildlife Safari'),
        ('CULTURAL', 'Cultural Tour'),
        ('BEACH', 'Beach Holiday'),
        ('MOUNTAIN', 'Mountain Climbing'),
        ('CITY', 'City Tour'),
    ]

    DIFFICULTY_CHOICES = [
        ('EASY', 'Easy'),
        ('MODERATE', 'Moderate'),
        ('CHALLENGING', 'Challenging'),
        ('EXTREME', 'Extreme'),
    ]

    title = models.CharField(
        max_length=200,
        help_text="Tour title"
    )
    slug = models.SlugField(
        max_length=220,
        unique=True,
        blank=True,
        help_text="URL-friendly version of title"
    )
    tagline = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        help_text="Short catchy phrase for the tour"
    )
    description = models.TextField(
        default="No description available",
        help_text="Detailed description of the destination"
    )

    highlights = models.TextField(
        blank=True,
        null=True,
        help_text="Key highlights of the tour"
    )
    itinerary = models.TextField(
        blank=True,
        null=True,
        help_text="Day-by-day itinerary"
    )
    inclusions = models.TextField(
        blank=True,
        null=True,
        help_text="What's included in the tour"
    )
    exclusions = models.TextField(
        blank=True,
        null=True,
        help_text="What's not included in the tour"
    )

    price_per_person = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Price per person in KES"
    )
    discount_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Discounted price if applicable"
    )
    duration_days = models.PositiveIntegerField(
        default=1,
        help_text="Duration in days"
    )
    duration_nights = models.PositiveIntegerField(
        default=0,
        help_text="Number of nights for the tour"
    )
    max_group_size = models.PositiveIntegerField(
        default=10,
        help_text="Maximum number of people per tour"
    )
    min_group_size = models.PositiveIntegerField(
        default=1,
        help_text="Minimum number of people per tour"
    )
    difficulty = models.CharField(
        max_length=20,
        choices=DIFFICULTY_CHOICES,
        default='EASY',
        help_text="Difficulty level of the tour"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='WILDLIFE',
        help_text="Category of the tour"
    )
    available = models.BooleanField(
        default=True,
        help_text="Whether this tour is currently bookable"
    )
    featured = models.BooleanField(
        default=False,
        help_text="Whether to feature this tour on homepage"
    )
    is_popular = models.BooleanField(
        default=False,
        help_text="Whether this is a popular tour"
    )
    max_advance_booking_days = models.PositiveIntegerField(
        default=365,
        help_text="Maximum days in advance for booking"
    )

    # Media (Cloudinary)
    image = CloudinaryField(
        "image",
        blank=True,
        null=True,
        help_text="Primary tour image"
    )
    video = CloudinaryField(
        "video",
        resource_type="video",
        blank=True,
        null=True,
        help_text="Tour promotional video"
    )
    image_url = models.URLField(
        blank=True,
        null=True,
        help_text="External image URL as fallback"
    )
    gallery_images = models.JSONField(
        default=list,
        blank=True,
        help_text="List of additional image URLs"
    )

    # Location
    departure_point = models.CharField(
        max_length=200,
        default="Nairobi",
        help_text="Tour departure location"
    )
    destinations_visited = models.TextField(
        blank=True,
        null=True,
        help_text="List of destinations visited"
    )

    # Relations
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tours",
        help_text="User who created this tour"
    )
    is_approved = models.BooleanField(
        default=False,
        help_text="Whether the tour has been approved"
    )
    approved_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_tours",
        help_text="User who approved this tour"
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the tour was approved"
    )

    # Managers
    objects = models.Manager()
    active = ActiveManager()

    class Meta:
        verbose_name = "Tour"
        verbose_name_plural = "Tours"
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['difficulty']),
            models.Index(fields=['is_popular']),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        """Validate model fields."""
        if self.price_per_person < 0:
            raise ValidationError("Price per person cannot be negative.")

        if self.discount_price < 0:
            raise ValidationError("Discount price cannot be negative.")

        if self.discount_price > 0 and self.discount_price >= self.price_per_person:
            raise ValidationError("Discount price must be less than the regular price.")

        if self.duration_days < 1:
            raise ValidationError("Duration must be at least 1 day.")

        if self.max_group_size < self.min_group_size:
            raise ValidationError("Maximum group size cannot be less than minimum group size.")

        if self.max_advance_booking_days < 1:
            raise ValidationError("Maximum advance booking days must be at least 1.")

    def save(self, *args, **kwargs):
        """Override save to auto-generate slug and set duration nights."""
        # Auto-generate slug if not provided
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Tour.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        # Set duration nights based on duration days
        if self.duration_days > 0 and not self.duration_nights:
            self.duration_nights = self.duration_days - 1

        self.full_clean()
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
        """Approve the tour.

        Args:
            user: The user approving the tour
        """
        self.is_approved = True
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['is_approved', 'approved_by', 'approved_at'])

    def get_similar_tours(self, limit=3):
        """Get similar tours based on category and difficulty.

        Args:
            limit: Maximum number of tours to return

        Returns:
            QuerySet of similar tours
        """
        return Tour.objects.filter(
            category=self.category,
            difficulty=self.difficulty,
            is_approved=True,
            available=True
        ).exclude(pk=self.pk).order_by('-featured', '-is_popular')[:limit]


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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Payer info
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, null=True, blank=True, related_name="payments")
    customer = models.ForeignKey('Customer', on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    guest_full_name = models.CharField(max_length=200, blank=True, null=True)
    guest_email = models.EmailField(blank=True, null=True)
    guest_phone = models.CharField(max_length=20, blank=True, null=True)
    normalized_guest_phone = models.CharField(max_length=20, blank=True)

    adults = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField(default=0)
    days = models.PositiveIntegerField(default=1)

    # Booking / Tour
    booking = models.OneToOneField("Booking", on_delete=models.CASCADE, null=True, blank=True, related_name="payment")
    tour = models.ForeignKey("Tour", on_delete=models.CASCADE, null=True, blank=True, related_name="payments")
    travel_date = models.DateField(default=timezone.now)

    # Billing
    billing_line1 = models.CharField(max_length=255, default="Nairobi")
    billing_city = models.CharField(max_length=100, default="Nairobi")
    billing_state = models.CharField(max_length=100, default="Nairobi")
    billing_postal_code = models.CharField(max_length=20, default="00100")
    billing_country_code = models.CharField(max_length=3, default="KE")

    # Payment details
    provider = models.CharField(max_length=20, choices=PaymentProvider.choices, default=PaymentProvider.PAYSTACK)
    method = models.CharField(max_length=20, choices=PaymentProvider.choices, default=PaymentProvider.PAYSTACK)
    currency = models.CharField(max_length=10, default="KES")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    phone_number = models.CharField(max_length=20, blank=True, default="")
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)

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
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    refund_reason = models.TextField(blank=True, null=True)
    refunded_on = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['paystack_transaction_id']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['customer', 'status']),
        ]

    def __str__(self):
        identity = self.guest_full_name or (self.user.get_full_name() if self.user else "Guest")
        return f"{identity} - {self.amount} {self.currency} ({self.status})"

    def save(self, *args, **kwargs):
        if self.guest_phone and not self.normalized_guest_phone:
            self.normalized_guest_phone = normalize_phone_number(self.guest_phone)
        if self.status == PaymentStatus.SUCCESS:
            if not self.amount_paid:
                self.amount_paid = self.amount
            if not self.paid_on:
                self.paid_on = timezone.now()
        self.full_clean()
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
        elif self.customer:
            return self.customer.email
        elif self.user:
            return self.user.email
        return None

# =============================================================================
# CONTENT & MISC
# =============================================================================
class ContactMessage(TimeStampedModel):
    """
    Model for messages from the contact page.
    Enhanced with better tracking and status.
    """
    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    ]

    name = models.CharField(
        max_length=150,
        help_text="Name of the person sending the message"
    )
    email = models.EmailField(
        help_text="Email address of the sender"
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[validate_phone_number],
        help_text="Phone number of the sender"
    )
    subject = models.CharField(
        max_length=200,
        help_text="Subject of the message"
    )
    message = models.TextField(
        help_text="Message content"
    )
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='MEDIUM',
        help_text="Priority level of the message"
    )
    is_resolved = models.BooleanField(
        default=False,
        help_text="Whether this message has been resolved"
    )
    resolved_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_messages",
        help_text="User who resolved this message"
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the message was resolved"
    )
    assigned_to = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_messages",
        help_text="User this message is assigned to"
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
        """Mark message as resolved by the given user.

        Args:
            user: The user resolving the message
        """
        self.is_resolved = True
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.save(update_fields=['is_resolved', 'resolved_by', 'resolved_at'])

    def assign_to(self, user):
        """Assign message to a user.

        Args:
            user: The user to assign the message to
        """
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


class Video(TimeStampedModel):
    """Model for videos related to tours, destinations, etc."""
    CATEGORY_CHOICES = [
        ('DESTINATION', 'Destination Video'),
        ('TESTIMONIAL', 'Customer Testimonial'),
        ('ACTIVITY', 'Tour Activity'),
        ('PROMOTION', 'Promotional Video'),
        ('DRIVER', 'Driver Profile'),
    ]

    title = models.CharField(
        max_length=255,
        help_text="Video title"
    )
    slug = models.SlugField(
        max_length=275,
        unique=True,
        blank=True,
        help_text="URL-friendly version of title"
    )
    description = models.TextField(
        blank=True,
        help_text="Video description"
    )
    file = models.FileField(
        upload_to="videos/",
        help_text="Video file"
    )
    thumbnail = models.ImageField(
        upload_to="video_thumbnails/",
        blank=True,
        null=True,
        help_text="Video thumbnail image"
    )
    duration = models.DurationField(
        blank=True,
        null=True,
        help_text="Video duration"
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Price for paid videos"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='DESTINATION',
        help_text="Video category"
    )
    is_featured = models.BooleanField(
        default=False,
        help_text="Whether to feature this video"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this video is active"
    )
    view_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times the video has been viewed"
    )
    tags = models.CharField(
        max_length=500,
        blank=True,
        help_text="Comma-separated tags"
    )

    # Relations
    tour = models.ForeignKey(
        'Tour',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='videos',
        help_text="Tour this video is associated with"
    )
    destination = models.ForeignKey(
        'Destination',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='videos',
        help_text="Destination this video is associated with"
    )

    # Managers
    objects = models.Manager()
    active = ActiveManager()
    featured = FeaturedManager()

    class Meta:
        verbose_name = "Video"
        verbose_name_plural = "Videos"
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['is_featured']),
            models.Index(fields=['view_count']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        """Override save to auto-generate slug."""
        if not self.slug and self.title:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Video.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        """Get the absolute URL for this video."""
        return reverse('video_detail', kwargs={'slug': self.slug})

    def increment_view_count(self):
        """Increment video view count."""
        self.view_count += 1
        self.save(update_fields=['view_count'])

    @property
    def tag_list(self):
        """Return tags as a list."""
        if self.tags:
            return [tag.strip() for tag in self.tags.split(',')]
        return []

    @property
    def is_paid(self):
        """Check if this is a paid video."""
        return self.price is not None and self.price > 0

    @property
    def duration_in_minutes(self):
        """Get video duration in minutes."""
        if self.duration:
            total_seconds = self.duration.total_seconds()
            minutes = int(total_seconds // 60)
            seconds = int(total_seconds % 60)
            return f"{minutes}:{seconds:02d}"
        return None


class Trip(TimeStampedModel):
    """
    Model for trips completed by drivers.
    Enhanced with better tracking and metrics.
    """
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    driver = models.ForeignKey(
        'Driver',
        on_delete=models.CASCADE,
        related_name='trips',
        help_text="Driver who completed the trip"
    )
    booking = models.ForeignKey(
        'Booking',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='trips',
        help_text="Booking associated with this trip"
    )
    destination = models.CharField(
        max_length=200,
        help_text="Trip destination"
    )
    date = models.DateField(
        help_text="Date of the trip"
    )
    start_time = models.TimeField(
        default=timezone.now,
        help_text="Trip start time"
    )
    end_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Trip end time"
    )
    earnings = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Earnings from the trip"
    )
    distance = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Distance traveled in kilometers"
    )
    fuel_consumed = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed in liters"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='SCHEDULED',
        help_text="Current status of the trip"
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Additional notes about the trip"
    )
    customer_rating = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Customer rating (1-5)"
    )
    customer_feedback = models.TextField(
        blank=True,
        null=True,
        help_text="Customer feedback about the trip"
    )

    class Meta:
        verbose_name = "Trip"
        verbose_name_plural = "Trips"
        indexes = [
            models.Index(fields=['driver', 'date']),
            models.Index(fields=['status']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"{self.destination} ({self.status}) - {self.driver.name}"

    def clean(self):
        """Validate model fields."""
        if self.earnings < 0:
            raise ValidationError("Earnings cannot be negative.")

        if self.distance and self.distance < 0:
            raise ValidationError("Distance cannot be negative.")

        if self.fuel_consumed and self.fuel_consumed < 0:
            raise ValidationError("Fuel consumed cannot be negative.")

        if self.customer_rating and not (1 <= self.customer_rating <= 5):
            raise ValidationError("Customer rating must be between 1 and 5.")

        if self.end_time and self.end_time < self.start_time:
            # Handle overnight trips
            if self.end_time < self.start_time:
                # This is valid for trips that span midnight
                pass

    def save(self, *args, **kwargs):
        """Override save to validate."""
        self.full_clean()
        super().save(*args, **kwargs)

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
        """Mark trip as completed with optional details.

        Args:
            end_time: End time of the trip
            distance: Distance traveled in km
            fuel: Fuel consumed in liters
        """
        self.status = 'COMPLETED'
        if end_time:
            self.end_time = end_time
        if distance:
            self.distance = distance
        if fuel:
            self.fuel_consumed = fuel
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
        """Cancel the trip.

        Args:
            reason: Reason for cancellation
        """
        if self.status == 'COMPLETED':
            raise ValueError("Cannot cancel a completed trip.")

        self.status = 'CANCELLED'
        if reason:
            self.notes = f"{self.notes}\n\nCancellation reason: {reason}" if self.notes else f"Cancellation reason: {reason}"
        self.save()


# =============================================================================
# REVIEW MODELS
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

    customer = models.ForeignKey(
        'Customer',
        on_delete=models.CASCADE,
        related_name='reviews',
        help_text="Customer who wrote the review"
    )
    tour = models.ForeignKey(
        'Tour',
        on_delete=models.CASCADE,
        related_name='reviews',
        null=True,
        blank=True,
        help_text="Tour being reviewed"
    )
    driver = models.ForeignKey(
        'Driver',
        on_delete=models.CASCADE,
        related_name='reviews',
        null=True,
        blank=True,
        help_text="Driver being reviewed"
    )
    booking = models.ForeignKey(
        'Booking',
        on_delete=models.CASCADE,
        related_name='reviews',
        help_text="Booking associated with this review"
    )
    rating = models.PositiveIntegerField(
        choices=RATING_CHOICES,
        help_text="Rating given (1-5)"
    )
    title = models.CharField(
        max_length=200,
        help_text="Review title"
    )
    comment = models.TextField(
        help_text="Review comment"
    )
    is_public = models.BooleanField(
        default=True,
        help_text="Whether this review is public"
    )
    is_verified = models.BooleanField(
        default=False,
        help_text="Review has been verified as genuine"
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the review was verified"
    )

    class Meta:
        verbose_name = "Review"
        verbose_name_plural = "Reviews"
        unique_together = ['customer', 'booking']  # One review per booking
        indexes = [
            models.Index(fields=['rating']),
            models.Index(fields=['is_public']),
            models.Index(fields=['is_verified']),
            models.Index(fields=['tour', 'rating']),
            models.Index(fields=['driver', 'rating']),
        ]

    def __str__(self):
        return f"Review by {self.customer} - {self.rating}/5"

    def clean(self):
        """Validate model fields."""
        if not self.tour and not self.driver:
            raise ValidationError("A review must be associated with either a tour or a driver.")

        if self.tour and self.driver:
            raise ValidationError("A review cannot be associated with both a tour and a driver.")

        if self.rating and not (1 <= self.rating <= 5):
            raise ValidationError("Rating must be between 1 and 5.")

    def save(self, *args, **kwargs):
        """Override save to validate."""
        self.full_clean()
        super().save(*args, **kwargs)

    def verify(self):
        """Mark review as verified."""
        self.is_verified = True
        self.verified_at = timezone.now()
        self.save(update_fields=['is_verified', 'verified_at'])

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