from django import forms
from django.contrib import admin, messages
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from .models import (
    Destination, Customer, Booking, Payment, PaymentStatus,
    ContactMessage, Tour, Driver, Video, Trip
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
    list_display = ("title", "price_per_person", "duration_days",
                    "available", "is_approved", "created_by", "created_at")
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
    list_display = ("name", "phone_number", "license_number",
                    "available", "experience_years", "vehicle")
    list_filter = ("available", "experience_years")
    search_fields = ("name", "phone_number", "license_number", "vehicle")
    ordering = ("name",)

# =====================================================
# BOOKING ADMIN
# =====================================================
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("customer", "destination", "booking_type", "num_passengers",
                    "travel_date", "total_price", "is_confirmed", "is_cancelled",
                    "booking_date", "driver")
    list_filter = ("booking_type", "is_confirmed", "is_cancelled", "travel_date", "booking_date")
    search_fields = ("customer__first_name", "customer__last_name",
                     "customer__email", "destination__name", "driver__name")
    ordering = ("-booking_date",)
    date_hierarchy = "travel_date"
    autocomplete_fields = ("customer", "destination", "driver")


# =====================================================
# PAYMENT FORM (Admin-level validation)
# =====================================================
class PaymentAdminForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()

        # Ensure no critical blank fields
        required_fields = [
            "amount", "currency", "provider", "method",
            "guest_full_name", "guest_email", "guest_phone",
            "description"
        ]
        for field in required_fields:
            value = cleaned_data.get(field)
            if not value:
                raise forms.ValidationError({field: f"{field.replace('_',' ').title()} is required."})

        return cleaned_data

# =====================================================
# PAYMENT ADMIN
# =====================================================
@admin.action(description="Mark selected payments as Completed")
def mark_as_completed(modeladmin, request, queryset):
    updated_count = 0
    for payment in queryset:
        if payment.status != PaymentStatus.SUCCESS:
            payment.status = PaymentStatus.SUCCESS
            payment.updated_at = timezone.now()
            payment.save()
            updated_count += 1
    messages.success(request, f"{updated_count} payment(s) marked as Completed.")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    form = PaymentAdminForm
    actions = [mark_as_completed]

    list_display = (
        "booking",
        "tour",
        "amount",
        "currency",
        "provider",
        "status",
        "pesapal_reference",
        "transaction_id",
        "get_method",
        "guest_full_name",
        "guest_email",
        "guest_phone",
        "description",
        "created_at",
    )
    list_filter = ("provider", "status", "currency", "created_at", "method")
    search_fields = (
        "transaction_id",
        "reference",
        "pesapal_reference",
        "guest_full_name",
        "guest_email",
        "guest_phone",
        "description",
        "booking__customer__first_name",
        "booking__customer__last_name",
        "tour__title",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("booking", "tour", "user")

    # Custom Methods
    def get_method(self, obj):
        return obj.method
    get_method.short_description = "Payment Method"

    def save_model(self, request, obj, form, change):
        """
        - Ensures no critical blanks (validated by form).
        - Deduplicates Pesapal references.
        - Sends admin email automatically.
        """
        super().save_model(request, obj, form, change)

        # Deduplicate Pesapal reference
        if obj.pesapal_reference:
            duplicates = Payment.objects.filter(pesapal_reference=obj.pesapal_reference)\
                                        .exclude(id=obj.id)\
                                        .order_by("-created_at")
            duplicates.delete()

        # Send admin email
        subject = f"Payment Update: {obj.status} - {obj.pesapal_reference or 'No Ref'}"
        message = f"""
Payment Details:

Booking: {obj.booking or '-'}
Tour: {obj.tour or '-'}
Amount: {obj.amount} {obj.currency}
Provider: {obj.provider}
Status: {obj.status}
Pesapal Reference: {obj.pesapal_reference or '-'}
Transaction ID: {obj.transaction_id or '-'}
Payment Method: {obj.method}
Guest Name: {obj.guest_full_name}
Guest Email: {obj.guest_email}
Guest Phone: {obj.guest_phone}
Description: {obj.description}
Created At: {obj.created_at}

This notification was generated automatically by the admin panel.
        """

        admin_email = getattr(settings, "ADMIN_EMAIL", None)
        if admin_email:
            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[admin_email],
                    fail_silently=False
                )
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to send admin email for Payment {obj.id}: {e}")
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
