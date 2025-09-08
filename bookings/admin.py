from django.contrib import admin
from .models import (
    Destination, Customer, Booking, Payment, ContactMessage,
    Tour, Driver, Video, Trip
)


# =====================================================
# DESTINATION ADMIN
# =====================================================
@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ("name", "location", "price_per_person", "destination_type", "created_at")
    list_filter = ("destination_type", "created_at")
    search_fields = ("name", "location", "description")
    ordering = ("name",)
    date_hierarchy = "created_at"


# =====================================================
# CUSTOMER ADMIN
# =====================================================
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email", "phone_number", "created_at")
    search_fields = ("first_name", "last_name", "email", "phone_number")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"


# =====================================================
# TOUR ADMIN
# =====================================================
@admin.register(Tour)
class TourAdmin(admin.ModelAdmin):
    list_display = ("title", "price_per_person", "duration_days", "available", "is_approved", "created_by", "created_at")
    list_filter = ("available", "is_approved", "created_at", "created_by")
    search_fields = ("title", "description", "created_by__username")
    ordering = ("-created_at",)
    autocomplete_fields = ("created_by",)
    date_hierarchy = "created_at"


# =====================================================
# DRIVER ADMIN
# =====================================================
@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_number", "license_number", "available", "experience_years", "vehicle")
    list_filter = ("available", "experience_years")
    search_fields = ("name", "phone_number", "license_number", "vehicle")
    ordering = ("name",)


# =====================================================
# BOOKING ADMIN
# =====================================================
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "customer", "destination", "booking_type", "num_passengers",
        "travel_date", "total_price", "is_confirmed", "is_cancelled",
        "booking_date", "driver"
    )
    list_filter = ("booking_type", "is_confirmed", "is_cancelled", "travel_date", "booking_date")
    search_fields = (
        "customer__first_name", "customer__last_name",
        "customer__email", "destination__name", "driver__name"
    )
    ordering = ("-booking_date",)
    date_hierarchy = "travel_date"
    autocomplete_fields = ("customer", "destination", "driver")


# =====================================================
# PAYMENT ADMIN
# =====================================================
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("booking", "tour", "amount", "currency", "provider", "status", "transaction_id", "created_at")
    list_filter = ("provider", "status", "currency", "created_at")
    search_fields = (
        "transaction_id", "reference", "pesapal_reference",
        "booking__customer__first_name", "booking__customer__last_name",
        "tour__title",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("booking", "tour", "user")


# =====================================================
# CONTACT MESSAGE ADMIN
# =====================================================
@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "subject", "sent_at")
    search_fields = ("name", "email", "subject", "message")
    ordering = ("-sent_at",)
    date_hierarchy = "sent_at"


# =====================================================
# VIDEO ADMIN
# =====================================================
@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "price", "created_at")
    search_fields = ("title", "description")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"


# =====================================================
# TRIP ADMIN
# =====================================================
@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ("driver", "destination", "date", "earnings", "status", "created_at")
    list_filter = ("status", "date", "created_at")
    search_fields = ("driver__name", "destination")
    ordering = ("-date", "-created_at")
    date_hierarchy = "date"
    autocomplete_fields = ("driver",)
