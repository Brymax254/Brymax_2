from django import template
import os
from django.conf import settings

register = template.Library()

@register.simple_tag
def get_partner_logos():
    partners_dir = os.path.join(settings.BASE_DIR, 'static', 'images', 'partners')
    if not os.path.exists(partners_dir):
        return []
    return [
        f'images/partners/{f}'
        for f in os.listdir(partners_dir)
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.svg', '.webp'))
    ]
