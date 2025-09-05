import requests
from django.conf import settings

class PesapalAuth:
    @staticmethod
    def get_token():
        url = f"{settings.PESAPAL_BASE_URL}/api/Auth/RequestToken"
        payload = {
            "consumer_key": settings.PESAPAL_CONSUMER_KEY,
            "consumer_secret": settings.PESAPAL_CONSUMER_SECRET
        }

        response = requests.post(url, json=payload)
        response.raise_for_status()  # raise error if request fails
        return response.json()  # should return {"token": "...", "expiryDate": "..."}
