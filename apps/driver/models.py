from django.db import models

class Driver(models.Model):
    full_name = models.CharField(max_length=120)
    license_no = models.CharField(max_length=50, unique=True)
    phone = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    current_location = models.CharField(max_length=255, blank=True, null=True)
    is_available = models.BooleanField(default=True)

    def __str__(self):
        return self.full_name
