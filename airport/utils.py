def normalize_phone_number(phone: str, default_country_code: str = '254') -> str:
    """
    Normalize a phone number to international format.

    Args:
        phone: The phone number string to normalize.
        default_country_code: The default country code (without '+') to use if none is provided.

    Returns:
        Normalized phone number in E.164 format (e.g., +254712345678).
    """
    if not phone:
        return f"+{default_country_code}700000000"  # Default fallback

    # Remove all non-digit characters
    phone = ''.join(filter(str.isdigit, phone))

    # If the number starts with '0', replace with the country code
    if phone.startswith('0'):
        phone = default_country_code + phone[1:]
    # If the number doesn't start with '+', add the country code
    elif not phone.startswith('+'):
        # Check if it already has the country code (without '+')
        if phone.startswith(default_country_code):
            phone = '+' + phone
        else:
            phone = '+' + default_country_code + phone
    else:
        # It already has a '+', so we leave it as is
        pass

    return phone