from django.urls import path
from .views import (
    PaymentListView,
    payment_detail,
    payment_receipt,
    payment_methods,
    payment_webhook
)

urlpatterns = [
    path('', PaymentListView.as_view(), name='list'),
    path('<int:pk>/', payment_detail, name='detail'),
    path('<int:pk>/receipt/', payment_receipt, name='receipt'),
    path('methods/', payment_methods, name='methods'),
    path('webhook/', payment_webhook, name='webhook'),
]
