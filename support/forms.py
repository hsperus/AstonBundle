from django import forms
from django.core.exceptions import ValidationError

from accounts.forms import clean_aston_email

from .models import TOPICS


class ContactForm(forms.Form):
    name = forms.CharField(max_length=120, label="Full name", error_messages={"required": "Enter your name."})
    email = forms.EmailField(label="Aston email", error_messages={"required": "Enter your Aston email address.",
                                                                  "invalid": "Enter an email address like name@aston.ac.uk"})
    topic = forms.ChoiceField(choices=TOPICS, label="Topic")
    order_number = forms.CharField(max_length=20, required=False, label="Order number")
    message = forms.CharField(max_length=2000, widget=forms.Textarea, label="Message",
                              error_messages={"required": "Write your message."})
    website = forms.CharField(required=False)  # honeypot: humans leave it empty

    def clean_email(self):
        return clean_aston_email(self.cleaned_data["email"])

    def clean_message(self):
        msg = self.cleaned_data["message"].strip()
        if len(msg) < 20:
            raise ValidationError("Please write at least 20 characters so we can help.")
        return msg

    def clean_order_number(self):
        return self.cleaned_data["order_number"].strip().upper()

    def clean(self):
        data = super().clean()
        if data.get("website"):
            raise ValidationError("Your message could not be sent.")
        return data
