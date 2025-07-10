from apps.driver.models import Driver
from .models import RideRequest
import time

def match_driver_to_ride(ride: RideRequest):
    available_drivers = Driver.objects.filter(is_available=True)

    for driver in available_drivers:
        # Simulate asking driver
        accepted = simulate_driver_response(driver, ride)

        if accepted:
            ride.assigned_driver = driver
            ride.status = 'ASSIGNED'
            ride.save()
            driver.is_available = False
            driver.save()
            return driver
        else:
            time.sleep(1)  # wait before trying next
    return None

def simulate_driver_response(driver, ride):
    """
    Simulate waiting 60 seconds for response (fake for now).
    In real world, use WebSockets or polling with mobile app.
    """
    # For testing, assume driver always accepts after 5 sec
    time.sleep(5)
    return True  # Later, make it dynamic or async
