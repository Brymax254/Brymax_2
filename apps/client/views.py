from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from .models import Client
from .forms import ClientForm

class ClientListView(ListView):
    model = Client
    template_name = 'client/list.html'
    context_object_name = 'clients'
    paginate_by = 10

class ClientCreateView(CreateView):
    model = Client
    form_class = ClientForm
    template_name = 'client/create.html'
    success_url = '/clients/'

class ClientUpdateView(UpdateView):
    model = Client
    form_class = ClientForm
    template_name = 'client/update.html'
    success_url = '/clients/'

class ClientDeleteView(DeleteView):
    model = Client
    template_name = 'client/confirm_delete.html'
    success_url = '/clients/'

def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    return render(request, 'client/detail.html', {'client': client})

def client_bookings(request, pk):
    client = get_object_or_404(Client, pk=pk)
    bookings = []  # Get actual bookings later
    return render(request, 'client/bookings.html', {
        'client': client,
        'bookings': bookings
    })