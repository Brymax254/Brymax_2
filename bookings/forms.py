from django import forms
from django.utils import timezone
from .models import Tour, PaymentStatus


class GuestCheckoutForm(forms.Form):
    """Form for guest checkout process."""
    full_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your full name',
            'required': True
        }),
        error_messages={
            'required': 'Please enter your full name'
        }
    )

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address',
            'required': True
        }),
        error_messages={
            'required': 'Please enter your email address',
            'invalid': 'Please enter a valid email address'
        }
    )

    phone = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your phone number (e.g., 0712345678)',
            'required': True
        }),
        error_messages={
            'required': 'Please enter your phone number'
        }
    )

    adults = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1'
        }),
        error_messages={
            'min_value': 'At least one adult is required'
        }
    )

    children = forms.IntegerField(
        min_value=0,
        initial=0,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0'
        })
    )

    days = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1'
        }),
        error_messages={
            'min_value': 'At least one day is required'
        }
    )

    travel_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'min': timezone.now().date().isoformat()
        }),
        error_messages={
            'required': 'Please select a travel date'
        }
    )

    special_requests = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Any special requests or dietary requirements?'
        })
    )

    def clean_phone(self):
        """Validate phone number format."""
        phone = self.cleaned_data.get('phone')
        # Remove any non-digit characters
        phone = ''.join(filter(str.isdigit, phone))

        # Validate Kenyan phone number format
        if len(phone) == 9 and phone.startswith('7'):  # Format: 712345678
            return f"0{phone}"  # Convert to 0712345678
        elif len(phone) == 10 and phone.startswith('07'):  # Format: 0712345678
            return phone
        elif len(phone) == 12 and phone.startswith('254'):  # Format: 254712345678
            return f"+{phone}"  # Convert to +254712345678
        elif len(phone) == 13 and phone.startswith('+254'):  # Format: +254712345678
            return phone

        raise forms.ValidationError(
            "Please enter a valid Kenyan phone number (e.g., 0712345678 or +254712345678)"
        )

    def clean_travel_date(self):
        """Validate that travel date is not in the past."""
        travel_date = self.cleaned_data.get('travel_date')
        if travel_date and travel_date < timezone.now().date():
            raise forms.ValidationError("Travel date cannot be in the past")
        return travel_date

    def clean(self):
        """Form-wide validation."""
        cleaned_data = super().clean()
        adults = cleaned_data.get('adults')
        children = cleaned_data.get('children')

        # Validate total participants
        if adults and children:
            total_participants = adults + children
            if total_participants > 20:  # Set a reasonable maximum
                raise forms.ValidationError("Total participants cannot exceed 20")

        return cleaned_data


class TourForm(forms.ModelForm):
    """Form for creating and editing tours."""

    class Meta:
        model = Tour
        fields = [
            'title', 'description', 'itinerary', 'price_per_person',
            'duration_days', 'max_group_size', 'min_group_size',
            'difficulty', 'category', 'available', 'featured',
            'image', 'video', 'image_url'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter tour title'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Enter tour description'
            }),
            'itinerary': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': 'Enter day-by-day itinerary'
            }),
            'price_per_person': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '100',
                'placeholder': '0.00'
            }),
            'duration_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Number of days'
            }),
            'max_group_size': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Maximum group size'
            }),
            'min_group_size': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Minimum group size'
            }),
            'difficulty': forms.Select(attrs={
                'class': 'form-control'
            }),
            'category': forms.Select(attrs={
                'class': 'form-control'
            }),
            'available': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'featured': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control-file',
                'accept': 'image/*'
            }),
            'video': forms.FileInput(attrs={
                'class': 'form-control-file',
                'accept': 'video/*'
            }),
            'image_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://example.com/image.jpg'
            })
        }

    def clean_price_per_person(self):
        """Validate that price is positive."""
        price = self.cleaned_data.get('price_per_person')
        if price and price <= 0:
            raise forms.ValidationError("Price must be greater than zero")
        return price

    def clean(self):
        """Form-wide validation."""
        cleaned_data = super().clean()
        max_group_size = cleaned_data.get('max_group_size')
        min_group_size = cleaned_data.get('min_group_size')
        duration_days = cleaned_data.get('duration_days')

        # Validate group sizes
        if max_group_size and min_group_size:
            if min_group_size > max_group_size:
                raise forms.ValidationError("Minimum group size cannot be greater than maximum group size")

        # Validate duration
        if duration_days and duration_days > 30:
            raise forms.ValidationError("Tour duration cannot exceed 30 days")

        return cleaned_data


class PaymentSearchForm(forms.Form):
    """Form for searching payments in admin."""
    reference = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by reference'
        })
    )

    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + list(PaymentStatus.choices),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-control'
        })
    )

    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by email'
        })
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    def clean(self):
        """Validate date range."""
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')

        if date_from and date_to:
            if date_from > date_to:
                raise forms.ValidationError("Date from cannot be later than date to")

        return cleaned_data


class ContactForm(forms.Form):
    """Form for contact page."""
    name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Your name',
            'required': True
        }),
        error_messages={
            'required': 'Please enter your name'
        }
    )

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Your email address',
            'required': True
        }),
        error_messages={
            'required': 'Please enter your email address',
            'invalid': 'Please enter a valid email address'
        }
    )

    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Your phone number'
        })
    )

    subject = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Subject',
            'required': True
        }),
        error_messages={
            'required': 'Please enter a subject'
        }
    )

    message = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 5,
            'placeholder': 'Your message',
            'required': True
        }),
        error_messages={
            'required': 'Please enter your message'
        }
    )

    def clean_phone(self):
        """Validate phone number format."""
        phone = self.cleaned_data.get('phone')
        if phone:  # Only validate if phone is provided
            # Remove any non-digit characters
            phone = ''.join(filter(str.isdigit, phone))

            # Validate Kenyan phone number format
            if len(phone) == 9 and phone.startswith('7'):  # Format: 712345678
                return f"0{phone}"  # Convert to 0712345678
            elif len(phone) == 10 and phone.startswith('07'):  # Format: 0712345678
                return phone
            elif len(phone) == 12 and phone.startswith('254'):  # Format: 254712345678
                return f"+{phone}"  # Convert to +254712345678
            elif len(phone) == 13 and phone.startswith('+254'):  # Format: +254712345678
                return phone
            else:
                raise forms.ValidationError(
                    "Please enter a valid Kenyan phone number (e.g., 0712345678 or +254712345678)"
                )
        return phone


class DriverProfileForm(forms.Form):
    """Form for updating driver profile."""
    name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Your full name'
        })
    )

    phone_number = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Your phone number'
        })
    )

    experience_years = forms.IntegerField(
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0'
        })
    )

    vehicle = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Vehicle make and model'
        })
    )

    vehicle_plate = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Vehicle license plate'
        })
    )

    bio = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Tell us about yourself'
        })
    )

    profile_picture = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control-file',
            'accept': 'image/*'
        })
    )

    def clean_phone_number(self):
        """Validate phone number format."""
        phone = self.cleaned_data.get('phone_number')
        if phone:  # Only validate if phone is provided
            # Remove any non-digit characters
            phone = ''.join(filter(str.isdigit, phone))

            # Validate Kenyan phone number format
            if len(phone) == 9 and phone.startswith('7'):  # Format: 712345678
                return f"0{phone}"  # Convert to 0712345678
            elif len(phone) == 10 and phone.startswith('07'):  # Format: 0712345678
                return phone
            elif len(phone) == 12 and phone.startswith('254'):  # Format: 254712345678
                return f"+{phone}"  # Convert to +254712345678
            elif len(phone) == 13 and phone.startswith('+254'):  # Format: +254712345678
                return phone
            else:
                raise forms.ValidationError(
                    "Please enter a valid Kenyan phone number (e.g., 0712345678 or +254712345678)"
                )
        return phone