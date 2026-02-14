# =============================================================================
# IMPORTS
# =============================================================================
from rest_framework import serializers
from bookings.models import (
    Driver, BookingCustomer, Vehicle, Destination, TourCategory, Tour,
    Booking, Trip, Payment, PaymentStatus, Review, ContactMessage,
    PaymentProvider
)

# =============================================================================
# SIMPLE MODEL SERIALIZERS
# =============================================================================
class DestinationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Destination
        fields = '__all__'
        read_only_fields = ('slug',)


class TourCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TourCategory
        fields = '__all__'
        read_only_fields = ('slug',)

from rest_framework import serializers
from bookings.models import Vehicle

class VehicleSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    price_usd = serializers.ReadOnlyField()  # comes from @property on the model

    class Meta:
        model = Vehicle
        fields = [
            'id', 'make', 'model', 'year', 'color', 'license_plate',
            'vehicle_type', 'fuel_type', 'capacity', 'features',
            'accessibility_features', 'insurance_expiry', 'inspection_expiry',
            'is_active', 'carbon_footprint_per_km',
            'image_url', 'price_usd'
        ]
        read_only_fields = ('id',)

    def get_image_url(self, obj):
        request = self.context.get('request')

        # If image uploaded to MEDIA
        if getattr(obj, 'image', None):
            try:
                url = obj.image.url
            except Exception:
                url = None
            if url:
                return request.build_absolute_uri(url) if request else url

        # If using external URL
        if getattr(obj, 'external_image_url', None):
            return obj.external_image_url

        # Placeholder fallback
        placeholder = '/static/images/placeholder-vehicle.png'
        return request.build_absolute_uri(placeholder) if request else placeholder

class BookingCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingCustomer
        fields = '__all__'


# =============================================================================
# COMPLEX MODEL SERIALIZERS
# =============================================================================
class DriverSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    vehicle = VehicleSerializer(read_only=True)
    full_name = serializers.ReadOnlyField(source='user.get_full_name')
    age = serializers.ReadOnlyField()
    license_status = serializers.ReadOnlyField()
    license_status_text = serializers.ReadOnlyField()

    class Meta:
        model = Driver
        fields = '__all__'
        read_only_fields = ('normalized_phone', 'rating', 'total_trips', 'total_earnings')


class TourSerializer(serializers.ModelSerializer):
    category = TourCategorySerializer(read_only=True)
    destinations = DestinationSerializer(many=True, read_only=True)
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    approved_by = serializers.PrimaryKeyRelatedField(read_only=True)
    current_price = serializers.ReadOnlyField()
    has_discount = serializers.ReadOnlyField()
    discount_percentage = serializers.ReadOnlyField()
    total_duration = serializers.ReadOnlyField()
    primary_image = serializers.ImageField(source='get_image_src', read_only=True)

    class Meta:
        model = Tour
        fields = '__all__'
        read_only_fields = ('slug', 'is_approved', 'approved_at')


class BookingSerializer(serializers.ModelSerializer):
    booking_customer = BookingCustomerSerializer(read_only=True)
    destination = DestinationSerializer(read_only=True)
    tour = TourSerializer(read_only=True)
    driver = DriverSerializer(read_only=True)
    vehicle = VehicleSerializer(read_only=True)
    total_passengers = serializers.ReadOnlyField()
    is_upcoming = serializers.ReadOnlyField()
    is_past = serializers.ReadOnlyField()
    is_today = serializers.ReadOnlyField()
    can_be_cancelled = serializers.ReadOnlyField()
    service_name = serializers.ReadOnlyField()

    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ('booking_reference', 'total_price', 'carbon_offset_amount',
                            'is_paid', 'is_cancelled', 'booking_date')


class TripSerializer(serializers.ModelSerializer):
    driver = DriverSerializer(read_only=True)
    booking = BookingSerializer(read_only=True)
    vehicle = VehicleSerializer(read_only=True)
    duration = serializers.ReadOnlyField()
    fuel_efficiency = serializers.ReadOnlyField()

    class Meta:
        model = Trip
        fields = '__all__'


class PaymentSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    booking = BookingSerializer(read_only=True)
    tour = TourSerializer(read_only=True)
    is_successful = serializers.ReadOnlyField()
    payer_email = serializers.ReadOnlyField()

    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('id', 'normalized_guest_phone', 'amount_paid', 'paid_on',
                            'webhook_verified', 'webhook_received_at', 'refund_reference',
                            'refund_amount', 'refunded_on')


class ReviewSerializer(serializers.ModelSerializer):
    booking = BookingSerializer(read_only=True)
    tour = TourSerializer(read_only=True)
    driver = DriverSerializer(read_only=True)
    responded_by = serializers.PrimaryKeyRelatedField(read_only=True)
    review_target = serializers.SerializerMethodField()
    review_target_name = serializers.SerializerMethodField()
    average_detailed_rating = serializers.ReadOnlyField()
    get_rating_text = serializers.ReadOnlyField()

    class Meta:
        model = Review
        fields = '__all__'
        read_only_fields = ('is_verified', 'verified_at', 'responded_at')

    def get_review_target(self, obj):
        if obj.tour:
            return TourSerializer(obj.tour).data
        elif obj.driver:
            return DriverSerializer(obj.driver).data
        return None

    def get_review_target_name(self, obj):
        return obj.review_target_name


class ContactMessageSerializer(serializers.ModelSerializer):
    resolved_by = serializers.PrimaryKeyRelatedField(read_only=True)
    assigned_to = serializers.PrimaryKeyRelatedField(read_only=True)
    is_assigned = serializers.ReadOnlyField()
    is_overdue = serializers.ReadOnlyField()

    class Meta:
        model = ContactMessage
        fields = '__all__'
        read_only_fields = ('resolved_at',)


# =============================================================================
# CHOICE SERIALIZERS
# =============================================================================
class PaymentProviderSerializer(serializers.Serializer):
    value = serializers.CharField()
    display_name = serializers.CharField()


class PaymentStatusSerializer(serializers.Serializer):
    value = serializers.CharField()
    display_name = serializers.CharField()


# =============================================================================
# NESTED SERIALIZERS FOR CREATE/UPDATE OPERATIONS
# =============================================================================
class NestedDestinationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Destination
        fields = ('id', 'name', 'slug')


class NestedTourCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TourCategory
        fields = ('id', 'name', 'slug')


class NestedVehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = ('id', 'make', 'model', 'license_plate')


class NestedDriverSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = ('id', 'user', 'license_number', 'rating')


class NestedBookingCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingCustomer
        fields = ('id', 'full_name', 'email', 'phone_number')


class NestedTourSerializer(serializers.ModelSerializer):
    category = NestedTourCategorySerializer(read_only=True)

    class Meta:
        model = Tour
        fields = ('id', 'title', 'slug', 'category', 'price_per_person', 'discount_price')


class NestedBookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = ('id', 'booking_reference', 'travel_date', 'status', 'total_price')


class NestedTripSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = ('id', 'date', 'status', 'earnings')


class NestedPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ('id', 'reference', 'amount', 'status', 'paid_on')


class NestedReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ('id', 'rating', 'title', 'is_verified')


# =============================================================================
# CREATE/UPDATE SERIALIZERS
# =============================================================================
class BookingCreateSerializer(serializers.ModelSerializer):
    destination_id = serializers.IntegerField(required=False)
    tour_id = serializers.IntegerField(required=False)

    class Meta:
        model = Booking
        fields = ('booking_customer', 'destination_id', 'tour_id', 'booking_type',
                  'num_adults', 'num_children', 'num_infants', 'pickup_location',
                  'dropoff_location', 'travel_date', 'travel_time', 'return_date',
                  'return_time', 'special_requests', 'notes', 'carbon_offset_option')

    def validate(self, data):
        if not data.get('destination_id') and not data.get('tour_id'):
            raise serializers.ValidationError("Either destination_id or tour_id must be provided.")
        return data


class PaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ('user', 'guest_full_name', 'guest_email', 'guest_phone', 'booking',
                  'tour', 'travel_date', 'adults', 'children', 'days', 'provider',
                  'method', 'currency', 'amount', 'description', 'phone_number')


class ReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ('booking', 'tour', 'driver', 'rating', 'safety_rating',
                  'cleanliness_rating', 'value_rating', 'comfort_rating',
                  'punctuality_rating', 'title', 'comment', 'is_public')

    def validate(self, data):
        if not data.get('tour') and not data.get('driver'):
            raise serializers.ValidationError("Either tour or driver must be provided.")
        return data


class DriverCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = ('user', 'phone_number', 'gender', 'date_of_birth', 'nationality',
                  'bio', 'preferred_language', 'communication_preferences',
                  'license_number', 'license_type', 'license_expiry', 'experience_years',
                  'bank_name', 'bank_account', 'bank_branch', 'payment_methods')


class TourCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tour
        fields = ('title', 'tagline', 'description', 'highlights', 'itinerary',
                  'inclusions', 'exclusions', 'price_per_person', 'discount_price',
                  'currency', 'duration_days', 'duration_nights', 'max_group_size',
                  'min_group_size', 'difficulty', 'category', 'departure_point',
                  'destinations_visited', 'eco_friendly', 'carbon_footprint_per_person',
                  'sustainability_certifications', 'wheelchair_accessible',
                  'accessibility_features', 'health_safety_measures', 'covid19_protocols')


class VehicleCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = ('make', 'model', 'year', 'color', 'license_plate', 'vehicle_type',
                  'fuel_type', 'capacity', 'features', 'accessibility_features',
                  'insurance_expiry', 'inspection_expiry', 'carbon_footprint_per_km')