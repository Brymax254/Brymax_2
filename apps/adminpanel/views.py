from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.views.generic import TemplateView
from apps.client.models import Client
from apps.driver.models import Driver
from apps.payments.models import Payment


@staff_member_required
def dashboard(request):
    stats = {
        'total_clients': Client.objects.count(),
        'total_drivers': Driver.objects.count(),
        'recent_payments': Payment.objects.order_by('-created_at')[:5]
    }
    return render(request, 'adminpanel/dashboard.html', stats)

@staff_member_required
def reports(request):
    return render(request, 'adminpanel/reports.html')

@staff_member_required
def booking_reports(request):
    # Generate booking reports
    return render(request, 'adminpanel/booking_reports.html')

@staff_member_required
def payment_reports(request):
    # Generate payment reports
    return render(request, 'adminpanel/payment_reports.html')

@staff_member_required
def site_settings(request):
    if request.method == 'POST':
        # Update settings
        pass
    return render(request, 'adminpanel/settings.html')

@staff_member_required
def user_management(request):
    # User management logic
    return render(request, 'adminpanel/users.html')