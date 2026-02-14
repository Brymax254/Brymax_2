from django.urls import path
from . import views

app_name = "vehicles"

urlpatterns = [
    path('', views.vehicle_list, name='list'),  # List all vehicles
    path('add/', views.vehicle_add, name='add'),  # Add vehicle
    path('edit/<int:pk>/', views.vehicle_edit, name='edit'),  # Edit vehicle
    path('toggle-status/<int:pk>/', views.vehicle_toggle_status, name='toggle_status'),  # Activate/Deactivate
]
