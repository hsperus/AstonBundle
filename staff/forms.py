from decimal import Decimal

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from accounts.models import Role
from catalog.models import PRODUCT_ICONS, TONES, Category, Product
from inventory.models import MANUAL_REASONS, Reason


class StaffSignInForm(forms.Form):
    email = forms.EmailField(label="Staff email", error_messages={"required": "Enter your staff email."})
    password = forms.CharField(widget=forms.PasswordInput, strip=False, error_messages={"required": "Enter your password."})


class ProductForm(forms.ModelForm):
    stock = forms.IntegerField(label="Stock quantity", error_messages={"invalid": "Enter a whole number, for example 25."})
    specs_text = forms.CharField(required=False, widget=forms.Textarea, label="Specifications",
                                 help_text="One per line, as Label: Value")

    class Meta:
        model = Product
        fields = ["name", "category", "sku", "summary", "description", "features", "price", "low_stock_threshold",
                  "max_per_order", "icon", "tone", "image", "image_alt", "returnable", "is_active"]
        labels = {"price": "Price (£)", "low_stock_threshold": "Low-stock threshold", "max_per_order": "Max per order",
                  "is_active": "Visible in shop", "returnable": "Can be returned", "icon": "Placeholder icon",
                  "tone": "Placeholder colour", "image_alt": "Alt text (describes the image)"}
        error_messages = {
            "name": {"required": "Enter the product name."},
            "sku": {"required": "Enter a SKU.", "unique": "Another product already uses this SKU."},
            "price": {"required": "Enter a price.", "invalid": "Enter a price like 13.99."},
            "summary": {"required": "Write a one-line summary."},
            "description": {"required": "Write a description."},
            "image_alt": {"required": "Add alt text so screen-reader users know what the image shows. Example: “Cream electric kettle with UK plug”."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.all()
        self.fields["category"].empty_label = "Choose a category"
        self.fields["icon"] = forms.ChoiceField(choices=[(i, i) for i in PRODUCT_ICONS], label="Placeholder icon")
        self.fields["tone"] = forms.ChoiceField(choices=TONES, required=False, label="Placeholder colour")
        if self.instance.pk:
            self.fields["stock"].initial = self.instance.stock
            self.fields["specs_text"].initial = "\n".join(f"{k}: {v}" for k, v in (self.instance.specs or []))
        else:
            self.fields["stock"].initial = 0

    def clean_sku(self):
        sku = self.cleaned_data["sku"].strip().upper()
        if not all(ch.isalnum() or ch == "-" for ch in sku):
            raise ValidationError("Use letters, numbers and dashes only.")
        return sku

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price is None or price <= 0:
            raise ValidationError("Price must be more than £0.")
        if price > Decimal("2000"):
            raise ValidationError("That price looks too high. Check it is in pounds.")
        return price

    def clean_stock(self):
        stock = self.cleaned_data["stock"]
        if stock < 0:
            raise ValidationError("Stock cannot be negative. Enter 0 or more.")
        if stock > 100000:
            raise ValidationError("That number looks too high.")
        return stock

    def clean_max_per_order(self):
        v = self.cleaned_data["max_per_order"]
        if not 1 <= v <= 50:
            raise ValidationError("Choose a number from 1 to 50.")
        return v

    def clean_image(self):
        img = self.cleaned_data.get("image")
        if img and hasattr(img, "size") and img.size > 5 * 1024 * 1024:
            raise ValidationError("Use an image under 5 MB.")
        return img

    def clean_specs_text(self):
        rows = []
        for line in self.cleaned_data["specs_text"].splitlines():
            if not line.strip():
                continue
            if ":" not in line:
                raise ValidationError(f"Use “Label: Value” on each line (problem: “{line.strip()[:30]}”).")
            k, v = line.split(":", 1)
            rows.append([k.strip(), v.strip()])
        return rows


class AdjustForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.all(), widget=forms.HiddenInput)
    direction = forms.ChoiceField(choices=[("add", "Add stock"), ("remove", "Remove stock")], widget=forms.RadioSelect,
                                  initial="add")
    quantity = forms.IntegerField(min_value=1, max_value=10000,
                                  error_messages={"min_value": "Enter 1 or more.", "required": "Enter a quantity.",
                                                  "invalid": "Enter a whole number."})
    reason = forms.ChoiceField(choices=[("", "Choose a reason")] + [(r.value, r.label) for r in MANUAL_REASONS],
                               error_messages={"required": "Choose a reason. Every stock change is recorded."})
    note = forms.CharField(max_length=200, required=False)

    def clean(self):
        data = super().clean()
        if data.get("direction") == "add" and data.get("reason") == Reason.DAMAGED:
            self.add_error("reason", "“Damaged / write-off” removes stock. Choose “Remove stock”.")
        if data.get("direction") == "remove" and data.get("reason") in (Reason.DELIVERY, Reason.RETURN_RESELLABLE):
            self.add_error("reason", "This reason adds stock. Choose “Add stock”.")
        return data


class InviteForm(forms.Form):
    email = forms.EmailField(label="Work email")
    role = forms.ChoiceField(choices=[(Role.STOCK, Role.STOCK.label), (Role.SUPPORT, Role.SUPPORT.label)],
                             widget=forms.RadioSelect, initial=Role.STOCK)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        domain = settings.STAFF_EMAIL_DOMAIN
        if not email.endswith("@" + domain):
            raise ValidationError(f"Use a team email ending with @{domain}.")
        from accounts.models import User

        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("This person already has an account.")
        return email


class AcceptInviteForm(forms.Form):
    full_name = forms.CharField(max_length=120, label="Your name")
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password", strip=False)
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password", strip=False)

    def clean(self):
        from django.contrib.auth import password_validation

        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords don’t match.")
        if p1:
            try:
                password_validation.validate_password(p1)
            except ValidationError as e:
                self.add_error("password1", e)
        return data
