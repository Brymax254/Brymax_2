# bookings/utils.py
import logging
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import re

logger = logging.getLogger(__name__)

# =============================================================================
# 💳 Payment Utilities
# =============================================================================
def log_payment_event(event_type, payment_id, **kwargs):
    """
    Log payment events for debugging and analytics.
    Args:
        event_type (str): e.g., 'callback_success', 'retry_failed'
        payment_id (str or int)
        kwargs: extra info like email, phone, reference, error
    """
    msg = f"[Payment Event] type={event_type}, payment_id={payment_id}, data={kwargs}"
    logger.info(msg)


def create_success_response(data=None):
    """
    Standardized success response for APIs or AJAX requests
    """
    return {
        "status": True,
        "data": data or {}
    }


def create_error_response(message, status=400):
    """
    Standardized error response for APIs or AJAX requests
    """
    return {
        "status": False,
        "message": message,
        "http_status": status
    }


def send_payment_confirmation_email(payment):
    """
    Send confirmation email after successful payment
    """
    try:
        subject = f"Payment Confirmation for {payment.tour.name}"
        message = f"""
Hello {payment.guest_full_name},

Your payment of KES {payment.amount_paid} for the tour "{payment.tour.name}" has been successfully received.

Reference: {payment.transaction_id}
Payment Date: {timezone.localtime(payment.paid_at).strftime('%d-%b-%Y %H:%M:%S')}

Thank you for booking with us!
"""
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [payment.guest_email],
            fail_silently=False,
        )
        logger.info(f"Payment confirmation email sent for payment_id={payment.id}")
    except Exception as e:
        logger.error(f"Failed to send payment confirmation email for payment_id={payment.id}: {str(e)}", exc_info=True)


# =============================================================================
# 📞 Helper Utilities
# =============================================================================
def normalize_phone_number(phone):
    """
    Normalize phone number to format 2547XXXXXXXX
    Removes spaces, dashes, parentheses, or leading +.
    """
    if not phone:
        return ""
    # Remove non-digit characters
    phone = re.sub(r'\D', '', phone)
    # Handle leading 0
    if phone.startswith('0'):
        phone = '254' + phone[1:]
    # Already in international format
    elif phone.startswith('254'):
        pass
    # Leading +
    elif phone.startswith('+254'):
        phone = phone[1:]
    return phone
