import uuid
import hmac
import hashlib
import base64
import json
import time
import logging
import requests
from requests.auth import HTTPBasicAuth
from django.conf import settings
from django.utils import timezone
from airport.utils import normalize_phone_number  # your helper for phone formatting

logger = logging.getLogger(__name__)

# =============================================================================
# PAYSTACK SERVICE
# =============================================================================
class PaystackService:
    """
    Handles Paystack API calls for transaction initialization, verification, and refunds.
    """

    base_url = "https://api.paystack.co"

    def initialize_transaction(self, payment, callback_url, metadata=None):
        """Initialize a Paystack transaction."""
        try:
            reference = f"PY-{uuid.uuid4().hex[:10]}"
            payload = {
                "email": payment.guest_email,
                "amount": int(payment.amount * 100),  # convert KES to cents
                "reference": reference,
                "callback_url": callback_url,
                "metadata": metadata or {}
            }

            headers = {
                "Authorization": f"Bearer {settings.PAYSTACK['SECRET_KEY']}",
                "Content-Type": "application/json"
            }

            response = requests.post(
                f"{self.base_url}/transaction/initialize",
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            return response.json(), reference

        except requests.exceptions.RequestException as e:
            logger.error("Paystack initialization error: %s", e, exc_info=True)
            return {"status": False, "message": str(e)}, None

    def verify_transaction(self, reference):
        """Verify a Paystack transaction."""
        try:
            headers = {"Authorization": f"Bearer {settings.PAYSTACK['SECRET_KEY']}"}
            response = requests.get(
                f"{self.base_url}/transaction/verify/{reference}",
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error("Paystack verification error: %s", e, exc_info=True)
            return {"status": False, "message": str(e)}

    def initiate_refund(self, reference, amount=None, reason="Refund"):
        """Initiate a refund on a successful transaction."""
        try:
            headers = {"Authorization": f"Bearer {settings.PAYSTACK['SECRET_KEY']}"}
            payload = {"transaction": reference, "amount": int(amount * 100) if amount else None, "reason": reason}
            response = requests.post(
                f"{self.base_url}/refund",
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error("Paystack refund error: %s", e, exc_info=True)
            return {"status": False, "message": str(e)}


# =============================================================================
# PAYMENT SESSION MANAGER
# =============================================================================
class PaymentSessionManager:
    """
    Manage pending payments in Django sessions.
    """

    SESSION_KEY = "pending_payment_id"

    def __init__(self, session):
        self.session = session

    def set_pending_payment(self, payment):
        self.session[self.SESSION_KEY] = str(payment.id)
        self.session.modified = True

    def get_pending_payment(self):
        from .models import Payment
        payment_id = self.session.get(self.SESSION_KEY)
        if payment_id:
            try:
                return Payment.objects.get(id=payment_id)
            except Payment.DoesNotExist:
                return None
        return None

    def clear_payment_session(self):
        self.session.pop(self.SESSION_KEY, None)
        self.session.modified = True

    def has_pending_payment(self):
        """Return True if there is a pending payment in session."""
        payment = self.get_pending_payment()
        return payment is not None and payment.status in ["pending", "failed"]


# =============================================================================
# M-PESA STK PUSH (Optional)
# =============================================================================
class MpesaSTKPush:
    """Handle M-PESA STK Push integration."""

    def __init__(self):
        self.consumer_key = settings.MPESA_CONSUMER_KEY
        self.consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.shortcode = settings.MPESA_SHORTCODE
        self.passkey = settings.MPESA_PASSKEY
        self.callback_url = settings.MPESA_CALLBACK_URL
        self.token = None
        self.token_expiry = None

        if settings.MPESA_ENV == "production":
            self.auth_url = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
            self.stk_url = "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
            self.query_url = "https://api.safaricom.co.ke/mpesa/stkpushquery/v1/query"
        else:
            self.auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
            self.stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
            self.query_url = "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query"

    def _get_auth_token(self):
        if self.token and self.token_expiry and self.token_expiry > timezone.now():
            return self.token
        try:
            response = requests.get(
                self.auth_url,
                auth=HTTPBasicAuth(self.consumer_key, self.consumer_secret),
                timeout=30
            )
            response.raise_for_status()
            token_data = response.json()
            self.token = token_data.get("access_token")
            self.token_expiry = timezone.now() + timezone.timedelta(minutes=55)
            return self.token
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get M-Pesa auth token: {str(e)}")

    def _generate_timestamp(self):
        return time.strftime("%Y%m%d%H%M%S")

    def _generate_password(self, timestamp):
        data = f"{self.shortcode}{self.passkey}{timestamp}"
        return base64.b64encode(data.encode()).decode()

    def stk_push(self, phone_number, amount, account_reference, transaction_desc):
        normalized_phone = normalize_phone_number(phone_number).lstrip('+')
        token = self._get_auth_token()
        timestamp = self._generate_timestamp()
        password = self._generate_password(timestamp)

        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": normalized_phone,
            "PartyB": self.shortcode,
            "PhoneNumber": normalized_phone,
            "CallBackURL": self.callback_url,
            "AccountReference": account_reference,
            "TransactionDesc": transaction_desc
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(self.stk_url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def check_stk_status(self, checkout_request_id):
        token = self._get_auth_token()
        timestamp = self._generate_timestamp()
        password = self._generate_password(timestamp)
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(self.query_url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
