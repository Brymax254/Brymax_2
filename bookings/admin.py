# bookings/admin.py
from django.urls import reverse, path
from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.db.models import Count, Sum, Avg, Q
from django.utils import timezone
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.contrib.admin import SimpleListFilter
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import timedelta
import json

from .models import (
    BookingCustomer, Driver, Vehicle, Destination, TourCategory, Tour,
    Booking, Trip, Payment, PaymentProvider, PaymentStatus
)


# =============================================================================
# CUSTOM FILTERS
# =============================================================================

class DriverStatusFilter(SimpleListFilter):
    title = 'driver status'
    parameter_name = 'driver_status'

    def lookups(self, request, model_admin):
        return (
            ('available', 'Available'),
            ('unavailable', 'Unavailable'),
            ('verified', 'Verified'),
            ('unverified', 'Unverified'),
            ('license_expiring', 'License Expiring Soon'),
            ('license_expired', 'License Expired'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'available':
            return queryset.filter(available=True)
        elif self.value() == 'unavailable':
            return queryset.filter(available=False)
        elif self.value() == 'verified':
            return queryset.filter(is_verified=True)
        elif self.value() == 'unverified':
            return queryset.filter(is_verified=False)
        elif self.value() == 'license_expiring':
            thirty_days_from_now = timezone.now().date() + timedelta(days=30)
            return queryset.filter(
                license_expiry__lte=thirty_days_from_now,
                license_expiry__gte=timezone.now().date()
            )
        elif self.value() == 'license_expired':
            return queryset.filter(license_expiry__lt=timezone.now().date())
        return queryset


class BookingStatusFilter(SimpleListFilter):
    title = 'booking status'
    parameter_name = 'booking_status'

    def lookups(self, request, model_admin):
        return (
            ('pending', 'Pending'),
            ('confirmed', 'Confirmed'),
            ('cancelled', 'Cancelled'),
            ('completed', 'Completed'),
            ('upcoming', 'Upcoming'),
            ('past', 'Past'),
            ('today', 'Today'),
            ('unpaid', 'Unpaid'),
        )

    def queryset(self, request, queryset):
        today = timezone.now().date()
        if self.value() == 'pending':
            return queryset.filter(status='PENDING')
        elif self.value() == 'confirmed':
            return queryset.filter(status='CONFIRMED')
        elif self.value() == 'cancelled':
            return queryset.filter(status='CANCELLED')
        elif self.value() == 'completed':
            return queryset.filter(status='COMPLETED')
        elif self.value() == 'upcoming':
            return queryset.filter(travel_date__gte=today)
        elif self.value() == 'past':
            return queryset.filter(travel_date__lt=today)
        elif self.value() == 'today':
            return queryset.filter(travel_date=today)
        elif self.value() == 'unpaid':
            return queryset.filter(is_paid=False)
        return queryset


class PaymentStatusFilter(SimpleListFilter):
    title = 'payment status'
    parameter_name = 'payment_status'

    def lookups(self, request, model_admin):
        return (
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('success', 'Successful'),
            ('failed', 'Failed'),
            ('refunded', 'Refunded'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'pending':
            return queryset.filter(status='PENDING')
        elif self.value() == 'processing':
            return queryset.filter(status='PROCESSING')
        elif self.value() == 'success':
            return queryset.filter(status='SUCCESS')
        elif self.value() == 'failed':
            return queryset.filter(status='FAILED')
        elif self.value() == 'refunded':
            return queryset.filter(status__in=['REFUNDED', 'PARTIAL_REFUND'])
        return queryset


# =============================================================================
# INLINE ADMIN CLASSES
# =============================================================================

class TripInline(admin.TabularInline):
    model = Trip
    extra = 0
    fields = ('date', 'start_time', 'end_time', 'status', 'earnings', 'distance', 'fuel_consumed')
    readonly_fields = ('date', 'start_time', 'end_time', 'status', 'earnings', 'distance', 'fuel_consumed')
    can_delete = False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ('amount', 'currency', 'provider', 'status', 'transaction_id', 'payment_actions')
    readonly_fields = ('amount', 'currency', 'provider', 'status', 'transaction_id', 'payment_actions')
    can_delete = False

    def payment_actions(self, obj):
        if obj.status == 'PENDING':
            return format_html(
                '<a class="button" href="{}?action=mark_successful">Mark Successful</a> | '
                '<a class="button" href="{}?action=mark_failed">Mark Failed</a>',
                reverse('admin:payment_action', args=[obj.pk]),
                reverse('admin:payment_action', args=[obj.pk])
            )
        elif obj.status == 'SUCCESS' and not obj.is_refunded:
            return format_html(
                '<a class="button" href="{}?action=initiate_refund">Initiate Refund</a>',
                reverse('admin:payment_action', args=[obj.pk])
            )
        return "No actions available"

    payment_actions.short_description = 'Actions'


class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0
    fields = ('booking_reference', 'travel_date', 'status', 'total_price', 'is_paid', 'booking_actions')
    readonly_fields = ('booking_reference', 'travel_date', 'status', 'total_price', 'is_paid', 'booking_actions')
    can_delete = False

    def booking_actions(self, obj):
        if obj.status == 'PENDING':
            return format_html(
                '<a class="button" href="{}?action=confirm">Confirm</a> | '
                '<a class="button" href="{}?action=cancel">Cancel</a>',
                reverse('admin:booking_action', args=[obj.pk]),
                reverse('admin:booking_action', args=[obj.pk])
            )
        elif obj.status == 'CONFIRMED' and obj.is_upcoming:
            return format_html(
                '<a class="button" href="{}?action=cancel">Cancel</a>',
                reverse('admin:booking_action', args=[obj.pk])
            )
        return "No actions available"

    booking_actions.short_description = 'Actions'


# =============================================================================
# MODEL ADMIN CLASSES
# =============================================================================

@admin.register(BookingCustomer)
class BookingCustomerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'normalized_phone', 'adults', 'children', 'travel_date', 'total_bookings',
                    'total_spent')
    list_filter = ('travel_date', 'adults', 'children')
    search_fields = ('full_name', 'email', 'normalized_phone')
    ordering = ('-travel_date',)
    readonly_fields = ('normalized_phone', 'total_bookings', 'total_spent')

    fieldsets = (
        ('Customer Information', {
            'fields': ('full_name', 'email', 'phone_number', 'country_code', 'normalized_phone')
        }),
        ('Travel Details', {
            'fields': ('adults', 'children', 'travel_date', 'days')
        }),
        ('Statistics', {
            'fields': ('total_bookings', 'total_spent'),
            'classes': ('collapse',)
        }),
    )

    def total_bookings(self, obj):
        return obj.bookings.count()

    total_bookings.short_description = 'Total Bookings'

    def total_spent(self, obj):
        total = obj.bookings.aggregate(total=Sum('total_price'))['total'] or 0
        return f"{total} KES"

    total_spent.short_description = 'Total Spent'

@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = (
        'full_name', 'normalized_phone', 'license_number', 'rating',
        'available', 'is_verified', 'license_status_badge', 'driver_actions'
    )
    list_filter = (DriverStatusFilter, 'gender', 'license_type')
    search_fields = (
        'user__username', 'user__first_name', 'user__last_name',
        'normalized_phone', 'license_number'
    )
    readonly_fields = (
        'normalized_phone', 'rating', 'total_trips', 'total_earnings',
        'license_status_badge', 'age'
    )
    actions = [
        'verify_drivers', 'unverify_drivers',
        'make_available', 'make_unavailable', 'send_verification_reminder'
    ]
    inlines = [TripInline]

    fieldsets = (
        ('User Information', {
            'fields': (
                'user', 'phone_number', 'normalized_phone', 'gender',
                'date_of_birth', 'age', 'nationality'
            )
        }),
        ('Profile', {
            'fields': ('profile_picture', 'bio', 'preferred_language', 'communication_preferences')
        }),
        ('Driver Details', {
            'fields': (
                'license_number', 'license_type', 'license_expiry',
                'license_status_badge', 'available', 'experience_years'
            )
        }),
        ('Statistics', {
            'fields': ('rating', 'total_trips', 'total_earnings'),
            'classes': ('collapse',)
        }),
        ('Documents', {
            'fields': ('verification_document', 'driver_license_copy', 'police_clearance')
        }),
        ('Bank Details', {
            'fields': ('bank_name', 'bank_account', 'bank_branch', 'payment_methods')
        }),
        ('Vehicle', {
            'fields': ('vehicle',)
        }),
        ('Verification', {
            'fields': ('is_verified', 'driver_actions'),
            'classes': ('collapse',)
        }),
    )

    # ===== Custom Display Fields =====

    def license_status_badge(self, obj):
        """Show expiry status with color-coded badge."""
        if not obj.license_expiry:
            return format_html('<span style="color: orange;">Unknown</span>')

        days_until_expiry = (obj.license_expiry - timezone.now().date()).days
        if days_until_expiry < 0:
            return format_html('<span style="color: red; font-weight: bold;">Expired</span>')
        elif days_until_expiry < 30:
            return format_html(
                '<span style="color: orange; font-weight: bold;">Expiring in {} days</span>',
                days_until_expiry
            )
        return format_html('<span style="color: green;">Valid</span>')

    license_status_badge.short_description = 'License Status'

    def age(self, obj):
        """Calculate age from date of birth."""
        if obj.date_of_birth:
            today = timezone.now().date()
            return (
                today.year - obj.date_of_birth.year
                - ((today.month, today.day) < (obj.date_of_birth.month, obj.date_of_birth.day))
            )
        return "N/A"

    age.short_description = 'Age'

    # ===== Custom Action Buttons (Verify / Unverify) =====

    def driver_actions(self, obj):
        """Add Verify/Unverify buttons in admin list."""
        url = reverse('admin:driver_action', args=[obj.pk])
        if not obj.is_verified:
            return format_html(
                '<a class="button" style="background:#28a745;color:white;padding:5px 10px;'
                'border-radius:6px;text-decoration:none;" href="{}?action=verify" '
                'onclick="setTimeout(()=>location.reload(),1500)">✅ Verify</a>',
                url
            )
        else:
            return format_html(
                '<a class="button" style="background:#dc3545;color:white;padding:5px 10px;'
                'border-radius:6px;text-decoration:none;" href="{}?action=unverify" '
                'onclick="setTimeout(()=>location.reload(),1500)">🚫 Unverify</a>',
                url
            )

    driver_actions.short_description = 'Actions'

    # ===== Bulk Actions =====

    def verify_drivers(self, request, queryset):
        count = queryset.update(is_verified=True)
        self.message_user(request, f"✅ {count} drivers have been verified.", messages.SUCCESS)

    verify_drivers.short_description = "Verify selected drivers"

    def unverify_drivers(self, request, queryset):
        count = queryset.update(is_verified=False)
        self.message_user(request, f"🚫 {count} drivers have been unverified.", messages.WARNING)

    unverify_drivers.short_description = "Unverify selected drivers"

    def make_available(self, request, queryset):
        count = queryset.update(available=True)
        self.message_user(request, f"🟢 {count} drivers are now available.", messages.SUCCESS)

    make_available.short_description = "Make selected drivers available"

    def make_unavailable(self, request, queryset):
        count = queryset.update(available=False)
        self.message_user(request, f"🔴 {count} drivers are now unavailable.", messages.WARNING)

    make_unavailable.short_description = "Make selected drivers unavailable"

    def send_verification_reminder(self, request, queryset):
        count = queryset.count()
        self.message_user(request, f"📩 Verification reminders sent to {count} drivers.", messages.INFO)

    send_verification_reminder.short_description = "Send verification reminder"
@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        'full_name', 'license_plate', 'vehicle_type', 'fuel_type',
        'capacity', 'is_active', 'documents_status_badge', 'image_preview'
    )
    list_filter = ('vehicle_type', 'fuel_type', 'is_active')
    search_fields = ('make', 'model', 'license_plate')
    readonly_fields = (
        'vehicle_age', 'documents_valid', 'insurance_status', 'inspection_status',
        'documents_status_badge', 'image_preview'
    )
    actions = ['activate_vehicles', 'deactivate_vehicles', 'send_inspection_reminder']

    fieldsets = (
        ('Basic Information', {
            'fields': (
                'make', 'model', 'year', 'color',
                'license_plate', 'vehicle_type', 'fuel_type', 'capacity'
            )
        }),
        ('Images', {
            'fields': ('image', 'external_image_url', 'image_preview'),  # ✅ replaced image_url with preview
        }),
        ('Features', {
            'fields': ('features', 'accessibility_features')
        }),
        ('Documents', {
            'fields': ('logbook_copy', 'insurance_copy', 'inspection_certificate')
        }),
        ('Status', {
            'fields': ('insurance_expiry', 'inspection_expiry', 'is_active', 'documents_status_badge')
        }),
        ('Sustainability', {
            'fields': ('carbon_footprint_per_km',)
        }),
        ('Computed Fields', {
            'fields': ('vehicle_age', 'documents_valid', 'insurance_status', 'inspection_status'),
            'classes': ('collapse',)
        }),
    )

    inlines = [TripInline]

    # ==========================
    # 🖼️ Image Preview
    # ==========================
    def image_preview(self, obj):
        """Display a small preview of the uploaded image or external image URL."""
        if getattr(obj, 'image', None):
            return format_html(
                '<img src="{}" style="max-height:150px; border-radius:10px; box-shadow:0 2px 4px rgba(0,0,0,0.3);" />',
                obj.image.url
            )
        elif getattr(obj, 'external_image_url', None):
            return format_html(
                '<img src="{}" style="max-height:150px; border-radius:10px; opacity:0.9;" />',
                obj.external_image_url
            )
        return format_html('<span style="color:gray;">No image available</span>')

    image_preview.short_description = "Image Preview"

    # ==========================
    # 📄 Document Badge
    # ==========================
    def documents_status_badge(self, obj):
        """Show colored badge based on document validity."""
        if not obj.insurance_expiry or not obj.inspection_expiry:
            return format_html('<span style="color: orange;">Unknown</span>')

        today = timezone.now().date()
        insurance_valid = obj.insurance_expiry > today
        inspection_valid = obj.inspection_expiry > today

        if insurance_valid and inspection_valid:
            return format_html('<span style="color: green; font-weight: bold;">Valid</span>')
        else:
            return format_html('<span style="color: red; font-weight: bold;">Expired</span>')

    documents_status_badge.short_description = 'Documents Status'

    # ==========================
    # ⚙️ Custom Actions
    # ==========================
    def activate_vehicles(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} vehicles have been activated.", messages.SUCCESS)

    activate_vehicles.short_description = "Activate selected vehicles"

    def deactivate_vehicles(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} vehicles have been deactivated.", messages.WARNING)

    deactivate_vehicles.short_description = "Deactivate selected vehicles"

    def send_inspection_reminder(self, request, queryset):
        # In a real implementation, this would send an email or SMS
        count = queryset.count()
        self.message_user(request, f"Inspection reminders sent for {count} vehicles.", messages.INFO)

    send_inspection_reminder.short_description = "Send inspection reminder"


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ('name', 'destination_type', 'price_per_person', 'currency', 'is_active', 'is_featured',
                    'image_thumbnail')
    list_filter = ('destination_type', 'is_active', 'is_featured', 'eco_friendly')
    search_fields = ('name', 'description', 'location')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('get_absolute_url', 'primary_image', 'image_thumbnail')
    actions = ['activate_destinations', 'deactivate_destinations', 'feature_destinations', 'unfeature_destinations']

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'destination_type')
        }),
        ('Pricing', {
            'fields': ('price_per_person', 'currency')
        }),
        ('Status', {
            'fields': ('is_active', 'is_featured')
        }),
        ('Media', {
            'fields': ('image', 'video', 'image_url', 'gallery_images', 'primary_image', 'image_thumbnail')
        }),
        ('Location', {
            'fields': ('location', 'latitude', 'longitude')
        }),
        ('Sustainability', {
            'fields': ('eco_friendly', 'carbon_footprint_per_visit', 'sustainability_certifications')
        }),
        ('Accessibility', {
            'fields': ('wheelchair_accessible', 'accessibility_features')
        }),
        ('Health & Safety', {
            'fields': ('health_safety_measures', 'covid19_protocols')
        }),
        ('URL', {
            'fields': ('get_absolute_url',),
            'classes': ('collapse',)
        }),
    )
    inlines = [BookingInline]

    def image_thumbnail(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="100" height="100" />', obj.image.url)
        elif obj.image_url:
            return format_html('<img src="{}" width="100" height="100" />', obj.image_url)
        return "No image"

    image_thumbnail.short_description = 'Image'

    # Custom actions
    def activate_destinations(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} destinations have been activated.", messages.SUCCESS)

    activate_destinations.short_description = "Activate selected destinations"

    def deactivate_destinations(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} destinations have been deactivated.", messages.WARNING)

    deactivate_destinations.short_description = "Deactivate selected destinations"

    def feature_destinations(self, request, queryset):
        count = queryset.update(is_featured=True)
        self.message_user(request, f"{count} destinations have been featured.", messages.SUCCESS)

    feature_destinations.short_description = "Feature selected destinations"

    def unfeature_destinations(self, request, queryset):
        count = queryset.update(is_featured=False)
        self.message_user(request, f"{count} destinations have been unfeatured.", messages.INFO)

    unfeature_destinations.short_description = "Unfeature selected destinations"


@admin.register(TourCategory)
class TourCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'tour_count')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('tour_count',)
    actions = ['activate_categories', 'deactivate_categories']

    def tour_count(self, obj):
        return obj.tours.count()

    tour_count.short_description = 'Number of Tours'

    # Custom actions
    def activate_categories(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} categories have been activated.", messages.SUCCESS)

    activate_categories.short_description = "Activate selected categories"

    def deactivate_categories(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} categories have been deactivated.", messages.WARNING)

    deactivate_categories.short_description = "Deactivate selected categories"


@admin.register(Tour)
class TourAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'duration_days', 'price_per_person', 'available', 'is_approved', 'featured',
                    'image_thumbnail')
    list_filter = ('category', 'difficulty', 'available', 'is_approved', 'featured', 'is_popular', 'eco_friendly')
    search_fields = ('title', 'description', 'tagline')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('get_absolute_url', 'current_price', 'total_duration', 'discount_percentage', 'image_thumbnail')
    actions = ['approve_tours', 'unapprove_tours', 'feature_tours', 'unfeature_tours', 'make_popular', 'make_unpopular']

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'slug', 'tagline', 'description')
        }),
        ('Itinerary', {
            'fields': ('highlights', 'itinerary', 'inclusions', 'exclusions')
        }),
        ('Pricing', {
            'fields': ('price_per_person', 'discount_price', 'currency', 'current_price', 'discount_percentage')
        }),
        ('Duration', {
            'fields': ('duration_days', 'duration_nights', 'total_duration')
        }),
        ('Group Size', {
            'fields': ('min_group_size', 'max_group_size')
        }),
        ('Details', {
            'fields': ('difficulty', 'category', 'departure_point', 'destinations_visited')
        }),
        ('Status', {
            'fields': ('available', 'featured', 'is_popular', 'max_advance_booking_days')
        }),
        ('Media', {
            'fields': ('image', 'video', 'image_url', 'gallery_images', 'image_thumbnail')
        }),
        ('Sustainability', {
            'fields': ('eco_friendly', 'carbon_footprint_per_person', 'sustainability_certifications')
        }),
        ('Accessibility', {
            'fields': ('wheelchair_accessible', 'accessibility_features')
        }),
        ('Health & Safety', {
            'fields': ('health_safety_measures', 'covid19_protocols')
        }),
        ('Approval', {
            'fields': ('is_approved', 'approved_by', 'approved_at')
        }),
        ('URL', {
            'fields': ('get_absolute_url',),
            'classes': ('collapse',)
        }),
    )
    inlines = [BookingInline]

    def image_thumbnail(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="100" height="100" />', obj.image.url)
        elif obj.image_url:
            return format_html('<img src="{}" width="100" height="100" />', obj.image_url)
        return "No image"

    image_thumbnail.short_description = 'Image'

    # Custom actions
    def approve_tours(self, request, queryset):
        count = 0
        for tour in queryset:
            tour.approve(request.user)
            count += 1
        self.message_user(request, f"{count} tours have been approved.", messages.SUCCESS)

    approve_tours.short_description = "Approve selected tours"

    def unapprove_tours(self, request, queryset):
        count = queryset.update(is_approved=False)
        self.message_user(request, f"{count} tours have been unapproved.", messages.WARNING)

    unapprove_tours.short_description = "Unapprove selected tours"

    def feature_tours(self, request, queryset):
        count = queryset.update(featured=True)
        self.message_user(request, f"{count} tours have been featured.", messages.SUCCESS)

    feature_tours.short_description = "Feature selected tours"

    def unfeature_tours(self, request, queryset):
        count = queryset.update(featured=False)
        self.message_user(request, f"{count} tours have been unfeatured.", messages.INFO)

    unfeature_tours.short_description = "Unfeature selected tours"

    def make_popular(self, request, queryset):
        count = queryset.update(is_popular=True)
        self.message_user(request, f"{count} tours have been marked as popular.", messages.SUCCESS)

    make_popular.short_description = "Mark selected tours as popular"

    def make_unpopular(self, request, queryset):
        count = queryset.update(is_popular=False)
        self.message_user(request, f"{count} tours have been unmarked as popular.", messages.INFO)

    make_unpopular.short_description = "Unmark selected tours as popular"


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('booking_reference', 'service_name', 'booking_customer', 'travel_date', 'status', 'total_price',
                    'is_paid', 'booking_actions')
    list_filter = (BookingStatusFilter, 'booking_type', 'is_cancelled', 'travel_date')
    search_fields = ('booking_reference', 'booking_customer__full_name', 'booking_customer__email')
    readonly_fields = ('booking_reference', 'total_passengers', 'is_upcoming', 'is_past', 'is_today',
                       'can_be_cancelled', 'service_name', 'booking_actions')
    actions = ['confirm_bookings', 'cancel_bookings', 'mark_as_paid', 'mark_as_unpaid', 'assign_drivers']

    fieldsets = (
        ('Booking Information', {
            'fields': ('booking_reference', 'booking_type', 'status', 'is_cancelled', 'cancellation_reason',
                       'booking_actions')
        }),
        ('Customer', {
            'fields': ('booking_customer',)
        }),
        ('Service', {
            'fields': ('destination', 'tour', 'service_name')
        }),
        ('Passengers', {
            'fields': ('num_adults', 'num_children', 'num_infants', 'total_passengers')
        }),
        ('Locations', {
            'fields': ('pickup_location', 'pickup_latitude', 'pickup_longitude',
                       'dropoff_location', 'dropoff_latitude', 'dropoff_longitude')
        }),
        ('Dates', {
            'fields': ('travel_date', 'travel_time', 'return_date', 'return_time',
                       'is_upcoming', 'is_past', 'is_today')
        }),
        ('Pricing', {
            'fields': ('total_price', 'currency', 'is_paid')
        }),
        ('Carbon Offset', {
            'fields': ('carbon_offset_option', 'carbon_offset_amount')
        }),
        ('Driver & Vehicle', {
            'fields': ('driver', 'vehicle')
        }),
        ('Additional Information', {
            'fields': ('special_requests', 'notes', 'booking_date')
        }),
        ('Status Flags', {
            'fields': ('can_be_cancelled',),
            'classes': ('collapse',)
        }),
    )
    inlines = [PaymentInline, TripInline]

    def booking_actions(self, obj):
        if obj.status == 'PENDING':
            return format_html(
                '<a class="button" href="{}?action=confirm">Confirm</a> | '
                '<a class="button" href="{}?action=cancel">Cancel</a>',
                reverse('admin:booking_action', args=[obj.pk]),
                reverse('admin:booking_action', args=[obj.pk])
            )
        elif obj.status == 'CONFIRMED' and obj.is_upcoming:
            return format_html(
                '<a class="button" href="{}?action=cancel">Cancel</a>',
                reverse('admin:booking_action', args=[obj.pk])
            )
        return "No actions available"

    booking_actions.short_description = 'Actions'

    # Custom actions
    def confirm_bookings(self, request, queryset):
        count = 0
        for booking in queryset:
            if booking.status == 'PENDING':
                booking.confirm()
                count += 1
        self.message_user(request, f"{count} bookings have been confirmed.", messages.SUCCESS)

    confirm_bookings.short_description = "Confirm selected bookings"

    def cancel_bookings(self, request, queryset):
        count = 0
        for booking in queryset:
            if booking.can_be_cancelled:
                booking.cancel(reason="Cancelled by admin")
                count += 1
        self.message_user(request, f"{count} bookings have been cancelled.", messages.WARNING)

    cancel_bookings.short_description = "Cancel selected bookings"

    def mark_as_paid(self, request, queryset):
        count = queryset.update(is_paid=True)
        self.message_user(request, f"{count} bookings have been marked as paid.", messages.SUCCESS)

    mark_as_paid.short_description = "Mark selected bookings as paid"

    def mark_as_unpaid(self, request, queryset):
        count = queryset.update(is_paid=False)
        self.message_user(request, f"{count} bookings have been marked as unpaid.", messages.WARNING)

    mark_as_unpaid.short_description = "Mark selected bookings as unpaid"

    def assign_drivers(self, request, queryset):
        # This would typically redirect to a custom view for driver assignment
        self.message_user(request, "Please use the individual booking pages to assign drivers.", messages.INFO)

    assign_drivers.short_description = "Assign drivers to selected bookings"


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ('destination', 'driver', 'vehicle', 'date', 'status', 'earnings', 'trip_actions')
    list_filter = ('status', 'date', 'driver')
    search_fields = ('destination', 'driver__user__username', 'driver__user__first_name', 'driver__user__last_name')
    readonly_fields = ('duration', 'fuel_efficiency', 'trip_actions')
    actions = ['start_trips', 'complete_trips', 'cancel_trips']

    fieldsets = (
        ('Trip Information', {
            'fields': ('driver', 'booking', 'vehicle', 'destination', 'status', 'trip_actions')
        }),
        ('Schedule', {
            'fields': ('date', 'start_time', 'end_time', 'duration')
        }),
        ('Metrics', {
            'fields': ('earnings', 'distance', 'fuel_consumed', 'carbon_emissions', 'fuel_efficiency')
        }),
        ('Feedback', {
            'fields': ('customer_rating', 'customer_feedback')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
    )

    def trip_actions(self, obj):
        if obj.status == 'SCHEDULED':
            return format_html(
                '<a class="button" href="{}?action=start">Start Trip</a> | '
                '<a class="button" href="{}?action=cancel">Cancel Trip</a>',
                reverse('admin:trip_action', args=[obj.pk]),
                reverse('admin:trip_action', args=[obj.pk])
            )
        elif obj.status == 'IN_PROGRESS':
            return format_html(
                '<a class="button" href="{}?action=complete">Complete Trip</a>',
                reverse('admin:trip_action', args=[obj.pk])
            )
        return "No actions available"

    trip_actions.short_description = 'Actions'

    # Custom actions
    def start_trips(self, request, queryset):
        count = 0
        for trip in queryset:
            if trip.status == 'SCHEDULED':
                trip.start()
                count += 1
        self.message_user(request, f"{count} trips have been started.", messages.SUCCESS)

    start_trips.short_description = "Start selected trips"

    def complete_trips(self, request, queryset):
        count = 0
        for trip in queryset:
            if trip.status == 'IN_PROGRESS':
                trip.complete()
                count += 1
        self.message_user(request, f"{count} trips have been completed.", messages.SUCCESS)

    complete_trips.short_description = "Mark selected trips as completed"

    def cancel_trips(self, request, queryset):
        count = 0
        for trip in queryset:
            if trip.status in ['SCHEDULED', 'IN_PROGRESS']:
                trip.cancel(reason="Cancelled by admin")
                count += 1
        self.message_user(request, f"{count} trips have been cancelled.", messages.WARNING)

    cancel_trips.short_description = "Cancel selected trips"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('booking', 'amount', 'currency', 'provider', 'status', 'transaction_id', 'payment_actions')
    list_filter = (PaymentStatusFilter, 'provider', 'currency')
    search_fields = ('transaction_id', 'booking__booking_reference', 'booking__booking_customer__email')
    readonly_fields = ('created_at', 'updated_at', 'payment_actions')
    actions = ['mark_successful', 'mark_failed', 'initiate_refunds']

    fieldsets = (
        ('Payment Information', {
            'fields': ('booking', 'amount', 'currency', 'provider', 'status', 'payment_actions')
        }),
        ('Transaction Details', {
            'fields': ('transaction_id', 'provider_response')
        }),
        ('Refund Information', {
            'fields': ('refund_amount', 'refund_reason', 'refund_transaction_id', 'refund_date')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def payment_actions(self, obj):
        if obj.status == 'PENDING':
            return format_html(
                '<a class="button" href="{}?action=mark_successful">Mark Successful</a> | '
                '<a class="button" href="{}?action=mark_failed">Mark Failed</a>',
                reverse('admin:payment_action', args=[obj.pk]),
                reverse('admin:payment_action', args=[obj.pk])
            )
        elif obj.status == 'SUCCESS' and not obj.is_refunded:
            return format_html(
                '<a class="button" href="{}?action=initiate_refund">Initiate Refund</a>',
                reverse('admin:payment_action', args=[obj.pk])
            )
        return "No actions available"

    payment_actions.short_description = 'Actions'

    # Custom actions
    def mark_successful(self, request, queryset):
        count = 0
        for payment in queryset:
            if payment.status == 'PENDING':
                payment.mark_successful()
                count += 1
        self.message_user(request, f"{count} payments have been marked as successful.", messages.SUCCESS)

    mark_successful.short_description = "Mark selected payments as successful"

    def mark_failed(self, request, queryset):
        count = 0
        for payment in queryset:
            if payment.status == 'PENDING':
                payment.mark_failed()
                count += 1
        self.message_user(request, f"{count} payments have been marked as failed.", messages.WARNING)

    mark_failed.short_description = "Mark selected payments as failed"

    def initiate_refunds(self, request, queryset):
        count = 0
        for payment in queryset:
            if payment.is_successful and not payment.is_refunded:
                payment.initiate_refund(reason="Refunded by admin")
                count += 1
        self.message_user(request, f"Refunds initiated for {count} payments.", messages.INFO)

    initiate_refunds.short_description = "Initiate refunds for selected payments"


# =============================================================================
# ADMIN CUSTOMIZATION
# =============================================================================

admin.site.site_header = "Safari Bookings Administration"
admin.site.site_title = "Safari Bookings Admin"
admin.site.index_title = "Welcome to Safari Bookings Administration"

# =============================================================================
# CUSTOM ADMIN VIEWS
# =============================================================================

# These views handle the custom actions from the inline admin forms.
# They are now registered with the default admin site.

def driver_action_view(request, driver_id):
    driver = Driver.objects.get(pk=driver_id)
    action = request.GET.get('action')

    if action == 'verify':
        driver.is_verified = True
        driver.save()
        messages.success(request, f"Driver {driver.full_name} has been verified.")
    elif action == 'unverify':
        driver.is_verified = False
        driver.save()
        messages.warning(request, f"Driver {driver.full_name} has been unverified.")

    return HttpResponseRedirect(reverse('admin:bookings_driver_change', args=[driver_id]))


def booking_action_view(request, booking_id):
    booking = Booking.objects.get(pk=booking_id)
    action = request.GET.get('action')

    if action == 'confirm':
        booking.confirm()
        messages.success(request, f"Booking {booking.booking_reference} has been confirmed.")
    elif action == 'cancel':
        booking.cancel(reason="Cancelled by admin")
        messages.warning(request, f"Booking {booking.booking_reference} has been cancelled.")

    return HttpResponseRedirect(reverse('admin:bookings_booking_change', args=[booking_id]))


def trip_action_view(request, trip_id):
    trip = Trip.objects.get(pk=trip_id)
    action = request.GET.get('action')

    if action == 'start':
        trip.start()
        messages.success(request, f"Trip to {trip.destination} has been started.")
    elif action == 'complete':
        trip.complete()
        messages.success(request, f"Trip to {trip.destination} has been completed.")
    elif action == 'cancel':
        trip.cancel(reason="Cancelled by admin")
        messages.warning(request, f"Trip to {trip.destination} has been cancelled.")

    return HttpResponseRedirect(reverse('admin:bookings_trip_change', args=[trip_id]))


def payment_action_view(request, payment_id):
    payment = Payment.objects.get(pk=payment_id)
    action = request.GET.get('action')

    if action == 'mark_successful':
        payment.mark_successful()
        messages.success(request, f"Payment {payment.id} has been marked as successful.")
    elif action == 'mark_failed':
        payment.mark_failed()
        messages.warning(request, f"Payment {payment.id} has been marked as failed.")
    elif action == 'initiate_refund':
        payment.initiate_refund(reason="Refunded by admin")
        messages.info(request, f"Refund initiated for payment {payment.id}.")

    return HttpResponseRedirect(reverse('admin:bookings_payment_change', args=[payment_id]))


def dashboard_view(request):
    # Calculate statistics
    total_bookings = Booking.objects.count()
    pending_bookings = Booking.objects.filter(status='PENDING').count()
    confirmed_bookings = Booking.objects.filter(status='CONFIRMED').count()
    completed_bookings = Booking.objects.filter(status='COMPLETED').count()

    total_revenue = Booking.objects.aggregate(total=Sum('total_price'))['total'] or 0
    pending_revenue = Booking.objects.filter(status='PENDING').aggregate(total=Sum('total_price'))['total'] or 0

    total_drivers = Driver.objects.count()
    available_drivers = Driver.objects.filter(available=True).count()
    verified_drivers = Driver.objects.filter(is_verified=True).count()

    total_vehicles = Vehicle.objects.count()
    active_vehicles = Vehicle.objects.filter(is_active=True).count()

    # Recent activities
    recent_bookings = Booking.objects.order_by('-created_at')[:5]
    recent_payments = Payment.objects.order_by('-created_at')[:5]

    context = {
        'total_bookings': total_bookings,
        'pending_bookings': pending_bookings,
        'confirmed_bookings': confirmed_bookings,
        'completed_bookings': completed_bookings,
        'total_revenue': total_revenue,
        'pending_revenue': pending_revenue,
        'total_drivers': total_drivers,
        'available_drivers': available_drivers,
        'verified_drivers': verified_drivers,
        'total_vehicles': total_vehicles,
        'active_vehicles': active_vehicles,
        'recent_bookings': recent_bookings,
        'recent_payments': recent_payments,
    }

    return render(request, 'admin/dashboard.html', context)


# =============================================================================
# REGISTER CUSTOM ADMIN URLS WITH THE DEFAULT ADMIN SITE
# =============================================================================

# This is the fix: We override the get_urls method to inject our custom admin URLs.
# This makes them available to the default admin site, resolving the NoReverseMatch error.

def get_admin_urls(urls):
    def get_urls():
        # Define your custom admin URLs here.
        # The names must match what is used in reverse() calls (e.g., 'admin:booking_action').
        custom_urls = [
            path('driver/<int:driver_id>/action/', admin.site.admin_view(driver_action_view), name='driver_action'),
            path('booking/<int:booking_id>/action/', admin.site.admin_view(booking_action_view), name='booking_action'),
            path('trip/<int:trip_id>/action/', admin.site.admin_view(trip_action_view), name='trip_action'),
            path('payment/<int:payment_id>/action/', admin.site.admin_view(payment_action_view), name='payment_action'),
            path('dashboard/', admin.site.admin_view(dashboard_view), name='dashboard'),
        ]
        # Add your custom URLs to the original admin URLs
        return custom_urls + urls

    return get_urls

# Apply the override to the default admin site
admin.site.get_urls = get_admin_urls(admin.site.get_urls())