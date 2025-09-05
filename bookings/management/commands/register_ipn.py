import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from bookings.utils.token_manager import get_pesapal_token

class Command(BaseCommand):
    help = "Register or refresh Pesapal IPN URL automatically"

    def handle(self, *args, **kwargs):
        token = get_pesapal_token()

        url = "https://pay.pesapal.com/v3/api/URLSetup/RegisterIPN"
        headers = {"Authorization": f"Bearer {token}"}
        data = {
            "url": settings.PESAPAL_IPN_URL,
            "ipn_notification_type": "POST"
        }

        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        resp_data = response.json()

        ipn_id = resp_data.get("ipn_id")
        self.stdout.write(self.style.SUCCESS(f"✅ IPN Registered Successfully: {ipn_id}"))
