from django.contrib import admin
from .models import CabType, AvailableCab, RideRequest

admin.site.register(CabType)
admin.site.register(RideRequest)
@admin.register(AvailableCab)
class AvailableCabAdmin(admin.ModelAdmin):
    list_display = ('cab_type', 'driver', 'license_plate', 'location', 'is_available', 'added_at')
    list_filter = ('is_available', 'cab_type')
    search_fields = ('license_plate', 'driver__user__username', 'location')