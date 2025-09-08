import requests
from django.conf import settings

BASE_URL = settings.PESAPAL_BASE_URL  # e.g. https://pay.pesapal.com/v3


def get_iframe_src(order_id, amount, description, email, phone):
    """
    Pesapal v3: Create order and return iframe URL
    """
    # 1. Get access token
    auth_url = f"{BASE_URL}/api/Auth/RequestToken"
    auth_payload = {
        "consumer_key": settings.PESAPAL_CONSUMER_KEY,
        "consumer_secret": settings.PESAPAL_CONSUMER_SECRET,
    }
    token_res = requests.post(auth_url, json=auth_payload, timeout=15)
    token_res.raise_for_status()
    access_token = token_res.json().get("token")

    # 2. Submit order
    order_url = f"{BASE_URL}/api/Transactions/SubmitOrderRequest"
    headers = {"Authorization": f"Bearer {access_token}"}
    order_payload = {
        "id": str(order_id),
        "currency": "KES",
        "amount": str(amount),
        "description": description,
        "callback_url": settings.PESAPAL_CALLBACK_URL,
        "notification_id": settings.PESAPAL_NOTIFICATION_ID,
        "billing_address": {
            "email_address": email,
            "phone_number": phone,
        },
    }
    order_res = requests.post(order_url, json=order_payload, headers=headers, timeout=15)
    order_res.raise_for_status()
    order_data = order_res.json()

    # Pesapal responds with { "redirect_url": "...", "order_tracking_id": "..." }
    redirect_url = order_data.get("redirect_url")
    if not redirect_url:
        raise ValueError(f"Pesapal response missing redirect_url: {order_data}")

    return redirect_url


