from datetime import date

from django import forms
from django.core.exceptions import ValidationError

from accounts.models import HALLS

from .models import RETURN_REASONS, SLOTS

POSTCODE_RE = r"^[A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2}$"


class DeliveryForm(forms.Form):
    delivery_type = forms.ChoiceField(choices=[("halls", "Aston halls"), ("other", "Other UK address")], initial="halls",
                                      widget=forms.RadioSelect)
    recipient_name = forms.CharField(max_length=120, label="Name on parcel",
                                     error_messages={"required": "Enter the name for the parcel."})
    halls = forms.ChoiceField(choices=[("", "Choose your halls")] + [h for h in HALLS if h[0] != "Other / private housing"],
                              required=False)
    room = forms.CharField(max_length=20, required=False, label="Room number")
    address_line = forms.CharField(max_length=200, required=False, label="Street address")
    postcode = forms.RegexField(regex=POSTCODE_RE, required=False, label="Postcode",
                                error_messages={"invalid": "Enter a UK postcode, for example B4 7ET."})
    phone = forms.CharField(max_length=20, required=False, label="UK phone")
    delivery_date = forms.DateField(error_messages={"required": "Choose a delivery day.", "invalid": "Choose a delivery day."})
    delivery_slot = forms.ChoiceField(choices=SLOTS, error_messages={"required": "Choose a time slot.",
                                                                     "invalid_choice": "Choose a time slot."})

    def __init__(self, *args, available=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.available = available  # callable(date, slot) -> bool

    def clean_recipient_name(self):
        name = " ".join(self.cleaned_data["recipient_name"].split())
        if len(name) < 2:
            raise ValidationError("Enter the name for the parcel.")
        return name

    def clean_phone(self):
        phone = self.cleaned_data["phone"].replace(" ", "")
        if phone and not (phone.startswith(("07", "+447")) and phone.lstrip("+").isdigit() and 11 <= len(phone) <= 13):
            raise ValidationError("Enter a UK mobile number, for example 07700 900123, or leave it blank.")
        return phone

    def clean(self):
        data = super().clean()
        if data.get("delivery_type") == "halls":
            if not data.get("halls"):
                self.add_error("halls", "Choose your halls.")
            room = (data.get("room") or "").strip().upper()
            if not room:
                self.add_error("room", "Enter your room number, for example C-214.")
            elif not all(ch.isalnum() or ch in "- " for ch in room):
                self.add_error("room", "Use letters, numbers and dashes only.")
            data["room"] = room
        elif data.get("delivery_type") == "other":
            if not (data.get("address_line") or "").strip():
                self.add_error("address_line", "Enter the street address.")
            if not data.get("postcode"):
                if "postcode" not in self.errors:
                    self.add_error("postcode", "Enter a UK postcode, for example B4 7ET.")
            else:
                data["postcode"] = data["postcode"].upper()
        d, slot = data.get("delivery_date"), data.get("delivery_slot")
        if d and slot and self.available and not self.available(d, slot):
            self.add_error("delivery_slot", "That slot is no longer available. Please choose another.")
        return data


class ReturnForm(forms.Form):
    lines = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple,
                                      error_messages={"required": "Choose at least one item to return."})
    reason = forms.ChoiceField(choices=[("", "Choose a reason")] + RETURN_REASONS,
                               error_messages={"required": "Choose a reason."})
    comments = forms.CharField(max_length=500, required=False, widget=forms.Textarea, label="Tell us more")
    photo = forms.ImageField(required=False, label="Photo")
    method = forms.ChoiceField(choices=[("collect", "Collect from my halls reception (free)"),
                                        ("desk", "I’ll bring it to the campus pick-up desk")], initial="collect",
                               widget=forms.RadioSelect)

    def __init__(self, *args, line_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lines"].choices = line_choices

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and photo.size > 5 * 1024 * 1024:
            raise ValidationError("The photo is too large. Please use a file under 5 MB.")
        return photo
