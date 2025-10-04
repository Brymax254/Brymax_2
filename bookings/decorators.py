from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import redirect


def driver_required(view_func):
    """
    Decorator to ensure user is logged in and has a driver profile.
    - Staff/superusers → always allow access
    - Normal users → must have verified and available driver profile
    """
    @login_required
    def _wrapped(request, *args, **kwargs):
        user = request.user

        # Case 1: Staff/superusers get immediate access
        if user.is_staff or user.is_superuser:
            return view_func(request, *args, **kwargs)

        # Case 2: Check for driver profile
        if not hasattr(user, "driver_profile"):
            messages.error(request, "You are not registered as a driver.")
            return redirect("driver_login")

        driver = user.driver_profile

        # Case 3: Verify driver status
        if not driver.is_verified:
            messages.error(request, "Your driver account is not verified yet.")
            return redirect("driver_login")

        if not driver.available:
            messages.error(request, "Your driver account is currently unavailable.")
            return redirect("driver_login")

        # All checks passed - allow access
        return view_func(request, *args, **kwargs)

    return _wrapped