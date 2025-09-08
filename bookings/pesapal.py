import requests
from requests_oauthlib import OAuth1
from django.conf import settings

# Choose sandbox or live
BASE_URL = settings.PESAPAL_BASE_URL

def get_iframe_src(order_id, amount, description, email, phone):
    """
    Create a Pesapal order request and return iframe URL
    """

    url = f"{BASE_URL}/api/PostPesapalDirectOrderV4"

    # OAuth1 signing
    auth = OAuth1(
        settings.PESAPAL_CONSUMER_KEY,
        settings.PESAPAL_CONSUMER_SECRET,
        signature_method='HMAC-SHA1'
    )

    # Payload as required by Pesapal
    payload = {
        "Amount": str(amount),
        "Description": description,
        "Type": "MERCHANT",
        "Reference": str(order_id),
        "Currency": "KES",
        "Email": email,
        "PhoneNumber": phone,
        "CallbackUrl": settings.PESAPAL_CALLBACK_URL,
    }

    response = requests.post(url, data=payload, auth=auth)
    response.raise_for_status()

    return response.text  # This will be the iframe URL
