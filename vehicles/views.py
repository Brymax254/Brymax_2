from django.shortcuts import render, get_object_or_404, redirect
from .models import Vehicle
from .forms import VehicleForm
from django.contrib import messages

from django.db.models import Q
from django.core.paginator import Paginator

def vehicle_list(request):
    vehicles = Vehicle.objects.all()

    # --- Filters ---
    vehicle_type = request.GET.get('vehicle_type')
    fuel_type = request.GET.get('fuel_type')
    is_active = request.GET.get('is_active')

    if vehicle_type and vehicle_type != 'all':
        vehicles = vehicles.filter(vehicle_type=vehicle_type)
    if fuel_type and fuel_type != 'all':
        vehicles = vehicles.filter(fuel_type=fuel_type)
    if is_active and is_active != 'all':
        vehicles = vehicles.filter(is_active=(is_active == 'True'))

    # --- Search ---
    search_query = request.GET.get('search')
    if search_query:
        vehicles = vehicles.filter(
            Q(make__icontains=search_query) |
            Q(model__icontains=search_query) |
            Q(license_plate__icontains=search_query)
        )

    # --- Pagination ---
    paginator = Paginator(vehicles.order_by('full_name'), 10)  # 10 vehicles per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get unique types for filter dropdowns
    vehicle_types = Vehicle.objects.values_list('vehicle_type', flat=True).distinct()
    fuel_types = Vehicle.objects.values_list('fuel_type', flat=True).distinct()

    context = {
        'page_obj': page_obj,
        'vehicle_types': vehicle_types,
        'fuel_types': fuel_types,
        'selected_vehicle_type': vehicle_type or 'all',
        'selected_fuel_type': fuel_type or 'all',
        'selected_is_active': is_active or 'all',
        'search_query': search_query or '',
    }
    return render(request, 'vehicles/vehicle_list.html', context)

# Toggle vehicle status (Activate/Deactivate)
def vehicle_toggle_status(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    vehicle.is_active = not vehicle.is_active
    vehicle.save()
    status = "activated" if vehicle.is_active else "deactivated"
    messages.success(request, f"Vehicle {status} successfully.")
    return redirect('vehicles:list')
