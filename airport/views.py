from django.shortcuts import render
from .dashboard import CustomIndexDashboard

def modern_admin_dashboard(request):
    dashboard = CustomIndexDashboard()
    context = {
        "dashboard": dashboard,
    }
    return render(request, "admin/brymax_dashboard.html", context)
