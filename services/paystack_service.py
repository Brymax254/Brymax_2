import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class PaystackService:
    @staticmethod
    def verify_transaction(reference):
        """
        Verify a Paystack transaction using the reference
        """
        url = f"https://api.paystack.co/transaction/verify/{reference}"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(url, headers=headers)
            response_data = response.json()

            if response_data.get('status'):
                data = response_data.get('data', {})
                return {
                    'status': data.get('status'),
                    'reference': data.get('reference'),
                    'amount': data.get('amount'),
                    'currency': data.get('currency'),
                    'paid_at': data.get('paid_at'),
                    'channel': data.get('channel'),
                    'customer': data.get('customer', {}),
                    'metadata': data.get('metadata', {}),
                    'id': data.get('id'),
                    'ip_address': data.get('ip_address'),
                    'authorization': data.get('authorization', {})
                }
            return {'status': 'failed', 'message': response_data.get('message')}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error verifying Paystack transaction: {e}")
            return {'status': 'error', 'message': str(e)}

    @staticmethod
    def initialize_transaction(amount, email, reference, callback_url, metadata=None):
        """
        Initialize a Paystack transaction
        """
        url = "https://api.paystack.co/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "amount": int(amount * 100),  # Convert to kobo
            "email": email,
            "reference": reference,
            "callback_url": callback_url
        }

        if metadata:
            payload["metadata"] = metadata

        try:
            response = requests.post(url, json=payload, headers=headers)
            response_data = response.json()

            if response_data.get('status'):
                return {
                    'status': 'success',
                    'authorization_url': response_data.get('data', {}).get('authorization_url'),
                    'access_code': response_data.get('data', {}).get('access_code'),
                    'reference': reference
                }
            return {'status': 'failed', 'message': response_data.get('message')}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error initializing Paystack transaction: {e}")
            return {'status': 'error', 'message': str(e)}