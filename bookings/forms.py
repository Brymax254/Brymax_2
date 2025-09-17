from django import forms

class GuestCheckoutForm(forms.Form):
    full_name = forms.CharField(max_length=200)
    email = forms.EmailField()
    phone = forms.CharField(max_length=20)
    adults = forms.IntegerField(min_value=1, initial=1)
    children = forms.IntegerField(min_value=0, initial=0)
    days = forms.IntegerField(min_value=1, initial=1)
    travel_date = forms.DateField()
