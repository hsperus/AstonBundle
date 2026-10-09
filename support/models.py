from django.conf import settings
from django.db import models
from django.utils import timezone

TOPICS = [
    ("delivery", "Delivery and arrival dates"),
    ("order", "My order"),
    ("return", "Returns and refunds"),
    ("product", "Product question"),
    ("account", "My account"),
    ("accessibility", "Accessibility"),
    ("other", "Something else"),
]


class Enquiry(models.Model):
    class Status(models.TextChoices):
        UNREAD = "unread", "Unread"
        READ = "read", "Read"
        RESOLVED = "resolved", "Resolved"

    reference = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=120)
    email = models.EmailField()
    topic = models.CharField(max_length=20, choices=TOPICS)
    order_number = models.CharField(max_length=20, blank=True)
    message = models.TextField(max_length=2000)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="enquiries")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNREAD, db_index=True)
    reply = models.TextField(blank=True)
    replied_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    replied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "enquiries"

    def __str__(self):
        return f"{self.reference} – {self.get_topic_display()}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = "PENDING"
        super().save(*args, **kwargs)
        if self.reference == "PENDING":
            self.reference = f"ENQ-{self.created_at:%y%m%d}-{self.pk:04d}"
            super().save(update_fields=["reference"])
