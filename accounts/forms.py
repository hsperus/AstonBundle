from datetime import date, timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import ValidationError

from .models import HALLS, User


def clean_aston_email(value):
    email = (value or "").strip().lower()
    domain = settings.ASTON_EMAIL_DOMAIN
    if not email.endswith("@" + domain) or email.count("@") != 1 or len(email.split("@")[0]) < 2:
        raise ValidationError(f"Use your Aston email address — it should end with @{domain}")
    return email


class RegisterForm(forms.Form):
    full_name = forms.CharField(max_length=120, label="Full name",
                                error_messages={"required": "Enter your full name."})
    email = forms.EmailField(label="Aston email", max_length=254,
                             error_messages={"required": "Enter your Aston email address.",
                                             "invalid": "Enter an email address like name@aston.ac.uk"})
    password = forms.CharField(widget=forms.PasswordInput(render_value=False), label="Password", strip=False,
                               error_messages={"required": "Choose a password."})
    terms = forms.BooleanField(error_messages={"required": "Please agree to the terms of use to continue."})

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if len(name) < 2:
            raise ValidationError("Enter your full name.")
        return name

    def clean_email(self):
        email = clean_aston_email(self.cleaned_data["email"])
        existing = User.objects.filter(email__iexact=email).first()
        if existing and existing.email_verified:
            raise ValidationError("An account with this email already exists. Sign in instead, or reset your password.")
        return email

    def clean(self):
        data = super().clean()
        pw = data.get("password")
        if pw:
            user = User(email=data.get("email", ""), full_name=data.get("full_name", ""))
            try:
                password_validation.validate_password(pw, user)
            except ValidationError as e:
                self.add_error("password", e)
        return data


class VerifyForm(forms.Form):
    code = forms.CharField(max_length=6, min_length=6, label="Verification code",
                           error_messages={"required": "Enter the 6-digit code.", "min_length": "Enter all 6 digits."})

    def clean_code(self):
        code = "".join(ch for ch in self.cleaned_data["code"] if ch.isdigit())
        if len(code) != 6:
            raise ValidationError("The code has 6 numbers.")
        return code


class SignInForm(forms.Form):
    email = forms.EmailField(label="Aston email", error_messages={"required": "Enter your email address."})
    password = forms.CharField(widget=forms.PasswordInput, strip=False, error_messages={"required": "Enter your password."})
    remember = forms.BooleanField(required=False, initial=True)


class ProfileForm(forms.ModelForm):
    arrival_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}),
                                   error_messages={"invalid": "Enter a real date, for example 09/01/2027."})

    class Meta:
        model = User
        fields = ["full_name", "halls", "room", "arrival_date", "phone"]
        labels = {"halls": "Halls name", "room": "Room number", "phone": "UK phone"}

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if len(name) < 2:
            raise ValidationError("Enter your full name.")
        return name

    def clean_room(self):
        room = self.cleaned_data["room"].strip().upper()
        if room and not all(ch.isalnum() or ch in "- " for ch in room):
            raise ValidationError("Use letters, numbers and dashes only, for example C-214.")
        return room

    def clean_phone(self):
        phone = self.cleaned_data["phone"].replace(" ", "")
        if phone and not (phone.startswith(("07", "+447")) and phone.lstrip("+").isdigit() and 11 <= len(phone) <= 13):
            raise ValidationError("Enter a UK mobile number, for example 07700 900123, or leave it blank.")
        return phone

    def clean_arrival_date(self):
        d = self.cleaned_data.get("arrival_date")
        if d and not (date.today() - timedelta(days=365) <= d <= date.today() + timedelta(days=730)):
            raise ValidationError("Choose a date within the next two years.")
        return d


class ForgotForm(forms.Form):
    email = forms.EmailField(label="Aston email", error_messages={"required": "Enter your email address."})


class StrongSetPasswordForm(SetPasswordForm):
    """Django's set-password form with plain-English labels."""

    error_messages = {"password_mismatch": "The two passwords don’t match."}


class DeleteAccountForm(forms.Form):
    confirm = forms.CharField(label="Type DELETE to confirm")

    def clean_confirm(self):
        if self.cleaned_data["confirm"].strip() != "DELETE":
            raise ValidationError("Type DELETE in capital letters to confirm.")
        return "DELETE"


HALL_CHOICES = HALLS
