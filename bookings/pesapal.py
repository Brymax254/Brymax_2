"""
Pesapal Payment Integration (v3 API)
Handles creating Pesapal orders and returning the redirect URL + tracking details.
"""

import uuid
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# Base URL for Pesapal environment (sandbox/live)
BASE_URL = settings.PESAPAL_BASE_URL


def normalize_phone_number(phone: str) -> str:
    """
    Convert phone numbers to international format (+254...).
    """
    if not phone:
        return "+254700000000"
    phone = phone.strip().replace(" ", "")
    if phone.startswith("0"):
        phone = "+254" + phone[1:]
    elif not phone.startswith("+"):
        phone = "+254" + phone
    return phone

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
    Create a Pesapal order and return (redirect_url, merchant_ref, order_tracking_id).

    Relies on these settings:
      - PESAPAL_BASE_URL        e.g. "https://pay.pesapal.com"
      - PESAPAL_CONSUMER_KEY
      - PESAPAL_CONSUMER_SECRET
      - PESAPAL_IPN_URL         your callback endpoint
      - PESAPAL_NOTIFICATION_ID configured in your .env
    """

    base_url = settings.PESAPAL_BASE_URL.rstrip("/")
    token_url = f"{base_url}/api/Auth/RequestToken"

    # 1) Authenticate
    auth_payload = {
        "consumer_key":    settings.PESAPAL_CONSUMER_KEY,
        "consumer_secret": settings.PESAPAL_CONSUMER_SECRET,
    }
    try:
        r = requests.post(token_url, json=auth_payload, timeout=15)
        r.raise_for_status()
        token_data = r.json()
    except Exception as e:
        logger.error("Pesapal Auth failed: %s", e, exc_info=True)
        raise

    access_token = token_data.get("token") or token_data.get("access_token")
    if not access_token:
        raise ValueError(f"Invalid auth token response: {token_data}")

    # 2) Build order
    merchant_ref    = f"{order_id}-{uuid.uuid4().hex[:8]}"
    order_url       = f"{base_url}/api/Transactions/SubmitOrderRequest"
    headers         = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
    }
    order_payload = {
        "id":               merchant_ref,
        "currency":         "KES",
        "amount":           str(amount),
        "description":      description,
        "callback_url":     settings.PESAPAL_IPN_URL,
        "notification_id":  settings.PESAPAL_NOTIFICATION_ID,
        "billing_address": {
            "email_address": email or "guest@brymax.xyz",
            "phone_number":  normalize_phone_number(phone) or phone,
            "first_name":    first_name or "Guest",
            "last_name":     last_name or "User",
            "country_code":  "KE",
        },
    }

    logger.debug("Submitting Pesapal order payload: %s", order_payload)

    # 3) Submit order
    try:
        r2 = requests.post(order_url, json=order_payload, headers=headers, timeout=15)
        r2.raise_for_status()
        order_data = r2.json()
    except Exception as e:
        logger.error("Pesapal order creation failed: %s", e, exc_info=True)
        raise

    # 4) Extract redirect URL and tracking ID
    # handle snake_case or CamelCase keys
    redirect_url       = order_data.get("redirect_url")       or order_data.get("RedirectURL")
    order_tracking_id  = order_data.get("order_tracking_id")  or order_data.get("OrderTrackingId")
    logger.info("Pesapal order response: %s", order_data)

    if not redirect_url or not order_tracking_id:
        raise ValueError(f"Invalid Pesapal response: {order_data}")

    return redirect_url, merchant_ref, order_tracking_id