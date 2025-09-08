# bookings/pesapal.py
import uuid
import requests
from django.conf import settings

BASE_URL = settings.PESAPAL_BASE_URL


def create_pesapal_order(
    order_id,
    amount,
    description,
    email,
    phone,
    first_name="John",
    last_name="Doe",
):
    """
    Pesapal v3: Create order and return (redirect_url, unique_code, order_tracking_id)
    """

    # 1. Get access token
    auth_url = f"{BASE_URL}/api/Auth/RequestToken"
    auth_payload = {
        "consumer_key": settings.PESAPAL_CONSUMER_KEY,
        "consumer_secret": settings.PESAPAL_CONSUMER_SECRET,
    }
    token_res = requests.post(auth_url, json=auth_payload, timeout=15)
    token_res.raise_for_status()
    token_json = token_res.json()

    access_token = token_json.get("token") or token_json.get("access_token")
    if not access_token:
        raise ValueError(f"Invalid token response: {token_json}")

    # 2. Generate unique request ID
    unique_code = f"{order_id}-{uuid.uuid4().hex[:8]}"

    # 3. Submit order
    order_url = f"{BASE_URL}/api/Transactions/SubmitOrderRequest"
    headers = {"Authorization": f"Bearer {access_token}"}
    order_payload = {
        "id": unique_code,
        "currency": "KES",
        "amount": str(amount),
        "description": description,
        "callback_url": settings.PESAPAL_CALLBACK_URL,
        "notification_id": settings.PESAPAL_NOTIFICATION_ID,
        "billing_address": {
            "email_address": email,
            "phone_number": phone,
            "first_name": first_name,
            "last_name": last_name,
            "country_code": "KE",
        },
    }

    order_res = requests.post(
        order_url, json=order_payload, headers=headers, timeout=15
    )
    order_res.raise_for_status()
    order_data = order_res.json()

    redirect_url = order_data.get("redirect_url")
    order_tracking_id = order_data.get("order_tracking_id")

    if not redirect_url or not order_tracking_id:
        raise ValueError(f"Pesapal response invalid: {order_data}")

    return redirect_url, unique_code, order_tracking_id
