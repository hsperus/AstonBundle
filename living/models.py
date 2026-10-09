"""AstonBundle Living: a fictional student residence next to campus.
Room types and shared facilities are shown on /living/; students send a booking
request, which arrives in the staff Enquiries inbox. No payment is taken."""
from decimal import Decimal

from django.db import models
from django.db.models import Q
from django.urls import reverse


class RoomType(models.Model):
    name = models.CharField(max_length=80)
    slug = models.SlugField(unique=True)
    summary = models.CharField(max_length=200)
    description = models.TextField()
    price_per_week = models.DecimalField(max_digits=7, decimal_places=2)
    contract_weeks = models.PositiveIntegerField(default=44, help_text="Length of the standard contract.")
    size_m2 = models.PositiveIntegerField("Size (m²)")
    bed = models.CharField(max_length=40)
    bathroom = models.CharField(max_length=60)
    kitchen = models.CharField(max_length=80)
    features = models.TextField(blank=True, help_text="One feature per line.")
    rooms_available = models.PositiveIntegerField(default=0)
    accessible = models.BooleanField(default=False)
    image = models.ImageField(upload_to="living/", blank=True)
    image_alt = models.CharField("Image description (alt text)", max_length=200)
    sort = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort", "price_per_week"]
        constraints = [models.CheckConstraint(condition=Q(price_per_week__gt=0), name="roomtype_price_positive")]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("living:room", args=[self.slug])

    @property
    def feature_list(self):
        return [f.strip() for f in self.features.splitlines() if f.strip()]

    @property
    def contract_total(self):
        return (self.price_per_week * self.contract_weeks).quantize(Decimal("0.01"))


class Facility(models.Model):
    name = models.CharField(max_length=80)
    slug = models.SlugField(unique=True)
    summary = models.CharField(max_length=240)
    icon = models.CharField(max_length=20, default="home")
    image = models.ImageField(upload_to="living/", blank=True)
    image_alt = models.CharField("Image description (alt text)", max_length=200)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort"]
        verbose_name_plural = "facilities"

    def __str__(self):
        return self.name
