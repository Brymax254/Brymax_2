from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.contrib.auth import login
from django.contrib import messages
from django.urls import reverse
from django.db.models import Sum, Avg
from django.http import HttpResponse
from django.core.management import call_command
from django.contrib.admin.views.decorators import staff_member_required
from urllib.parse import quote

from .forms import RideRequestForm, CustomUserCreationForm, RideRatingForm
from .models import RideRequest, CabType
from .utils import match_driver_to_ride


# -------------------- Home Page --------------------#
class HomeView(TemplateView):
    template_name = 'core/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Only load user-specific data if the user is authenticated
        if self.request.user.is_authenticated:
            user = self.request.user
            context['current_ride'] = RideRequest.objects.filter(user=user, status='REQUESTED').last()
            context['past_rides'] = RideRequest.objects.filter(user=user).exclude(status='REQUESTED')[:5]
            context['group_names'] = list(user.groups.values_list('name', flat=True))
        else:
            context['current_ride'] = None
            context['past_rides'] = []
            context['group_names'] = []

        context['featured_tours'] = []  # Replace with actual tour data
        return context


# -------------------- Request a Ride --------------------
@login_required
def request_ride(request):
    if request.method == 'POST':
        form = RideRequestForm(request.POST)
        if form.is_valid():
            ride = form.save(commit=False)
            ride.user = request.user
            ride.distance_km = 5.0  # Placeholder
            ride.save()
            match_driver_to_ride(ride)
            messages.success(request, "Your ride request has been submitted successfully!")
            return redirect('core:ride_detail', ride.id)
    else:
        form = RideRequestForm()
    return render(request, 'core/request_ride.html', {'form': form})


# -------------------- Ride Detail --------------------
@login_required
def ride_detail(request, ride_id):
    ride = get_object_or_404(RideRequest, id=ride_id, user=request.user)
    return render(request, 'core/ride_detail.html', {'ride': ride})


# -------------------- Cancel Ride --------------------
@login_required
def cancel_ride(request, ride_id):
    ride = get_object_or_404(RideRequest, id=ride_id, user=request.user)
    if ride.status == 'REQUESTED':
        ride.status = 'CANCELLED'
        ride.save()
    return redirect('core:home')


# -------------------- Static Pages --------------------
def about(request):
    return render(request, 'core/about.html')

def contact(request):
    if request.method == 'POST':
        pass  # Add contact form logic
    return render(request, 'core/contact.html')

def terms(request):
    return render(request, 'core/terms.html')

def privacy(request):
    return render(request, 'core/privacy.html')


# -------------------- Trip History --------------------
@login_required
def trip_history(request):
    trips = RideRequest.objects.filter(user=request.user).exclude(status='REQUESTED')
    context = {
        'trips': trips,
        'total_rides': trips.count(),
        'completed_rides': trips.filter(status='Completed').count(),
        'total_spent': trips.aggregate(Sum('estimated_fare'))['estimated_fare__sum'] or 0,
        'average_rating': trips.aggregate(Avg('rating'))['rating__avg'] or 0,
    }
    return render(request, 'core/ride_detail.html', context)


# -------------------- Register --------------------
def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('core:home')
    else:
        form = CustomUserCreationForm()
    return render(request, 'registration/register.html', {'form': form})


# -------------------- Profile Page --------------------
@login_required
def profile_view(request):
    return render(request, 'core/profile.html', {'user': request.user})


# -------------------- Rate Ride --------------------
@login_required
def rate_ride(request, ride_id):
    ride = get_object_or_404(RideRequest, id=ride_id, user=request.user)

    if request.method == 'POST':
        form = RideRatingForm(request.POST, instance=ride)
        if form.is_valid():
            form.save()
            return redirect('core:trip_history')
    else:
        form = RideRatingForm(instance=ride)

    return render(request, 'core/rate_ride.html', {'form': form, 'ride': ride})


# -------------------- Custom Login View --------------------
class CustomLoginView(LoginView):
    template_name = 'registration/login.html'

    def get_success_url(self):
        if self.request.user.is_staff:
            return reverse('admin:index')  # Admin panel
        return reverse('core:home')  # Normal users


# -------------------- Confirm Ride --------------------
@login_required
def confirm_ride(request):
    if request.method == 'POST':
        pickup = request.POST.get('pickup_location')
        dropoff = request.POST.get('dropoff_location')
        date = request.POST.get('pickup_time')
        cab = request.POST.get('cab_type')
        notes = request.POST.get('notes', '')

        user = request.user

        full_name = f"{user.first_name} {user.last_name}".strip() or user.username

        ride = RideRequest.objects.create(
            user=user,
            pickup_location=pickup,
            dropoff_location=dropoff,
            pickup_time=date,
            status='Pending',
            notes=notes,
            cab_type_id=cab
        )

        message = (
            f"🚗 NEW RIDE BOOKING\n"
            f"👤 Name: {full_name}\n"
            f"📞 Phone: {phone}\n"
            f"📍 Pickup: {pickup}\n"
            f"📍 Drop-off: {dropoff}\n"
            f"📅 Date/Time: {date}\n"
            f"🚕 Cab Type ID: {cab}\n"
            f"📝 Notes: {notes or 'None'}\n"
            f"Booking ID: #{ride.id}\n"
            f"Status: Pending"
        )

        whatsapp_url = f"https://api.whatsapp.com/send?phone=254759234580&text={quote(message)}"
        request.session['whatsapp_url'] = whatsapp_url
        return redirect('core:ride_detail', ride_id=ride.id)

    return redirect('core:home')


# -------------------- Run Migrations from View --------------------
@staff_member_required
def run_migrations(request):
    call_command('migrate')
    return HttpResponse("Migrations ran successfully.")
