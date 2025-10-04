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
    Driver, BookingCustomer, Vehicle, Destination, TourCategory, Tour,
    Booking, Trip, Payment, PaymentStatus, Review, ContactMessage
)


# =====================================================
# DESTINATION ADMIN
# =====================================================
@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ("name", "location", "price_per_person", "destination_type", "is_active", "is_featured",
                    "created_at")
    list_filter = ("destination_type", "is_active", "is_featured", "created_at")
    search_fields = ("name", "location", "description")
    ordering = ("name",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (None, {
            "fields": ("name", "slug", "destination_type", "is_active", "is_featured")
        }),
        ("Details", {
            "fields": ("description", "location", "price_per_person", "currency")
        }),
        ("Location", {
            "fields": ("latitude", "longitude")
        }),
        ("Media", {
            "fields": ("image", "video", "image_url", "gallery_images")
        }),
        ("Sustainability", {
            "fields": ("eco_friendly", "carbon_footprint_per_visit", "sustainability_certifications")
        }),
        ("Accessibility", {
            "fields": ("wheelchair_accessible", "accessibility_features")
        }),
        ("Health & Safety", {
            "fields": ("health_safety_measures", "covid19_protocols")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at")
        }),
    )


# =====================================================
# TOUR CATEGORY ADMIN
# =====================================================
@admin.register(TourCategory)
class TourCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "description")
    ordering = ("name",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (None, {
            "fields": ("name", "slug", "is_active")
        }),
        ("Details", {
            "fields": ("description", "image")
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
    list_display = ("title", "category", "price_per_person", "current_price", "duration_days",
                    "available", "is_approved", "is_popular", "featured", "created_by", "created_at")
    list_filter = ("category", "available", "is_approved", "is_popular", "featured", "created_at", "created_by")
    search_fields = ("title", "description", "created_by__username")
    ordering = ("-created_at",)
    autocomplete_fields = ("created_by", "category", "destinations")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = (
        (None, {
            "fields": ("title", "slug", "category", "is_approved", "available", "featured", "is_popular")
        }),
        ("Details", {
            "fields": ("tagline", "description", "highlights", "itinerary", "inclusions", "exclusions")
        }),
        ("Pricing", {
            "fields": ("price_per_person", "discount_price", "currency")
        }),
        ("Duration & Group", {
            "fields": ("duration_days", "duration_nights", "min_group_size", "max_group_size")
        }),
        ("Other Details", {
            "fields": ("difficulty", "max_advance_booking_days")
        }),
        ("Location", {
            "fields": ("departure_point", "destinations_visited", "destinations")
        }),
        ("Media", {
            "fields": ("image", "video", "image_url", "gallery_images")
        }),
        ("Sustainability", {
            "fields": ("eco_friendly", "carbon_footprint_per_person", "sustainability_certifications")
        }),
        ("Accessibility", {
            "fields": ("wheelchair_accessible", "accessibility_features")
        }),
        ("Health & Safety", {
            "fields": ("health_safety_measures", "covid19_protocols")
        }),
        ("Creator", {
            "fields": ("created_by", "approved_by", "approved_at")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at")
        }),
    )

# =====================================================
# VEHICLE ADMIN
# =====================================================
from django.contrib import admin
from django.utils.html import format_html
import datetime
import json
from .models import Vehicle


# -------------------------
# CUSTOM FILTERS
# -------------------------
class InsuranceStatusFilter(admin.SimpleListFilter):
    title = "Insurance Status"
    parameter_name = "insurance_status"

    def lookups(self, request, model_admin):
        return [
            ("valid", "Valid"),
            ("expired", "Expired"),
        ]

    def queryset(self, request, queryset):
        today = datetime.date.today()
        if self.value() == "valid":
            return queryset.filter(insurance_expiry__gte=today)
        if self.value() == "expired":
            return queryset.filter(insurance_expiry__lt=today)
        return queryset


class InspectionStatusFilter(admin.SimpleListFilter):
    title = "Inspection Status"
    parameter_name = "inspection_status"

    def lookups(self, request, model_admin):
        return [
            ("valid", "Valid"),
            ("expired", "Expired"),
        ]

    def queryset(self, request, queryset):
        today = datetime.date.today()
        if self.value() == "valid":
            return queryset.filter(inspection_expiry__gte=today)
        if self.value() == "expired":
            return queryset.filter(inspection_expiry__lt=today)
        return queryset


# -------------------------
# VEHICLE ADMIN
# -------------------------
@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        "license_plate",
        "full_name",
        "vehicle_type_display",
        "fuel_type_display",
        "capacity",
        "is_active",
        "insurance_status",
        "inspection_status",
        "image_preview",
    )
    list_filter = (
        "vehicle_type",
        "fuel_type",
        "is_active",
        InsuranceStatusFilter,   # ✅ custom filter
        InspectionStatusFilter,  # ✅ custom filter
        "created_at",
    )
    search_fields = ("make", "model", "license_plate", "color")
    ordering = ("license_plate",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at", "image_preview", "vehicle_age", "documents_status")

    fieldsets = (
        (None, {
            "fields": (
                "make", "model", "year", "color", "license_plate",
                "vehicle_type", "fuel_type", "capacity", "is_active"
            )
        }),
        ("Images", {
            "fields": (("image", "image_preview"), "external_image_url"),
            "description": "Upload an image or provide an external image URL"
        }),
        ("Features", {
            "fields": ("features", "accessibility_features"),
            "classes": ("collapse",)
        }),
        ("Documents", {
            "fields": ("logbook_copy", "insurance_copy", "inspection_certificate"),
            "classes": ("collapse",)
        }),
        ("Expiry Dates", {
            "fields": ("insurance_expiry", "inspection_expiry")
        }),
        ("Environmental", {
            "fields": ("carbon_footprint_per_km",),
            "classes": ("collapse",)
        }),
        ("Vehicle Information", {
            "fields": ("vehicle_age", "documents_status"),
            "classes": ("collapse",)
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at")
        }),
    )

    # -------------------------
    # DISPLAY HELPERS
    # -------------------------
    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height: 100px; max-width: 200px; border-radius:5px;" />',
                obj.image.url
            )
        elif obj.external_image_url:
            return format_html(
                '<img src="{}" style="max-height: 100px; max-width: 200px; border-radius:5px;" />',
                obj.external_image_url
            )
        return format_html(
            '<div style="width:200px; height:100px; background:#f0f0f0; border-radius:5px; '
            'display:flex; align-items:center; justify-content:center; color:#666;">{}<br>Image</div>',
            obj.vehicle_type_display
        )

    image_preview.short_description = "Image Preview"

    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = "Vehicle"

    def vehicle_type_display(self, obj):
        return obj.vehicle_type_display
    vehicle_type_display.short_description = "Type"

    def fuel_type_display(self, obj):
        return obj.fuel_type_display
    fuel_type_display.short_description = "Fuel"

    def insurance_status(self, obj):
        today = datetime.date.today()
        if obj.insurance_expiry and obj.insurance_expiry >= today:
            return format_html('<span style="color: green;">✓ Valid</span>')
        return format_html('<span style="color: red;">✗ Expired</span>')
    insurance_status.short_description = "Insurance"
    insurance_status.admin_order_field = "insurance_expiry"

    def inspection_status(self, obj):
        today = datetime.date.today()
        if obj.inspection_expiry and obj.inspection_expiry >= today:
            return format_html('<span style="color: green;">✓ Valid</span>')
        return format_html('<span style="color: red;">✗ Expired</span>')
    inspection_status.short_description = "Inspection"
    inspection_status.admin_order_field = "inspection_expiry"

    def vehicle_age(self, obj):
        return f"{obj.vehicle_age} years" if obj.vehicle_age is not None else "N/A"
    vehicle_age.short_description = "Vehicle Age"

    def documents_status(self, obj):
        if obj.documents_valid:
            return format_html('<span style="color: green;">✓ All Valid</span>')
        return format_html('<span style="color: red;">✗ Some Expired</span>')
    documents_status.short_description = "Documents Status"

    # -------------------------
    # FORM HANDLING
    # -------------------------
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in ["features", "accessibility_features"]:
            kwargs["widget"] = forms.Textarea(attrs={"rows": 4, "cols": 40})
            kwargs["help_text"] = 'Enter features as JSON, e.g.: ["AC", "WiFi", "USB Charging"]'
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        for field_name in ["features", "accessibility_features"]:
            field_value = form.cleaned_data.get(field_name)
            if isinstance(field_value, str):
                try:
                    parsed = json.loads(field_value)
                    if isinstance(parsed, list):
                        setattr(obj, field_name, parsed)
                    else:
                        setattr(obj, field_name, [])
                except json.JSONDecodeError:
                    setattr(obj, field_name, [item.strip() for item in field_value.split(",") if item.strip()])
        super().save_model(request, obj, form, change)

    class Media:
        css = {"all": ("admin/css/vehicle_admin.css",)}
        js = ("admin/js/vehicle_admin.js",)

# =====================================================
# DRIVER ADMIN
# =====================================================
@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("get_full_name", "get_phone_display", "license_number", "license_type",
                    "available", "rating", "total_trips", "created_at")
    list_filter = ("available", "license_type", "experience_years", "created_at", "is_verified")
    search_fields = ("user__first_name", "user__last_name", "phone_number", "license_number", "vehicle__license_plate")
    ordering = ("user__first_name", "user__last_name")
    autocomplete_fields = ("user", "vehicle")
    date_hierarchy = "created_at"
    readonly_fields = ("normalized_phone", "created_at", "updated_at", "total_trips", "total_earnings", "rating")
    fieldsets = (
        (None, {
            "fields": ("user", "license_number", "license_type", "available", "is_verified")
        }),
        ("Contact Information", {
            "fields": ("phone_number", "normalized_phone")
        }),
        ("Personal Details", {
            "fields": ("gender", "date_of_birth", "nationality", "profile_picture", "bio")
        }),
        ("License & Experience", {
            "fields": ("license_expiry", "driver_license_copy", "experience_years")
        }),
        ("Documents", {
            "fields": ("verification_document", "police_clearance"),
            "classes": ("collapse",)
        }),
        ("Bank Information", {
            "fields": ("bank_name", "bank_account", "bank_branch", "payment_methods"),
            "classes": ("collapse",)
        }),
        ("Statistics", {
            "fields": ("rating", "total_trips", "total_earnings"),
            "classes": ("collapse",)
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )

    # Custom methods to display user information
    def get_full_name(self, obj):
        return obj.user.get_full_name() if obj.user else "No User"
    get_full_name.short_description = "Full Name"
    get_full_name.admin_order_field = "user__first_name"

    def get_phone_display(self, obj):
        return obj.phone_number
    get_phone_display.short_description = "Phone Number"

    def get_email(self, obj):
        return obj.user.email if obj.user else "No Email"
    get_email.short_description = "Email"

    # If you want to include email in search, add this method
    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        queryset |= self.model.objects.filter(user__email__icontains=search_term)
        return queryset, use_distinct
# =====================================================
# BOOKING ADMIN
# =====================================================
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "booking_reference",
        "booking_customer",
        "service_name",
        "booking_type",
        "total_passengers",
        "travel_date",
        "travel_time",
        "total_price",
        "colored_status",
        "is_paid",
        "driver",
        "created_at",
    )
    list_filter = ("booking_type", "status", "is_paid", "travel_date", "carbon_offset_option")
    search_fields = ("booking_reference", "booking_customer__full_name", "booking_customer__email",
                     "destination__name", "tour__title", "driver__full_name")
    ordering = ("-booking_date",)
    date_hierarchy = "travel_date"
    autocomplete_fields = ("booking_customer", "destination", "tour", "driver", "vehicle")
    readonly_fields = ("created_at", "updated_at", "booking_reference")
    fieldsets = (
        (None, {
            "fields": ("booking_reference", "booking_customer", "booking_type", "status")
        }),
        ("Service", {
            "fields": ("destination", "tour")
        }),
        ("Passengers", {
            "fields": ("num_adults", "num_children", "num_infants")
        }),
        ("Dates & Times", {
            "fields": ("travel_date", "travel_time", "return_date", "return_time")
        }),
        ("Locations", {
            "fields": ("pickup_location", "dropoff_location")
        }),
        ("Coordinates", {
            "fields": ("pickup_latitude", "pickup_longitude", "dropoff_latitude", "dropoff_longitude")
        }),
        ("Pricing", {
            "fields": ("total_price", "currency", "carbon_offset_option", "carbon_offset_amount")
        }),
        ("Payment", {
            "fields": ("is_paid",)
        }),
        ("Assignment", {
            "fields": ("driver", "vehicle")
        }),
        ("Additional Information", {
            "fields": ("special_requests", "notes", "cancellation_reason")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("booking_date", "created_at", "updated_at")
        }),
    )

    def colored_status(self, obj):
        color_map = {
            'PENDING': 'orange',
            'CONFIRMED': 'blue',
            'CANCELLED': 'red',
            'COMPLETED': 'green',
            'IN_PROGRESS': 'purple',
            'NO_SHOW': 'gray',
        }
        color = color_map.get(obj.status, "black")
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.status)

    colored_status.short_description = "Status"


# =============================================================================
# TRIP ADMIN
# =============================================================================
@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ('destination', 'driver', 'date', 'start_time', 'status', 'earnings')
    list_filter = ('status', 'date')
    search_fields = ('destination', 'driver__full_name', 'booking__booking_reference')
    autocomplete_fields = ['driver', 'vehicle', 'booking']
    readonly_fields = ('duration', 'fuel_efficiency')

    fieldsets = (
        ('Trip Information', {
            'fields': ('driver', 'booking', 'vehicle', 'destination', 'status')
        }),
        ('Schedule', {
            'fields': ('date', 'start_time', 'end_time')
        }),
        ('Metrics', {
            'fields': ('earnings', 'distance', 'fuel_consumed', 'carbon_emissions')
        }),
        ('Feedback', {
            'fields': ('customer_rating', 'customer_feedback')
        }),
        ('Additional', {
            'fields': ('notes',)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset().select_related(
            'driver', 'vehicle', 'booking', 'booking__booking_customer'
        )



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


# =============================================================================
# PAYMENT ADMIN
# =============================================================================
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    form = PaymentAdminForm
    list_display = ('id', 'guest_full_name', 'guest_email', 'tour', 'amount', 'status', 'paid_on')
    list_filter = ('status', 'provider', 'created_at', 'paid_on')
    search_fields = ('reference', 'guest_full_name', 'guest_email', 'tour__title')
    readonly_fields = ('amount_paid', 'is_successful', 'payer_email')
    actions = [mark_as_completed, resend_confirmation_emails]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'tour', 'booking', 'user', 'booking__booking_customer'
        )

    # --- Safe list_display methods ---
    def get_customer_name(self, obj):
        if obj.booking and obj.booking.booking_customer:
            return obj.booking.booking_customer.full_name
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
        if hasattr(response, "context_data"):
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
        pending_payments = Payment.objects.filter(status=PaymentStatus.PENDING)
        updated_count = 0

        for payment in pending_payments:
            if payment.reference:
                try:
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
            "fields": ("user", "booking_customer", "guest_full_name", "guest_email", "guest_phone")
        }),
        ("Booking/Tour Information", {
            "fields": ("booking", "tour", "travel_date")
        }),
        ("Passenger Details", {
            "fields": ("adults", "children", "days")
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
        ("Refund Information", {
            "fields": ("refund_reference", "refund_amount", "refund_reason", "refunded_on")
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("paid_on", "created_at", "updated_at")
        }),
    )

# =============================================================================
# REVIEW ADMIN
# =============================================================================
@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('get_booking_customer', 'review_target_name', 'rating', 'is_public', 'is_verified', 'created_at')
    list_filter = ('rating', 'is_public', 'is_verified', 'created_at')
    search_fields = ('booking_customer__full_name', 'title', 'comment')
    readonly_fields = ('average_detailed_rating', 'review_target', 'review_target_name')

    fieldsets = (
        ('Review Information', {
            'fields': ('booking', 'tour', 'driver', 'rating', 'title', 'comment')
        }),
        ('Detailed Ratings', {
            'fields': ('safety_rating', 'cleanliness_rating', 'value_rating', 'comfort_rating', 'punctuality_rating')
        }),
        ('Status', {
            'fields': ('is_public', 'is_verified', 'verified_at')
        }),
        ('Response', {
            'fields': ('response', 'responded_at', 'responded_by')
        }),
    )

    def get_booking_customer(self, obj):
        return obj.booking.booking_customer.full_name if obj.booking and obj.booking.booking_customer else "Unknown"

    get_booking_customer.short_description = "Booking Customer"

    def get_queryset(self, request):
        return super().get_queryset().select_related(
            'booking', 'booking__booking_customer', 'tour', 'driver'
        )

    actions = ["mark_as_verified"]

    def mark_as_verified(self, request, queryset):
        count = queryset.update(is_verified=True, verified_at=timezone.now())
        self.message_user(request, f"{count} reviews marked as verified.")

    mark_as_verified.short_description = "Mark selected reviews as verified"


# =============================================================================
# CONTACT MESSAGE ADMIN
# =============================================================================
@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'inquiry_type', 'priority', 'is_resolved', 'created_at')
    list_filter = ('inquiry_type', 'priority', 'is_resolved', 'assigned_to')
    search_fields = ('name', 'email', 'subject', 'message')
    readonly_fields = ('is_assigned', 'is_overdue')

    fieldsets = (
        ('Message Information', {
            'fields': ('name', 'email', 'phone', 'inquiry_type', 'subject', 'message')
        }),
        ('Status', {
            'fields': ('priority', 'is_resolved', 'assigned_to', 'resolved_by', 'resolved_at')
        }),
        ('Additional', {
            'fields': ('ip_address', 'created_at')
        }),
    )

    def mark_as_resolved(self, request, queryset):
        updated = queryset.update(is_resolved=True, resolved_by=request.user, resolved_at=timezone.now())
        self.message_user(request, f"{updated} messages marked as resolved.")

    mark_as_resolved.short_description = "Mark selected messages as resolved"

    def assign_to_me(self, request, queryset):
        updated = queryset.update(assigned_to=request.user)
        self.message_user(request, f"{updated} messages assigned to you.")

    assign_to_me.short_description = "Assign selected messages to me"

    def is_assigned(self, obj):
        return bool(obj.assigned_to)

    is_assigned.boolean = True
    is_assigned.short_description = "Assigned"


# =============================================================================
# BOOKING CUSTOMER ADMIN
# =============================================================================
@admin.register(BookingCustomer)
class BookingCustomerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'normalized_phone', 'travel_date', 'created_at')
    list_filter = ('country_code', 'created_at')
    search_fields = ('full_name', 'email', 'normalized_phone')