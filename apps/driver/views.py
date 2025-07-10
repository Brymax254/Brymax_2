from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from .models import Driver
from .forms import DriverForm

class DriverListView(ListView):
    model = Driver
    template_name = 'driver/list.html'
    context_object_name = 'drivers'
    paginate_by = 10

class DriverCreateView(CreateView):
    model = Driver
    form_class = DriverForm
    template_name = 'driver/create.html'
    success_url = '/drivers/'

class DriverUpdateView(UpdateView):
    model = Driver
    form_class = DriverForm
    template_name = 'driver/update.html'
    success_url = '/drivers/'

class DriverDeleteView(DeleteView):
    model = Driver
    template_name = 'driver/confirm_delete.html'
    success_url = '/drivers/'

def driver_detail(request, pk):
    driver = get_object_or_404(Driver, pk=pk)
    return render(request, 'driver/detail.html', {'driver': driver})

def driver_schedule(request, pk):
    driver = get_object_or_404(Driver, pk=pk)
    schedule = []  # Get actual schedule later
    return render(request, 'driver/schedule.html', {
        'driver': driver,
        'schedule': schedule
    })

def driver_availability(request):
    if request.method == 'POST':
        # Process availability form
        pass
    return render(request, 'driver/availability.html')