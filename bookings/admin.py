from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.db.models import Count, Sum, Avg
from django.utils import timezone
from decimal import Decimal
from .models import (
    BookingCustomer, Driver, Vehicle, Destination, TourCategory, Tour,
    Booking, Trip, Payment, PaymentProvider, PaymentStatus
)

# =============================================================================
# INLINE ADMIN CLASSES
# =============================================================================

class TripInline(admin.TabularInline):
    model = Trip
    extra = 0
    fields = ('date', 'start_time', 'end_time', 'status', 'earnings')
    readonly_fields = ('date', 'start_time', 'end_time', 'status', 'earnings')

class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ('amount', 'status', 'provider', 'transaction_id')
    readonly_fields = ('amount', 'status', 'provider', 'transaction_id')

class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0
    fields = ('booking_reference', 'travel_date', 'status', 'total_price')
    readonly_fields = ('booking_reference', 'travel_date', 'status', 'total_price')

# =============================================================================
# MODEL ADMIN CLASSES
# =============================================================================

@admin.register(BookingCustomer)
class BookingCustomerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'normalized_phone', 'adults', 'children', 'travel_date')
    list_filter = ('travel_date', 'adults', 'children')
    search_fields = ('full_name', 'email', 'normalized_phone')
    ordering = ('-travel_date',)
    readonly_fields = ('normalized_phone',)

@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'normalized_phone', 'license_number', 'rating', 'available', 'is_verified')
    list_filter = ('available', 'is_verified', 'gender', 'license_type')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'normalized_phone', 'license_number')
    readonly_fields = ('normalized_phone', 'rating', 'total_trips', 'total_earnings')
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'phone_number', 'normalized_phone', 'gender', 'date_of_birth', 'nationality')
        }),
        ('Profile', {
            'fields': ('profile_picture', 'bio', 'preferred_language', 'communication_preferences')
        }),
        ('Driver Details', {
            'fields': ('license_number', 'license_type', 'license_expiry', 'available', 'experience_years')
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
    )
    inlines = [TripInline]

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'license_plate', 'vehicle_type', 'fuel_type', 'capacity', 'is_active')
    list_filter = ('vehicle_type', 'fuel_type', 'is_active')
    search_fields = ('make', 'model', 'license_plate')
    readonly_fields = ('vehicle_age', 'documents_valid', 'insurance_status', 'inspection_status')
    fieldsets = (
        ('Basic Information', {
            'fields': ('make', 'model', 'year', 'color', 'license_plate', 'vehicle_type', 'fuel_type', 'capacity')
        }),
        ('Images', {
            'fields': ('image', 'external_image_url')
        }),
        ('Features', {
            'fields': ('features', 'accessibility_features')
        }),
        ('Documents', {
            'fields': ('logbook_copy', 'insurance_copy', 'inspection_certificate')
        }),
        ('Status', {
            'fields': ('insurance_expiry', 'inspection_expiry', 'is_active')
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

@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ('name', 'destination_type', 'price_per_person', 'currency', 'is_active', 'is_featured')
    list_filter = ('destination_type', 'is_active', 'is_featured', 'eco_friendly')
    search_fields = ('name', 'description', 'location')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('get_absolute_url', 'primary_image')
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
            'fields': ('image', 'video', 'image_url', 'gallery_images', 'primary_image')
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

@admin.register(TourCategory)
class TourCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Tour)
class TourAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'duration_days', 'price_per_person', 'available', 'is_approved', 'featured')
    list_filter = ('category', 'difficulty', 'available', 'is_approved', 'featured', 'is_popular', 'eco_friendly')
    search_fields = ('title', 'description', 'tagline')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('get_absolute_url', 'current_price', 'total_duration', 'discount_percentage')
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
            'fields': ('image', 'video', 'image_url', 'gallery_images')
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

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('booking_reference', 'service_name', 'booking_customer', 'travel_date', 'status', 'total_price', 'is_paid')
    list_filter = ('booking_type', 'status', 'is_paid', 'is_cancelled', 'travel_date')
    search_fields = ('booking_reference', 'booking_customer__full_name', 'booking_customer__email')
    readonly_fields = ('booking_reference', 'total_passengers', 'is_upcoming', 'is_past', 'is_today', 'can_be_cancelled', 'service_name')
    fieldsets = (
        ('Booking Information', {
            'fields': ('booking_reference', 'booking_type', 'status', 'is_cancelled', 'cancellation_reason')
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

@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ('destination', 'driver', 'vehicle', 'date', 'status', 'earnings')
    list_filter = ('status', 'date', 'driver')
    search_fields = ('destination', 'driver__user__username', 'driver__user__first_name', 'driver__user__last_name')
    readonly_fields = ('duration', 'fuel_efficiency')
    fieldsets = (
        ('Trip Information', {
            'fields': ('driver', 'booking', 'vehicle', 'destination', 'status')
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

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('booking', 'amount', 'currency', 'provider', 'status', 'transaction_id')
    list_filter = ('status', 'provider', 'currency')
    search_fields = ('transaction_id', 'booking__booking_reference', 'booking__booking_customer__email')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Payment Information', {
            'fields': ('booking', 'amount', 'currency', 'provider', 'status')
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

# =============================================================================
# ADMIN CUSTOMIZATION
# =============================================================================

admin.site.site_header = "Safari Bookings Administration"
admin.site.site_title = "Safari Bookings Admin"
admin.site.index_title = "Welcome to Safari Bookings Administration"

# =============================================================================
# CUSTOM ACTIONS
# =============================================================================

def approve_tours(modeladmin, request, queryset):
    queryset.update(is_approved=True)
approve_tours.short_description = "Approve selected tours"

def feature_tours(modeladmin, request, queryset):
    queryset.update(featured=True)
feature_tours.short_description = "Feature selected tours"

def confirm_bookings(modeladmin, request, queryset):
    queryset.update(status='CONFIRMED')
confirm_bookings.short_description = "Confirm selected bookings"

def complete_trips(modeladmin, request, queryset):
    queryset.update(status='COMPLETED')
complete_trips.short_description = "Mark selected trips as completed"

# Add actions to model admins
TourAdmin.actions = [approve_tours, feature_tours]
BookingAdmin.actions = [confirm_bookings]
TripAdmin.actions = [complete_trips]