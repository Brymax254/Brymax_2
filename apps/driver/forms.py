from django import forms
from .models import Driver
class DriverForm(forms.ModelForm):
    class Meta:
        model  = Driver
        fields = ('full_name', 'license_no', 'phone')
