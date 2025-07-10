from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView
from .models import Payment

class PaymentListView(ListView):
    model = Payment
    template_name = 'payments/list.html'
    context_object_name = 'payments'
    paginate_by = 20

def payment_detail(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    return render(request, 'payments/detail.html', {'payment': payment})

def payment_receipt(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    return render(request, 'payments/receipt.html', {'payment': payment})

def payment_methods(request):
    return render(request, 'payments/methods.html')

def payment_webhook(request):
    if request.method == 'POST':
        # Process webhook
        pass
    return HttpResponse(status=200)