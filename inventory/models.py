from django.conf import settings
from django.db import models


class Reason(models.TextChoices):
    DELIVERY = "delivery", "Delivery from supplier"
    RETURN_RESELLABLE = "return", "Customer return (resellable)"
    DAMAGED = "damaged", "Damaged / write-off"
    CORRECTION = "correction", "Stock count correction"
    ORDER = "order", "Customer order"
    CANCEL = "cancel", "Order cancelled"


MANUAL_REASONS = [Reason.DELIVERY, Reason.RETURN_RESELLABLE, Reason.DAMAGED, Reason.CORRECTION]


class StockMovement(models.Model):
    """Every change to a product's stock is recorded here (audit trail)."""

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="movements")
    change = models.IntegerField()
    new_quantity = models.PositiveIntegerField()
    reason = models.CharField(max_length=20, choices=Reason.choices)
    note = models.CharField(max_length=200, blank=True)
    order = models.ForeignKey("orders.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product} {self.change:+d} ({self.get_reason_display()})"


class PurchaseOrder(models.Model):
    """A reorder created from the AI forecast. Always needs a human to create it;
    receiving it adds stock through the normal adjustment process."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="purchase_orders")
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    source = models.CharField(max_length=40, default="manual")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
