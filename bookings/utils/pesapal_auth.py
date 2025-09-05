import requests
from django.conf import settings
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)

# Cache key and TTL (seconds). TTL slightly less than 5 minutes.
PESAPAL_TOKEN_CACHE_KEY = "pesapal_token"
PESAPAL_TOKEN_TTL = 240  # 4 minutes

class PesapalAuth:
    @staticmethod
    def get_token(force_refresh: bool = False) -> str:
        """
        Return a valid Pesapal bearer token.
        Uses Django cache (Redis/memcached or local-memory) to share tokens across processes.
        If force_refresh=True, a fresh token is requested regardless of cache.
        """
        if not force_refresh:
            token = cache.get(PESAPAL_TOKEN_CACHE_KEY)
            if token:
                return token

        url = f"{settings.PESAPAL_BASE_URL}/api/Auth/RequestToken"
        payload = {
            "consumer_key": settings.PESAPAL_CONSUMER_KEY,
            "consumer_secret": settings.PESAPAL_CONSUMER_SECRET
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
        except requests.RequestException as e:
            logger.exception("Network error requesting Pesapal token")
            raise RuntimeError(f"Network error requesting Pesapal token: {e}")

        # Log status for debugging (but avoid logging token)
        logger.debug("Pesapal auth response status: %s", resp.status_code)

        # If non-JSON response or error, include raw text in the exception for debugging
        try:
            data = resp.json()
        except ValueError:
            logger.error("Pesapal returned non-json response: %s", resp.text)
            raise RuntimeError(f"Invalid response from Pesapal auth endpoint: {resp.status_code}")

        # Token key may be 'token' (common) — handle variants defensively
        token = data.get("token") or data.get("access_token") or data.get("Token")
        if not token:
            logger.error("Pesapal auth returned no token: %s", data)
            raise RuntimeError(f"Pesapal auth error: {data}")

        # Store token in cache for PESAPAL_TOKEN_TTL seconds
        cache.set(PESAPAL_TOKEN_CACHE_KEY, token, PESAPAL_TOKEN_TTL)
        return token
