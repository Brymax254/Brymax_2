from apps.driver.models import Driver
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class CabType(models.Model):
    name = models.CharField(max_length=50)
    base_fare = models.DecimalField(max_digits=6, decimal_places=2)
    per_km_rate = models.DecimalField(max_digits=6, decimal_places=2)

    def __str__(self):
        return self.name

class RideRequest(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('ASSIGNED', 'Driver Assigned'),
        ('CANCELLED', 'Cancelled'),
        ('COMPLETED', 'Completed')
    ]

    assigned_driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    cab_type = models.ForeignKey(CabType, on_delete=models.CASCADE)
    pickup_location = models.CharField(max_length=255)
    rating = models.FloatField(null=True, blank=True)
    dropoff_location = models.CharField(max_length=255)
    pickup_time = models.DateTimeField(null=True, blank=True)  # ✅ New field
    notes = models.TextField(null=True, blank=True)            # ✅ New field
    distance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_fare =models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.pickup_location} to {self.dropoff_location}"


class AvailableCab(models.Model):
    cab_type = models.ForeignKey(CabType, on_delete=models.CASCADE)
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE)
    license_plate = models.CharField(max_length=20)
    location = models.CharField(max_length=255)
    is_available = models.BooleanField(default=True)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.cab_type.name} - {self.license_plate} ({'Available' if self.is_available else 'Unavailable'})"
