from django import forms
from .models import Vehicle

class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = [
            'make', 'model', 'year', 'color', 'license_plate',
            'vehicle_type', 'fuel_type', 'capacity',
            'image', 'external_image_url',
            'features', 'accessibility_features',
            'logbook_copy', 'insurance_copy', 'inspection_certificate',
            'insurance_expiry', 'inspection_expiry', 'is_active'
        ]
        widgets = {
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
            'insurance_expiry': forms.DateInput(attrs={'class': 'form-control', 'type':'date'}),
            'inspection_expiry': forms.DateInput(attrs={'class': 'form-control', 'type':'date'}),
            'is_active': forms.CheckboxInput(attrs={'class':'form-check-input'}),
            'features': forms.Textarea(attrs={'class':'form-control', 'rows':3}),
            'accessibility_features': forms.Textarea(attrs={'class':'form-control', 'rows':3}),
            'make': forms.TextInput(attrs={'class':'form-control'}),
            'model': forms.TextInput(attrs={'class':'form-control'}),
            'color': forms.TextInput(attrs={'class':'form-control'}),
            'license_plate': forms.TextInput(attrs={'class':'form-control'}),
            'vehicle_type': forms.TextInput(attrs={'class':'form-control'}),
            'fuel_type': forms.TextInput(attrs={'class':'form-control'}),
            'capacity': forms.NumberInput(attrs={'class':'form-control'}),
            'external_image_url': forms.URLInput(attrs={'class':'form-control'}),
        }
