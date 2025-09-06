import requests
from django.conf import settings

BASE_URL = "https://pay.pesapal.com/v3/api"   # Sandbox: https://cybqa.pesapal.com/v3/api

def get_access_token():
    url = f"{BASE_URL}/Auth/RequestToken"
    data = {
        "consumer_key": settings.PESAPAL_CONSUMER_KEY,
        "consumer_secret": settings.PESAPAL_CONSUMER_SECRET
    }
    response = requests.post(url, json=data)
    return response.json()["token"]

def initiate_payment(order_id, amount, description, email, phone):
    token = get_access_token()
    url = f"{BASE_URL}/Transactions/SubmitOrderRequest"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "id": order_id,
        "currency": "KES",
        "amount": float(amount),
        "description": description,
        "callback_url": settings.PESAPAL_CALLBACK_URL,
        "billing_address": {
            "email_address": email,
            "phone_number": phone,
            "first_name": "Customer",
            "last_name": "Test"
        }
    }
    response = requests.post(url, json=payload, headers=headers)
    data = response.json()

    # Important: Extract iframe URL
    return data.get("redirect_url")
