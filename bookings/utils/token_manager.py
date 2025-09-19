import requests
import time
from django.conf import settings

# Simple in-memory token cache
TOKEN_CACHE = {"access_token": None, "expires_at": 0}

def get_pesapal_token():
    """
    Fetch or refresh a valid Pesapal token.
    """
    now = time.time()

    # Return cached token if still valid
    if TOKEN_CACHE["access_token"] and now < TOKEN_CACHE["expires_at"]:
        return TOKEN_CACHE["access_token"]

    url = "https://pay.pesapal.com/v3/api/Auth/RequestToken"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "consumer_key": settings.PESAPAL_CONSUMER_KEY,
        "consumer_secret": settings.PESAPAL_CONSUMER_SECRET,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        resp_data = response.json()

        token = resp_data.get("token")
        expires_in = resp_data.get("expires_in", 3600)

        if not token:
            raise ValueError("Pesapal response missing 'token' field")

        # Cache token with buffer to avoid expiry during use
        TOKEN_CACHE["access_token"] = token
        TOKEN_CACHE["expires_at"] = now + expires_in - 60

        return token

    except requests.exceptions.RequestException as e:
        raise Exception(f"Pesapal token request failed: {e}")
    except ValueError as ve:
        raise Exception(f"Invalid response from Pesapal: {ve}")
