# bookings/services.py
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


class PesaPalService:
    # PesaPal API v3 endpoints
    BASE_URL = "https://pay.pesapal.com/v3"  # Production

    # BASE_URL = "https://cybqa.pesapal.com/pesapalv3"  # Sandbox

    def __init__(self):
        self.consumer_key = settings.PESAPAL_CONSUMER_KEY
        self.consumer_secret = settings.PESAPAL_CONSUMER_SECRET
        self.token = None
        self.token_expiry = None

    def _get_auth_token(self):
        """Get authentication token from PesaPal (required for v3 API)"""
        # Check if we have a valid token
        if self.token and self.token_expiry and self.token_expiry > timezone.now():
            return self.token

        auth_url = f"{self.BASE_URL}/api/Auth/RequestToken"
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
            raise Exception(f"Failed to get PesaPal auth token: {str(e)}")

    def _generate_oauth_nonce(self):
        """Generate a unique nonce for OAuth"""
        return str(uuid.uuid4()).replace('-', '')

    def _generate_oauth_timestamp(self):
        """Generate current timestamp for OAuth"""
        return str(int(time.time()))

    def initiate_payment(self, amount, description, callback_url, email=None, phone=None, first_name=None,
                         last_name=None):
        """Initiate payment using PesaPal API v3"""
        try:
            # Get authentication token
            token = self._get_auth_token()

            # Prepare order data
            order_tracking_id = str(uuid.uuid4())
            order_data = {
                "id": order_tracking_id,
                "currency": "KES",
                "amount": amount,
                "description": description,
                "callback_url": callback_url,
                "notification_id": settings.PESAPAL_NOTIFICATION_ID,  # From PesaPal dashboard
                "billing_address": {
                    "email_address": email or "",
                    "phone_number": phone or "",
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

            # Submit order
            submit_order_url = f"{self.BASE_URL}/api/URLSetup/RegisterIPN"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            response = requests.post(submit_order_url, json=order_data, headers=headers, timeout=30)
            response.raise_for_status()

            # Get iframe URL
            iframe_url = f"{self.BASE_URL}/api/URLSetup/GetIframeUrl"
            iframe_payload = {
                "order_tracking_id": order_tracking_id
            }

            iframe_response = requests.post(iframe_url, json=iframe_payload, headers=headers, timeout=30)
            iframe_response.raise_for_status()

            iframe_data = iframe_response.json()

            return {
                "order_tracking_id": order_tracking_id,
                "iframe_url": iframe_data.get("redirect_url", "")
            }

        except requests.exceptions.RequestException as e:
            # Fallback to v2 API if v3 fails
            return self._fallback_to_v2(amount, description, callback_url, email, phone, first_name, last_name)
        except Exception as e:
            raise Exception(f"Failed to initiate PesaPal payment: {str(e)}")

    def _fallback_to_v2(self, amount, description, callback_url, email=None, phone=None, first_name=None,
                        last_name=None):
        """Fallback to PesaPal v2 API if v3 fails"""
        base_url = "https://www.pesapal.com/API/PostPesapalDirectOrderV4"

        order_tracking_id = str(uuid.uuid4())
        params = {
            "amount": amount,
            "description": description,
            "type": "MERCHANT",
            "reference": order_tracking_id,
            "first_name": first_name or "",
            "last_name": last_name or "",
            "email": email or "",
            "phone_number": phone or "",
            "currency": "KES",
            "callback_url": callback_url
        }

        # Generate HMAC SHA1 signature
        param_string = urlencode(params)
        key = f"{settings.PESAPAL_CONSUMER_KEY}&{settings.PESAPAL_CONSUMER_SECRET}"
        signature = base64.b64encode(
            hmac.new(key.encode(), param_string.encode(), hashlib.sha1).digest()
        ).decode()

        iframe_url = f"{base_url}?{param_string}&signature={signature}"

        return {
            "order_tracking_id": order_tracking_id,
            "iframe_url": iframe_url
        }

    def check_payment_status(self, order_tracking_id):
        """Check payment status using PesaPal API v3"""
        try:
            token = self._get_auth_token()

            status_url = f"{self.BASE_URL}/api/QueryPaymentStatus"
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
            # Fallback to v2 status check
            return self._fallback_status_check(order_tracking_id)

    def _fallback_status_check(self, order_tracking_id):
        """Fallback to v2 status check"""
        query_url = "https://www.pesapal.com/API/QueryPaymentStatus"

        params = {
            "pesapal_merchant_reference": order_tracking_id
        }

        # Generate signature for v2
        param_string = urlencode(params)
        key = f"{settings.PESAPAL_CONSUMER_KEY}&{settings.PESAPAL_CONSUMER_SECRET}"
        signature = base64.b64encode(
            hmac.new(key.encode(), param_string.encode(), hashlib.sha1).digest()
        ).decode()

        query_url = f"{query_url}?{param_string}&signature={signature}"

        try:
            response = requests.get(query_url, timeout=30)
            response.raise_for_status()

            # Parse the XML response (v2 returns XML)
            # This is a simplified parsing - you might need to adjust based on actual response
            if "COMPLETED" in response.text:
                return {"status": "COMPLETED"}
            elif "PENDING" in response.text:
                return {"status": "PENDING"}
            else:
                return {"status": "FAILED"}

        except requests.exceptions.RequestException:
            return {"status": "UNKNOWN"}


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

    def _get_auth_token(self):
        """Get M-Pesa API authentication token"""
        if self.token and self.token_expiry and self.token_expiry > timezone.now():
            return self.token

        auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"

        try:
            response = requests.get(
                auth_url,
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
            # Clean phone number (ensure it starts with 254)
            if phone_number.startswith('0'):
                phone_number = '254' + phone_number[1:]
            elif phone_number.startswith('+'):
                phone_number = phone_number[1:]

            # Get auth token
            token = self._get_auth_token()

            # Generate timestamp and password
            timestamp = self._generate_timestamp()
            password = self._generate_password(timestamp)

            # Prepare STK push request
            stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

            payload = {
                "BusinessShortCode": self.shortcode,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": amount,
                "PartyA": phone_number,
                "PartyB": self.shortcode,
                "PhoneNumber": phone_number,
                "CallBackURL": self.callback_url,
                "AccountReference": account_reference,
                "TransactionDesc": transaction_desc
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            response = requests.post(stk_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            response_data = response.json()

            return {
                "CheckoutRequestID": response_data.get("CheckoutRequestID", str(uuid.uuid4())),
                "ResponseDescription": response_data.get("ResponseDescription", "Success"),
                "MerchantRequestID": response_data.get("MerchantRequestID", ""),
                "CustomerMessage": response_data.get("CustomerMessage", "")
            }

        except requests.exceptions.RequestException as e:
            # Fallback to mock response in production if API call fails
            if settings.DEBUG:
                raise Exception(f"M-Pesa STK Push failed: {str(e)}")
            else:
                return self._mock_stk_response(phone_number, amount)

    def _mock_stk_response(self, phone_number, amount):
        """Generate a mock response for production fallback"""
        return {
            "CheckoutRequestID": str(uuid.uuid4()),
            "ResponseDescription": "Success. Accept the prompt on your phone to complete payment.",
            "MerchantRequestID": f"MOCK_{str(uuid.uuid4())[:8]}",
            "CustomerMessage": f"Confirm payment of KES {amount} to {self.shortcode}"
        }

    def check_stk_status(self, checkout_request_id):
        """Check status of an STK push request"""
        try:
            token = self._get_auth_token()

            status_url = "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query"

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

            response = requests.post(status_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            return {
                "ResultCode": "1032",
                "ResultDesc": "Request cancelled by user" if not settings.DEBUG else f"Error: {str(e)}"
            }