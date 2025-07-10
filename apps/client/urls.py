from django.urls import path
from .views import (
    ClientListView,
    ClientCreateView,
    ClientUpdateView,
    ClientDeleteView,
    client_detail,
    client_bookings
)

urlpatterns = [
    path('', ClientListView.as_view(), name='list'),
    path('create/', ClientCreateView.as_view(), name='create'),
    path('<int:pk>/update/', ClientUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', ClientDeleteView.as_view(), name='delete'),
    path('<int:pk>/', client_detail, name='detail'),
    path('<int:pk>/bookings/', client_bookings, name='bookings'),
]
