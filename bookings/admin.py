from django import forms
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
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
    list_display = (
        "customer",
        "destination",
        "booking_type",
        "num_passengers",
        "travel_date",
        "total_price",
        "colored_status",
        "booking_date",
        "driver"
    )
    list_filter = ("booking_type", "is_confirmed", "is_cancelled", "travel_date", "booking_date")
    search_fields = ("customer__first_name", "customer__last_name",
                     "customer__email", "destination__name", "driver__name")
    ordering = ("-booking_date",)
    date_hierarchy = "travel_date"
    autocomplete_fields = ("customer", "destination", "driver")

    def colored_status(self, obj):
        if obj.is_cancelled:
            color = "red"
            status = "Cancelled"
        elif obj.is_confirmed:
            color = "green"
            status = "Confirmed"
        else:
            color = "orange"
            status = "Pending"
        return format_html('<span style="color: {};">{}</span>', color, status)
    colored_status.short_description = "Status"

# =====================================================
# PAYMENT ADMIN FORM
# =====================================================
class PaymentAdminForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        required_fields = [
            "amount", "currency", "provider", "method",
            "guest_full_name", "guest_email", "guest_phone",
            "description"
        ]
        for field in required_fields:
            if not cleaned_data.get(field):
                raise forms.ValidationError({field: f"{field.replace('_',' ').title()} is required."})
        return cleaned_data

# =====================================================
# PAYMENT ADMIN ACTIONS
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

# =====================================================
# PAYMENT ADMIN
# =====================================================
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    form = PaymentAdminForm
    actions = [mark_as_completed]

    list_display = (
        "booking",
        "tour",
        "guest_full_name_safe",
        "guest_email_safe",
        "guest_phone_safe",
        "get_adults",
        "get_children",
        "get_days",
        "amount",
        "currency",
        "provider",
        "get_method",
        "colored_status",
        "transaction_id_safe",
        "description",
        "created_at",
    )

    # --- Safe list_display methods ---
    def guest_full_name_safe(self, obj):
        return obj.guest_full_name or "Guest"
    guest_full_name_safe.short_description = "Guest Full Name"

    def guest_email_safe(self, obj):
        return obj.guest_email or "-"
    guest_email_safe.short_description = "Guest Email"

    def guest_phone_safe(self, obj):
        return obj.guest_phone or "-"
    guest_phone_safe.short_description = "Guest Phone"

    def get_adults(self, obj):
        return getattr(obj, "adults", 1)
    get_adults.short_description = "Adults"

    def get_children(self, obj):
        return getattr(obj, "children", 0)
    get_children.short_description = "Children"

    def get_days(self, obj):
        return getattr(obj, "days", obj.tour.duration_days if obj.tour else 0)
    get_days.short_description = "Days"

    def get_method(self, obj):
        return obj.method or obj.provider
    get_method.short_description = "Payment Method"

    def transaction_id_safe(self, obj):
        # Use only transaction_id field that exists
        return obj.transaction_id or "-"
    transaction_id_safe.short_description = "Transaction ID"

    # --- Colored payment status ---
    def colored_status(self, obj):
        color_map = {
            PaymentStatus.SUCCESS: "green",
            PaymentStatus.PENDING: "orange",
            PaymentStatus.FAILED: "red",
        }
        color = color_map.get(obj.status, "black")
        return format_html('<span style="color: {};">{}</span>', color, obj.status)
    colored_status.short_description = "Status"

    # --- Override save_model for deduplication & notifications ---
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        # Deduplicate Pesapal references
        if obj.pesapal_reference:
            duplicates = Payment.objects.filter(
                pesapal_reference=obj.pesapal_reference
            ).exclude(id=obj.id).order_by("-created_at")
            duplicates.delete()

        # Notify admin via email
        admin_email = getattr(settings, "ADMIN_EMAIL", None)
        if admin_email:
            subject = f"Payment Update: {obj.status} - {obj.pesapal_reference or 'No Ref'}"
            message = f"""
Payment Details:

Booking: {obj.booking or '-'}
Tour: {obj.tour or '-'}
Amount: {obj.amount} {obj.currency}
Provider: {obj.provider}
Status: {obj.status}
Transaction ID: {obj.transaction_id or '-'}
Pesapal Reference: {obj.pesapal_reference or '-'}
Payment Method: {obj.method or obj.provider}
Guest Name: {obj.guest_full_name or 'Guest'}
Guest Email: {obj.guest_email or '-'}
Guest Phone: {obj.guest_phone or '-'}
Description: {obj.description or '-'}
Created At: {obj.created_at}

This notification was generated automatically by the admin panel.
            """
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
