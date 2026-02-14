# vehicles/models.py
from django.db import models
from django.utils import timezone
from datetime import date


class Vehicle(models.Model):

    VEHICLE_TYPES = [
        ('Sedan', 'Sedan'),
        ('SUV', 'SUV'),
        ('Van', 'Van'),
        ('Bus', 'Bus'),
        ('Truck', 'Truck'),
    ]

    FUEL_TYPES = [
        ('Petrol', 'Petrol'),
        ('Diesel', 'Diesel'),
        ('Electric', 'Electric'),
        ('Hybrid', 'Hybrid'),
    ]

    # ================= BASIC INFO =================
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    year = models.PositiveIntegerField()
    color = models.CharField(max_length=50)
    license_plate = models.CharField(max_length=30, unique=True)

    vehicle_type = models.CharField(max_length=30, choices=VEHICLE_TYPES)
    fuel_type = models.CharField(max_length=30, choices=FUEL_TYPES)
    capacity = models.PositiveIntegerField(help_text="Number of passengers")

    # ================= IMAGES =================
    image = models.ImageField(upload_to='vehicles/', blank=True, null=True)
    external_image_url = models.URLField(blank=True, null=True)

    # ================= FEATURES =================
    features = models.TextField(blank=True)
    accessibility_features = models.TextField(blank=True)

    # ================= DOCUMENTS =================
    logbook_copy = models.FileField(upload_to='vehicle_docs/', blank=True, null=True)
    insurance_copy = models.FileField(upload_to='vehicle_docs/', blank=True, null=True)
    inspection_certificate = models.FileField(upload_to='vehicle_docs/', blank=True, null=True)

    insurance_expiry = models.DateField(blank=True, null=True)
    inspection_expiry = models.DateField(blank=True, null=True)

    # ================= STATUS =================
    is_active = models.BooleanField(default=True)

    # ================= SUSTAINABILITY =================
    carbon_footprint_per_km = models.DecimalField(
        max_digits=6, decimal_places=2, blank=True, null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # ================= COMPUTED PROPERTIES =================

    @property
    def full_name(self):
        return f"{self.make} {self.model} ({self.license_plate})"

    @property
    def vehicle_age(self):
        return date.today().year - self.year if self.year else None

    @property
    def documents_valid(self):
        today = timezone.now().date()
        return (
            self.insurance_expiry and self.insurance_expiry > today and
            self.inspection_expiry and self.inspection_expiry > today
        )

    @property
    def insurance_status(self):
        if not self.insurance_expiry:
            return "Missing"
        return "Valid" if self.insurance_expiry > timezone.now().date() else "Expired"

    @property
    def inspection_status(self):
        if not self.inspection_expiry:
            return "Missing"
        return "Valid" if self.inspection_expiry > timezone.now().date() else "Expired"

    def __str__(self):
        return self.full_name
