from django.urls import path
from .views import (
    DriverListView,
    DriverCreateView,
    DriverUpdateView,
    DriverDeleteView,
    driver_detail,
    driver_schedule,
    driver_availability
)

urlpatterns = [
    path('', DriverListView.as_view(), name='list'),
    path('create/', DriverCreateView.as_view(), name='create'),
    path('<int:pk>/update/', DriverUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', DriverDeleteView.as_view(), name='delete'),
    path('<int:pk>/', driver_detail, name='detail'),
    path('<int:pk>/schedule/', driver_schedule, name='schedule'),
    path('availability/', driver_availability, name='availability'),
]
