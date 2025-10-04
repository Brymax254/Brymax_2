from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Allow dictionary key access in templates: {{ dict|get_item:key }}"""
    if not dictionary:
        return []

    # Try exact match
    if key in dictionary:
        return dictionary.get(key, [])

    # Try string version of the key (handles int vs str mismatches)
    str_key = str(key)
    if str_key in dictionary:
        return dictionary.get(str_key, [])

    # Try int version of the key (if possible)
    try:
        int_key = int(key)
        if int_key in dictionary:
            return dictionary.get(int_key, [])
    except (ValueError, TypeError):
        pass

    return []


@register.filter
def div(value, arg):
    """Divides the value by the arg."""
    try:
        return float(value) / float(arg)
    except (ValueError, ZeroDivisionError, TypeError):
        return 0


@register.filter
def mul(value, arg):
    """Multiplies the value by the arg."""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0
