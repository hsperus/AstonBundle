from django import forms
from django.core.exceptions import ValidationError

from .models import Review


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(choices=[(i, i) for i in range(1, 6)], coerce=int,
                                    error_messages={"required": "Choose a star rating.", "invalid_choice": "Choose a star rating."})

    class Meta:
        model = Review
        fields = ["rating", "title", "body", "course"]
        labels = {"body": "Your review", "course": "Your course"}
        error_messages = {"title": {"required": "Give your review a short title."},
                          "body": {"required": "Write a few words about the product."}}

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if len(body) < 10:
            raise ValidationError("Write at least 10 characters.")
        if "@" in body or "http" in body.lower():
            raise ValidationError("Please don’t include emails, links or personal details.")
        return body
