from django.contrib import admin
from .models import Destination, Customer, Booking, Payment, ContactMessage, Tour, Driver


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ("name", "location", "price_per_person", "destination_type", "created_at")
    list_filter = ("destination_type", "created_at")
    search_fields = ("name", "location", "description")
    ordering = ("name",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email", "phone_number", "created_at")
    search_fields = ("first_name", "last_name", "email", "phone_number")
    ordering = ("-created_at",)


@admin.register(Tour)
class TourAdmin(admin.ModelAdmin):
    list_display = ("title", "price_per_person", "available", "is_approved", "created_by", "created_at")
    list_filter = ("available", "is_approved", "created_at", "created_by")
    search_fields = ("title", "description", "created_by__username")
    ordering = ("-created_at",)


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_number", "license_number", "available")
    list_filter = ("available",)
    search_fields = ("name", "phone_number", "license_number")
    ordering = ("name",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("customer", "destination", "booking_type", "num_passengers",
                    "travel_date", "total_price", "is_confirmed", "booking_date", "driver")
    list_filter = ("booking_type", "is_confirmed", "travel_date", "booking_date")
    search_fields = ("customer__first_name", "customer__last_name",
                     "customer__email", "destination__name", "driver__name")
    ordering = ("-booking_date",)
    date_hierarchy = "travel_date"
    autocomplete_fields = ("customer", "destination", "driver")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("booking", "amount_paid", "method", "transaction_id", "paid_on", "is_successful")
    list_filter = ("method", "is_successful", "paid_on")
    search_fields = ("transaction_id", "booking__customer__first_name", "booking__customer__last_name")
    ordering = ("-paid_on",)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "subject", "sent_at")
    search_fields = ("name", "email", "subject", "message")
    ordering = ("-sent_at",)
