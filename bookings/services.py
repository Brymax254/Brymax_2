import uuid
import hmac
import hashlib
import base64
import json
import time
from urllib.parse import urlencode, quote_plus
from django.conf import settings
import requests
from requests.auth import HTTPBasicAuth
from django.utils import timezone
from airport.utils import normalize_phone_number  # Import from utils
import logging

logger = logging.getLogger(__name__)

class PesaPalService:
    """
    Service class for handling Pesapal API operations
    """

    def __init__(self):
        self.base_url = settings.PESAPAL_BASE_URL
        self.consumer_key = settings.PESAPAL_CONSUMER_KEY
        self.consumer_secret = settings.PESAPAL_CONSUMER_SECRET
        self.token = None
        self.token_expiry = None

    def _get_auth_token(self):
        """Get authentication token from PesaPal (required for v3 API)"""
        # Check if we have a valid token
        if self.token and self.token_expiry and self.token_expiry > timezone.now():
            return self.token

        auth_url = f"{self.base_url}/api/Auth/RequestToken"
        payload = {
            "consumer_key": self.consumer_key,
            "consumer_secret": self.consumer_secret
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        try:
            response = requests.post(auth_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            token_data = response.json()
            self.token = token_data.get("token")

            # Set token expiry (typically 1 hour, but we'll use 55 minutes to be safe)
            self.token_expiry = timezone.now() + timezone.timedelta(minutes=55)

            return self.token

        except requests.exceptions.RequestException as e:
            logger.error("Pesapal Auth failed: %s", e, exc_info=True)
            raise Exception(f"Failed to get PesaPal auth token: {str(e)}")

    def _generate_oauth_nonce(self):
        """Generate a unique nonce for OAuth"""
        return str(uuid.uuid4()).replace('-', '')

    def _generate_oauth_timestamp(self):
        """Generate current timestamp for OAuth"""
        return str(int(time.time()))

    def create_order(self, order_data):
        """
        Create a Pesapal order using the provided order data

        Args:
            order_data (dict): Contains order details including:
                - order_id: Unique identifier for the order
                - amount: Payment amount
                - description: Order description
                - email: Customer email
                - phone: Customer phone
                - first_name: Customer first name
                - last_name: Customer last name

        Returns:
            dict: Response with redirect_url, merchant_ref, and order_tracking_id
        """
        try:
            # Get authentication token
            token = self._get_auth_token()

            # Prepare order data
            merchant_ref = f"{order_data.get('order_id', str(uuid.uuid4()))}-{uuid.uuid4().hex[:8]}"
            order_url = f"{self.base_url}/api/Transactions/SubmitOrderRequest"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            # Normalize phone number
            from airport.utils import normalize_phone_number
            normalized_phone = normalize_phone_number(order_data.get('phone', ''))

            order_payload = {
                "id": merchant_ref,
                "currency": "KES",
                "amount": str(order_data.get('amount', 0)),
                "description": order_data.get('description', 'Safari Booking'),
                "callback_url": settings.PESAPAL_IPN_URL,
                "notification_id": settings.PESAPAL_NOTIFICATION_ID,
                "billing_address": {
                    "email_address": order_data.get('email', 'guest@brymax.xyz'),
                    "phone_number": normalized_phone,
                    "first_name": order_data.get('first_name', 'Guest'),
                    "last_name": order_data.get('last_name', 'User'),
                    "country_code": "KE",
                },
            }

            logger.debug("Submitting Pesapal order payload: %s", order_payload)

            # Submit order
            response = requests.post(order_url, json=order_payload, headers=headers, timeout=30)
            response.raise_for_status()
            order_response = response.json()

            # Extract redirect URL and tracking ID
            # handle snake_case or CamelCase keys
            redirect_url = order_response.get("redirect_url") or order_response.get("RedirectURL")
            order_tracking_id = order_response.get("order_tracking_id") or order_response.get("OrderTrackingId")
            logger.info("Pesapal order response: %s", order_response)

            if not redirect_url or not order_tracking_id:
                logger.error("Invalid Pesapal response: %s", order_response)
                raise ValueError(f"Invalid Pesapal response: {order_response}")

            return {
                'success': True,
                'redirect_url': redirect_url,
                'merchant_ref': merchant_ref,
                'order_tracking_id': order_tracking_id
            }

        except Exception as e:
            logger.error("Error creating Pesapal order: %s", str(e), exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def initiate_payment(self, amount, description, callback_url, email=None, phone=None, first_name=None,
                         last_name=None):
        """Initiate payment using Pesapal API v3"""
        try:
            token = self._get_auth_token()

            # Normalize phone number
            from airport.utils import normalize_phone_number
            normalized_phone = normalize_phone_number(phone)

            # Prepare order data
            order_data = {
                "currency": "KES",
                "amount": amount,
                "description": description,
                "callback_url": callback_url,
                "notification_id": settings.PESAPAL_NOTIFICATION_ID,
                "billing_address": {
                    "email_address": email or "",
                    "phone_number": normalized_phone,
                    "country_code": "KE",
                    "first_name": first_name or "",
                    "middle_name": "",
                    "last_name": last_name or "",
                    "line_1": "",
                    "line_2": "",
                    "city": "",
                    "state": "",
                    "postal_code": "",
                    "zip_code": ""
                }
            }

            submit_order_url = f"{self.base_url}/api/Transactions/SubmitOrderRequest"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            response = requests.post(submit_order_url, json=order_data, headers=headers, timeout=30)
            response.raise_for_status()
            order_response = response.json()

            return {
                "order_tracking_id": order_response.get("order_tracking_id"),
                "iframe_url": order_response.get("redirect_url")
            }

        except requests.exceptions.RequestException as e:
            # In production, we don't want to fallback to v2 because it's deprecated and less secure.
            # Instead, we should log the error and raise an exception.
            logger.error("Pesapal v3 API failed: %s", e, exc_info=True)
            raise Exception(f"PesaPal payment initiation failed: {str(e)}")

    def check_payment_status(self, order_tracking_id):
        """Check payment status using PesaPal API v3"""
        try:
            token = self._get_auth_token()

            status_url = f"{self.base_url}/api/Transactions/GetTransactionStatus"
            params = {
                "orderTrackingId": order_tracking_id
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }

            response = requests.get(status_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error("Pesapal status check failed: %s", e, exc_info=True)
            raise Exception(f"PesaPal status check failed: {str(e)}")

class MpesaSTKPush:
    """Handle M-PESA STK Push with proper API integration"""

    def __init__(self):
        self.consumer_key = settings.MPESA_CONSUMER_KEY
        self.consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.shortcode = settings.MPESA_SHORTCODE
        self.passkey = settings.MPESA_PASSKEY
        self.callback_url = settings.MPESA_CALLBACK_URL
        self.token = None
        self.token_expiry = None

        # Determine base URL based on environment
        if settings.MPESA_ENV == "production":
            self.auth_url = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
            self.stk_url = "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
            self.query_url = "https://api.safaricom.co.ke/mpesa/stkpushquery/v1/query"
        else:
            self.auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
            self.stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
            self.query_url = "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query"

    def _get_auth_token(self):
        """Get M-Pesa API authentication token"""
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

            # Set token expiry (typically 1 hour)
            self.token_expiry = timezone.now() + timezone.timedelta(minutes=55)

            return self.token

        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get M-Pesa auth token: {str(e)}")

    def _generate_timestamp(self):
        """Generate current timestamp for M-Pesa API"""
        return time.strftime("%Y%m%d%H%M%S")

    def _generate_password(self, timestamp):
        """Generate password for M-Pesa API"""
        data = f"{self.shortcode}{self.passkey}{timestamp}"
        return base64.b64encode(data.encode()).decode()

    def stk_push(self, phone_number, amount, account_reference, transaction_desc):
        """Initiate M-Pesa STK Push"""
        try:
            # Normalize phone number for M-Pesa (must be in format 254...)
            normalized_phone = normalize_phone_number(phone_number)
            # Remove the '+' and ensure it starts with 254
            if normalized_phone.startswith('+'):
                normalized_phone = normalized_phone[1:]

            # Get auth token
            token = self._get_auth_token()

            # Generate timestamp and password
            timestamp = self._generate_timestamp()
            password = self._generate_password(timestamp)

            # Prepare STK push request
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

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            response = requests.post(self.stk_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            response_data = response.json()

            return {
                "CheckoutRequestID": response_data.get("CheckoutRequestID", str(uuid.uuid4())),
                "ResponseDescription": response_data.get("ResponseDescription", "Success"),
                "MerchantRequestID": response_data.get("MerchantRequestID", ""),
                "CustomerMessage": response_data.get("CustomerMessage", "")
            }

        except requests.exceptions.RequestException as e:
            # In production, we should not use mock responses. Instead, log and raise.
            logger.error("M-Pesa STK Push failed: %s", e, exc_info=True)
            raise Exception(f"M-Pesa STK Push failed: {str(e)}")

    def check_stk_status(self, checkout_request_id):
        """Check status of an STK push request"""
        try:
            token = self._get_auth_token()

            timestamp = self._generate_timestamp()
            password = self._generate_password(timestamp)

            payload = {
                "BusinessShortCode": self.shortcode,
                "Password": password,
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_request_id
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            response = requests.post(self.query_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error("M-Pesa STK status check failed: %s", e, exc_info=True)
            raise Exception(f"M-Pesa STK status check failed: {str(e)}")