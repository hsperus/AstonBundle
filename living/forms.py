from django import forms
from django.core.exceptions import ValidationError

from .models import RoomType

MOVE_IN = [
    ("", "Choose a start date"),
    ("2027-01-09", "January 2027 intake (from 9 January 2027)"),
    ("2027-09-18", "September 2027 intake (from 18 September 2027)"),
]


class BookingRequestForm(forms.Form):
    name = forms.CharField(max_length=120, label="Full name", error_messages={"required": "Enter your name."})
    email = forms.EmailField(label="Email", error_messages={"required": "Enter your email address.",
                                                            "invalid": "Enter an email address like name@example.com"})
    room = forms.ModelChoiceField(queryset=RoomType.objects.filter(is_active=True), label="Room type", to_field_name="slug",
                                  empty_label="Choose a room type", error_messages={"required": "Choose a room type."})
    move_in = forms.ChoiceField(choices=MOVE_IN, label="Start date", error_messages={"required": "Choose a start date."})
    needs = forms.CharField(max_length=1000, required=False, widget=forms.Textarea, label="Anything we should know?",
                            help_text="For example accessibility needs or a flatmate you would like to live with.")
    agree = forms.BooleanField(error_messages={"required": "Please confirm you understand this is a request, not a booking."})
    website = forms.CharField(required=False)  # honeypot: humans leave it empty

    def clean(self):
        data = super().clean()
        if data.get("website"):
            raise ValidationError("Your request could not be sent.")
        return data
