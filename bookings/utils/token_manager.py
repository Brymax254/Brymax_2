import requests, time
from django.conf import settings

TOKEN_CACHE = {"access_token": None, "expires_at": 0}

def get_pesapal_token():
    """
    Fetch or refresh a valid Pesapal token.
    """
    now = time.time()

    if TOKEN_CACHE["access_token"] and now < TOKEN_CACHE["expires_at"]:
        return TOKEN_CACHE["access_token"]

    url = "https://pay.pesapal.com/v3/api/Auth/RequestToken"
    data = {
        "consumer_key": settings.PESAPAL_CONSUMER_KEY,
        "consumer_secret": settings.PESAPAL_CONSUMER_SECRET,
    }
    response = requests.post(url, json=data)
    response.raise_for_status()
    resp_data = response.json()

    TOKEN_CACHE["access_token"] = resp_data["token"]
    TOKEN_CACHE["expires_at"] = now + (resp_data.get("expires_in", 3600) - 60)
    return TOKEN_CACHE["access_token"]
