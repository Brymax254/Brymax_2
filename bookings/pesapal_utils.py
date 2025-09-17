import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def normalize_phone_number(phone: str) -> str:
    """Ensure phone numbers are in international format (+254...)."""
    phone = phone.strip().replace(" ", "")
    if phone.startswith("0"):
        phone = "+254" + phone[1:]
    elif not phone.startswith("+"):
        phone = "+254" + phone
    return phone


def get_access_token():
    """
    Authenticate with Pesapal and return an access token.
    """
    url = f"{settings.PESAPAL_BASE_URL}/api/Auth/RequestToken"

    payload = {
        "consumer_key": settings.PESAPAL_CONSUMER_KEY,
        "consumer_secret": settings.PESAPAL_CONSUMER_SECRET,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("token")
    except Exception as e:
        logger.error("Failed to get Pesapal token: %s", e)
        return None


def create_pesapal_order(order_id, amount, description, email, phone, first_name, last_name):
    """
    Create a Pesapal order.
    Returns: (redirect_url, order_reference, tracking_id)
    """
    token = get_access_token()
    if not token:
        return None, None, None

    url = f"{settings.PESAPAL_BASE_URL}/api/Transactions/SubmitOrderRequest"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "id": str(order_id),
        "amount": str(amount),
        "currency": "KES",
        "description": description,
        "callback_url": settings.PESAPAL_CALLBACK_URL,
        "notification_id": settings.PESAPAL_NOTIFICATION_ID,
        "billing_address": {
            "email_address": email,
            "phone_number": phone,
            "first_name": first_name,
            "last_name": last_name,
        },
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        return (
            data.get("redirect_url"),
            data.get("order_tracking_id"),
            data.get("order_tracking_id"),
        )
    except Exception as e:
        logger.error("Pesapal order creation failed: %s", e)
        return None, None, None
