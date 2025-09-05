import requests
import time
from django.conf import settings


class PesapalAuth:
    _token = None
    _expiry = 0  # when token expires (epoch timestamp)

    @classmethod
    def get_token(cls):
        """Get a valid bearer token (auto-refresh if expired)"""
        now = time.time()
        if cls._token and now < cls._expiry:
            return cls._token  # use cached token

        url = f"{settings.PESAPAL_BASE_URL}/api/Auth/RequestToken"
        payload = {
            "consumer_key": settings.PESAPAL_CONSUMER_KEY,
            "consumer_secret": settings.PESAPAL_CONSUMER_SECRET
        }

        response = requests.post(url, json=payload)
        data = response.json()

        if response.status_code == 200 and data.get("token"):
            cls._token = data["token"]
            # Token valid for 60 mins -> refresh at 55 mins
            cls._expiry = now + (55 * 60)
            return cls._token
        else:
            raise Exception(f"Pesapal Auth Error: {data}")


class PesapalAPI:
    @staticmethod
    def submit_order(order_data):
        """Submit a payment order to Pesapal"""
        token = PesapalAuth.get_token()
        url = f"{settings.PESAPAL_BASE_URL}/api/Transactions/SubmitOrderRequest"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=order_data, headers=headers)
        response.raise_for_status()
        return response.json()


def register_pesapal_ipn():
    """
    Registers the IPN URL with Pesapal.
    If `PESAPAL_NOTIFICATION_ID` already exists, Pesapal will just confirm it.
    """
    token = PesapalAuth.get_token()

    url = f"{settings.PESAPAL_BASE_URL}/api/URLSetup/RegisterIPN"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "url": settings.PESAPAL_IPN_URL,  # e.g. https://brymax.xyz/payments/ipn/
        "ipn_notification_type": "GET"
    }

    # ✅ Include existing IPN ID if defined
    if getattr(settings, "PESAPAL_NOTIFICATION_ID", None):
        payload["ipn_id"] = settings.PESAPAL_NOTIFICATION_ID

    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()
