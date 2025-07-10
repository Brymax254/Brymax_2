from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Notification

@login_required
def notification_list(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'notifications/list.html', {
        'notifications': notifications
    })

@login_required
def notification_detail(request, pk):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.mark_as_read()
    return render(request, 'notifications/detail.html', {
        'notification': notification
    })

@login_required
def mark_all_read(request):
    if request.method == 'POST':
        Notification.objects.filter(user=request.user, read=False).update(read=True)
    return redirect('notifications:list')

@login_required
def notification_preferences(request):
    if request.method == 'POST':
        # Update preferences
        pass
    return render(request, 'notifications/preferences.html')