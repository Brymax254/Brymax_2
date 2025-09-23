from django import forms
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse, path
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import (
    Destination, Customer, Booking, Payment, PaymentStatus,
    ContactMessage, Tour, Driver, Video, Trip
)


# =====================================================
# DESTINATION ADMIN
# =====================================================
@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ("name", "location", "price_per_person", "destination_type", "is_active", "created_at")
    list_filter = ("destination_type", "is_active", "created_at")
    search_fields = ("name", "location", "description")
    ordering = ("name",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (None, {
            "fields": ("name", "slug", "destination_type", "is_active")
        }),
        ("Details", {
            "fields": ("description", "location", "price_per_person")
        }),
        ("Media", {
            "fields": ("image", "video")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at")
        }),
    )


# =====================================================
# CUSTOMER ADMIN
# =====================================================
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "normalized_phone", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("first_name", "last_name", "email", "phone_number")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = ("normalized_phone", "created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": ("first_name", "last_name", "email", "is_active")
        }),
        ("Contact Information", {
            "fields": ("phone_number", "normalized_phone")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at")
        }),
    )


# =====================================================
# TOUR ADMIN
# =====================================================
@admin.register(Tour)
class TourAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "price_per_person", "duration_days",
                    "available", "is_approved", "created_by", "created_at")
    list_filter = ("category", "available", "is_approved", "created_at", "created_by")
    search_fields = ("title", "description", "created_by__username")
    ordering = ("-created_at",)
    autocomplete_fields = ("created_by",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = (
        (None, {
            "fields": ("title", "slug", "category", "is_approved", "available", "featured")
        }),
        ("Details", {
            "fields": ("description", "itinerary", "price_per_person", "duration_days")
        }),
        ("Group Settings", {
            "fields": ("min_group_size", "max_group_size", "difficulty")
        }),
        ("Media", {
            "fields": ("image", "video", "image_url")
        }),
        ("Creator", {
            "fields": ("created_by",)
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at")
        }),
    )


# =====================================================
# DRIVER ADMIN
# =====================================================
@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("name", "normalized_phone", "license_number",
                    "available", "is_active", "rating", "created_at")
    list_filter = ("available", "is_active", "experience_years")
    search_fields = ("name", "phone_number", "license_number", "vehicle")
    ordering = ("name",)
    readonly_fields = ("normalized_phone", "created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": ("name", "user", "license_number", "available", "is_active")
        }),
        ("Contact Information", {
            "fields": ("phone_number", "normalized_phone")
        }),
        ("Vehicle Information", {
            "fields": ("vehicle", "vehicle_plate")
        }),
        ("Profile", {
            "fields": ("profile_picture", "experience_years", "bio", "rating")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at")
        }),
    )


# =====================================================
# BOOKING ADMIN
# =====================================================
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "destination",
        "booking_type",
        "num_passengers_field",  # Changed from "num_passengers"
        "travel_date",
        "total_price",
        "status",
        "colored_status",
        "is_paid",
        "driver",
        "created_at",
    )
    list_filter = ("booking_type", "status", "is_paid", "travel_date")
    search_fields = ("customer__first_name", "customer__last_name",
                     "customer__email", "destination__name", "driver__name")
    ordering = ("-booking_date",)
    date_hierarchy = "travel_date"
    autocomplete_fields = ("customer", "destination", "driver")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": ("customer", "destination", "booking_type", "status")
        }),
        ("Trip Details", {
            "fields": ("num_passengers", "travel_date", "travel_time", "pickup_location", "dropoff_location")
        }),
        ("Pricing", {
            "fields": ("total_price", "is_paid")
        }),
        ("Additional Information", {
            "fields": ("special_requests", "driver")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("booking_date", "created_at", "updated_at")
        }),
    )

    def num_passengers_field(self, obj):
        return obj.num_passengers
    num_passengers_field.short_description = "Passengers"

    def colored_status(self, obj):
        color_map = {
            'PENDING': 'orange',
            'CONFIRMED': 'blue',
            'CANCELLED': 'red',
            'COMPLETED': 'green',
        }
        color = color_map.get(obj.status, "black")
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.status)

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
                raise forms.ValidationError({field: f"{field.replace('_', ' ').title()} is required."})
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
            payment.amount_paid = payment.amount
            payment.paid_on = timezone.now()
            payment.updated_at = timezone.now()
            payment.save()
            updated_count += 1
    messages.success(request, f"{updated_count} payment(s) marked as Completed.")


@admin.action(description="Resend confirmation emails for selected payments")
def resend_confirmation_emails(modeladmin, request, queryset):
    sent_count = 0
    for payment in queryset.filter(status=PaymentStatus.SUCCESS):
        try:
            subject = f"Payment Confirmation - {payment.tour.title if payment.tour else 'Your Booking'}"
            message = f"""
Dear {payment.guest_full_name or payment.guest_email.split('@')[0]},

This is a reminder of your payment for "{payment.tour.title if payment.tour else 'Your Booking'}".

Payment Details:
- Reference: {payment.reference}
- Amount: KES {payment.amount}
- Payment Method: {payment.method or payment.provider}
- Paid At: {payment.paid_on.strftime('%Y-%m-%d %H:%M:%S') if payment.paid_on else 'N/A'}

Thank you for booking with Safari Adventures Kenya!

Best regards,
Safari Adventures Kenya Team
            """

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[payment.guest_email],
                fail_silently=False
            )
            sent_count += 1
        except Exception as e:
            messages.error(request, f"Failed to send email for payment {payment.reference}: {str(e)}")

    messages.success(request, f"Confirmation emails resent for {sent_count} payment(s).")


# =====================================================
# PAYMENT ADMIN
# =====================================================
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    form = PaymentAdminForm
    actions = [mark_as_completed, resend_confirmation_emails]

    list_display = (
        "id",
        "get_customer_name",
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
        "reference",
        "paystack_transaction_id",
        "webhook_verified_status",
        "description",
        "paid_on",
        "created_at",
    )

    # --- Safe list_display methods ---
    def get_customer_name(self, obj):
        if obj.user:
            return obj.user.get_full_name()
        return obj.guest_full_name or "Guest"

    get_customer_name.short_description = "Customer"

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

    # --- Colored payment status ---
    def colored_status(self, obj):
        color_map = {
            PaymentStatus.PENDING: "orange",
            PaymentStatus.PROCESSING: "blue",
            PaymentStatus.SUCCESS: "green",
            PaymentStatus.FAILED: "red",
            PaymentStatus.CANCELLED: "gray",
            PaymentStatus.REFUNDED: "purple",
        }
        color = color_map.get(obj.status, "black")
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.status)

    colored_status.short_description = "Status"

    # --- Webhook verification status ---
    def webhook_verified_status(self, obj):
        if obj.webhook_verified:
            return format_html('<span style="color: green; font-weight: bold;">✓ Verified</span>')
        return format_html('<span style="color: red; font-weight: bold;">✗ Not Verified</span>')

    webhook_verified_status.short_description = "Webhook Status"

    # --- Custom actions ---
    def response_view(self, obj):
        if obj.raw_response:
            return format_html(
                '<a class="button" href="{}" target="_blank">View Response</a>',
                reverse('admin:payment_response', args=[obj.pk])
            )
        return "-"

    response_view.short_description = "View Raw Response"

    # --- Override save_model for notifications ---
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        # Send notification to admin for successful payments
        if obj.status == PaymentStatus.SUCCESS and not change:
            admin_email = getattr(settings, "ADMIN_EMAIL", None)
            if admin_email:
                subject = f"New Payment Received: {obj.reference}"
                message = f"""
Payment Details:

Booking: {obj.booking or '-'}
Tour: {obj.tour or '-'}
Amount: {obj.amount} {obj.currency}
Provider: {obj.provider}
Status: {obj.status}
Reference: {obj.reference}
Paystack Transaction ID: {obj.paystack_transaction_id or '-'}
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
                    messages.error(request, f"Failed to send admin email for Payment {obj.id}: {e}")

    # --- Custom changelist view ---
    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)

        # Add custom buttons
        response.context_data['custom_buttons'] = [
            {
                'url': reverse('admin:sync_payments'),
                'label': 'Sync with Paystack',
                'css_class': 'btn btn-primary',
            }
        ]

        return response

    # --- Get URLs ---
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('sync-payments/', self.admin_site.admin_view(self.sync_payments), name='sync_payments'),
            path('<uuid:pk>/response/', self.admin_site.admin_view(self.view_response), name='payment_response'),
        ]
        return custom_urls + urls

    # --- Custom views ---
    def sync_payments(self, request):
        """Sync payment statuses with Paystack"""
        import requests

        # Get all pending payments
        pending_payments = Payment.objects.filter(status=PaymentStatus.PENDING)
        updated_count = 0

        for payment in pending_payments:
            if payment.reference:
                try:
                    # Verify transaction with Paystack
                    headers = {
                        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                    }
                    response = requests.get(
                        f"https://api.paystack.co/transaction/verify/{payment.reference}",
                        headers=headers,
                        timeout=15
                    )
                    response_data = response.json()

                    if response_data.get('status'):
                        payment_data = response_data.get('data', {})
                        if payment_data.get('status') == 'success':
                            payment.status = PaymentStatus.SUCCESS
                            payment.amount_paid = payment.amount
                            payment.paid_on = timezone.now()
                            payment.webhook_verified = True
                            payment.webhook_received_at = timezone.now()
                            payment.raw_response = response_data
                            payment.save()
                            updated_count += 1
                except Exception as e:
                    messages.error(request, f"Failed to sync payment {payment.reference}: {str(e)}")

        messages.success(request, f"Successfully synced {updated_count} payment(s) with Paystack.")
        return JsonResponse({'success': True, 'updated_count': updated_count})

    def view_response(self, request, pk):
        """View raw Paystack response"""
        payment = get_object_or_404(Payment, pk=pk)
        return JsonResponse(payment.raw_response or {})

    # --- Read-only fields ---
    readonly_fields = (
        "id", "reference", "paystack_transaction_id", "access_code",
        "authorization_code", "webhook_verified", "webhook_received_at",
        "raw_response", "created_at", "updated_at"
    )

    fieldsets = (
        (None, {
            "fields": ("id", "status", "provider", "amount", "amount_paid")
        }),
        ("Customer Information", {
            "fields": ("user", "guest_full_name", "guest_email", "guest_phone")
        }),
        ("Booking/Tour Information", {
            "fields": ("booking", "tour", "travel_date")
        }),
        ("Transaction Details", {
            "fields": ("reference", "paystack_transaction_id", "transaction_id", "authorization_code")
        }),
        ("Billing Information", {
            "fields": ("billing_line1", "billing_city", "billing_state", "billing_postal_code", "billing_country_code")
        }),
        ("Webhook Information", {
            "fields": ("webhook_verified", "webhook_received_at", "raw_response")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("paid_on", "created_at", "updated_at")
        }),
    )


# =====================================================
# CONTACT MESSAGE ADMIN
# =====================================================
@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "subject", "is_resolved", "created_at")
    list_filter = ("is_resolved", "created_at")
    search_fields = ("name", "email", "subject", "message")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    actions = ["mark_as_resolved"]
    fieldsets = (
        (None, {
            "fields": ("name", "email", "phone", "subject", "is_resolved")
        }),
        ("Message", {
            "fields": ("message",)
        }),
        ("Resolution", {
            "fields": ("resolved_by", "resolved_at")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at")
        }),
    )

    def mark_as_resolved(self, request, queryset):
        queryset.update(is_resolved=True)
        self.message_user(request, "Selected messages marked as resolved.")

    mark_as_resolved.short_description = "Mark selected messages as resolved"


# =====================================================
# VIDEO ADMIN
# =====================================================
@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_featured", "is_active", "created_at")
    list_filter = ("category", "is_featured", "is_active", "created_at")
    search_fields = ("title", "description")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = (
        (None, {
            "fields": ("title", "slug", "category", "is_featured", "is_active")
        }),
        ("Details", {
            "fields": ("description", "price")
        }),
        ("Media", {
            "fields": ("file", "thumbnail")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at")
        }),
    )


# =====================================================
# TRIP ADMIN
# =====================================================
@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ("driver", "destination", "date", "status", "earnings", "created_at")
    list_filter = ("status", "date", "created_at")
    search_fields = ("driver__name", "destination")
    ordering = ("-date", "-created_at")
    date_hierarchy = "date"
    autocomplete_fields = ("driver",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": ("driver", "destination", "date", "status")
        }),
        ("Schedule", {
            "fields": ("start_time", "end_time")
        }),
        ("Details", {
            "fields": ("earnings", "distance", "notes")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at")
        }),
    )