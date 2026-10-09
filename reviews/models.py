from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count
from django.utils import timezone


class Review(models.Model):
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=80)
    body = models.TextField(max_length=1000)
    course = models.CharField(max_length=80, blank=True, help_text="Optional, shown next to the first name.")
    verified_buyer = models.BooleanField(default=True)
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("product", "user")]
        constraints = [models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="review_rating_1_5")]

    def __str__(self):
        return f"{self.product} – {self.rating}★"

    @property
    def author_display(self):
        parts = self.user.full_name.split()
        if not parts:
            return "Student"
        return parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")

    @property
    def stars(self):
        return ["starf" if i <= self.rating else "star" for i in range(1, 6)]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        refresh_product_rating(self.product)

    def delete(self, *args, **kwargs):
        product = self.product
        super().delete(*args, **kwargs)
        refresh_product_rating(product)


def refresh_product_rating(product):
    agg = Review.objects.filter(product=product, is_visible=True).aggregate(a=Avg("rating"), c=Count("id"))
    product.rating_avg = round(agg["a"] or 0, 2)
    product.rating_count = agg["c"] or 0
    product.save(update_fields=["rating_avg", "rating_count"])
