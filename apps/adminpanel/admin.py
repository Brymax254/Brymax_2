from django.contrib import admin
from apps.client.models import Client
from apps.driver.models import Driver
from apps.payments.models import Payment
from apps.notifications.models import Notification

admin.site.register(Client)
admin.site.register(Driver)
admin.site.register(Payment)
admin.site.register(Notification)
