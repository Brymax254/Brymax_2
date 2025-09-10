# bookings/pesapal.py
"""
Pesapal Payment Integration (v3 API)
Handles creating Pesapal orders and returning the redirect URL + tracking details.
"""

import uuid
import requests
from django.conf import settings


# Base URL for Pesapal environment (sandbox/live)
BASE_URL = settings.PESAPAL_BASE_URL


def create_pesapal_order(
    order_id,
    amount,
    description,
    email,
    phone,
    first_name,
    last_name,
):
    """
    Create a Pesapal order and return redirect URL, unique code, and order tracking ID.

    Parameters:
        order_id (str): Your internal order/ticket ID
        amount (Decimal/str): Payment amount
        description (str): Short description of the order
        email (str): User/guest email
        phone (str): User/guest phone
        first_name (str): First name of the payer
        last_name (str): Last name of the payer

    Returns:
        (redirect_url, unique_code, order_tracking_id)
    """

    # 1. Request authentication token
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

    # 3. Build order payload
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
            "first_name": first_name or "Guest",
            "last_name": last_name or "User",
            "country_code": "KE",
        },
    }

    # 4. Submit order
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
