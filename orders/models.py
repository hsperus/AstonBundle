from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone


class OrderStatus(models.TextChoices):
    PLACED = "placed", "Placed"
    PROCESSING = "processing", "Processing"
    DISPATCHED = "dispatched", "Dispatched"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"


# Allowed status changes for staff (a simple state machine).
TRANSITIONS = {
    OrderStatus.PLACED: [OrderStatus.PROCESSING, OrderStatus.CANCELLED],
    OrderStatus.PROCESSING: [OrderStatus.DISPATCHED, OrderStatus.CANCELLED],
    OrderStatus.DISPATCHED: [OrderStatus.DELIVERED],
    OrderStatus.DELIVERED: [],
    OrderStatus.CANCELLED: [],
}

# UI chip class + icon for each displayed status
CHIPS = {
    "placed": ("c-placed", "clip", "Placed"),
    "processing": ("c-proc", "clock", "Processing"),
    "dispatched": ("c-disp", "truck", "Dispatched"),
    "delivered": ("c-deliv", "okc", "Delivered"),
    "return_requested": ("c-rreq", "return", "Return requested"),
    "returned": ("c-ret", "box", "Returned"),
    "cancelled": ("c-canc", "xc", "Cancelled"),
}

SLOTS = [("09-13", "9:00–13:00"), ("13-17", "13:00–17:00"), ("17-20", "17:00–20:00")]


class Order(models.Model):
    number = models.CharField(max_length=20, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.PLACED, db_index=True)
    # delivery snapshot (kept even if the profile changes later)
    recipient_name = models.CharField(max_length=120)
    delivery_type = models.CharField(max_length=10, choices=[("halls", "Aston halls"), ("other", "Other UK address")], default="halls")
    halls = models.CharField(max_length=60, blank=True)
    room = models.CharField(max_length=20, blank=True)
    address_line = models.CharField(max_length=200, blank=True)
    postcode = models.CharField(max_length=10, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    delivery_date = models.DateField()
    delivery_slot = models.CharField(max_length=5, choices=SLOTS)
    # money (GBP)
    items_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bundle_saving = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_reference = models.CharField(max_length=30, blank=True, help_text="Simulated payment reference. No card data is stored.")
    payment_method = models.CharField(max_length=10, choices=[("card", "Card"), ("apple_pay", "Apple Pay")], blank=True)
    card_brand = models.CharField(max_length=20, blank=True, help_text="Brand of the simulated test card.")
    card_last4 = models.CharField(max_length=4, blank=True, help_text="Last four digits of the simulated test card.")
    shipment_number = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_test_data = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=Q(total__gte=0), name="order_total_not_negative")]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        creating = not self.pk
        if creating and not self.number:
            self.number = "PENDING"
        super().save(*args, **kwargs)
        if self.number == "PENDING":
            self.number = f"AB-{self.created_at:%y%m%d}-{self.pk:04d}"
            super().save(update_fields=["number"])

    def get_absolute_url(self):
        return reverse("orders:detail", args=[self.number])

    @property
    def payment_label(self):
        """e.g. "Apple Pay · Visa •••• 4242"; empty for orders made before payment methods existed."""
        if not self.card_last4:
            return ""
        card = f"{self.card_brand} •••• {self.card_last4}"
        return f"Apple Pay · {card}" if self.payment_method == "apple_pay" else card

    @property
    def slot_label(self):
        return dict(SLOTS).get(self.delivery_slot, self.delivery_slot)

    @property
    def address_display(self):
        if self.delivery_type == "halls":
            return f"{self.halls}, Room {self.room}"
        return f"{self.address_line}, {self.postcode}"

    @property
    def item_count(self):
        return sum(line.quantity for line in self.lines.all())

    def summary_text(self):
        lines = list(self.lines.all())
        bundles = []
        singles = []
        for line in lines:
            if line.bundle_name:
                if line.bundle_name not in bundles:
                    bundles.append(line.bundle_name)
            else:
                singles.append(line.name)
        parts = bundles + singles
        if not parts:
            return ""
        first = parts[0] + (" bundle" if bundles and parts[0] in bundles and "Bundle" not in parts[0] else "")
        rest = len(parts) - 1
        return first + (f" + {rest} item{'s' if rest > 1 else ''}" if rest else "")

    @property
    def display_status(self):
        if self.status == OrderStatus.DELIVERED:
            returns = list(self.returns.all())
            if any(r.status == ReturnStatus.REQUESTED for r in returns):
                return "return_requested"
            lines = list(self.lines.all())
            if lines and all(l.returned_quantity >= l.quantity for l in lines):
                return "returned"
        return self.status

    @property
    def chip(self):
        return CHIPS[self.display_status]

    def delivered_at(self):
        ev = self.events.filter(status=OrderStatus.DELIVERED).order_by("created_at").first()
        return ev.created_at if ev else None

    def return_deadline(self):
        d = self.delivered_at()
        return d + timedelta(days=settings.RETURN_WINDOW_DAYS) if d else None

    def return_window_open(self):
        deadline = self.return_deadline()
        return bool(deadline and timezone.now() <= deadline and self.status == OrderStatus.DELIVERED)

    def allowed_transitions(self):
        return TRANSITIONS.get(self.status, [])

    def product_requirements(self):
        """{product_id: qty} for stock operations."""
        req = {}
        for line in self.lines.all():
            if line.product_id:
                req[line.product_id] = req.get(line.product_id, 0) + line.quantity
        return req


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.SET_NULL, null=True, related_name="order_lines")
    bundle = models.ForeignKey("catalog.Bundle", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    bundle_name = models.CharField(max_length=120, blank=True)
    name = models.CharField(max_length=120)
    icon = models.CharField(max_length=20, default="box")
    tone = models.CharField(max_length=2, blank=True)
    list_price = models.DecimalField(max_digits=8, decimal_places=2, help_text="Normal unit price at the time of order.")
    unit_price = models.DecimalField(max_digits=8, decimal_places=2, help_text="Price actually paid per unit (bundle share).")
    quantity = models.PositiveSmallIntegerField()
    returned_quantity = models.PositiveSmallIntegerField(default=0)
    returnable = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="orderline_qty_positive")]

    def __str__(self):
        return f"{self.quantity} × {self.name}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def pending_return(self):
        return self.return_items.filter(request__status=ReturnStatus.REQUESTED).select_related("request").first()

    def returnable_quantity(self):
        pending = sum(
            ri.quantity for ri in self.return_items.filter(request__status__in=[ReturnStatus.REQUESTED, ReturnStatus.APPROVED])
        )
        return max(0, self.quantity - pending)

    def return_block_reason(self):
        """None if this line can be returned now, otherwise a plain-English reason."""
        if not self.returnable:
            return "Not returnable once opened (hygiene)." if self.icon in {"tub", "pillow"} else "This item can’t be returned."
        if self.order.status != OrderStatus.DELIVERED:
            return "You can request a return after delivery."
        if not self.order.return_window_open():
            return "The 30-day return window has closed."
        if self.returnable_quantity() == 0:
            return "A return is already open for this item."
        return None


class OrderEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20, choices=OrderStatus.choices)
    note = models.CharField(max_length=200, blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]


class ReturnStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


RETURN_REASONS = [
    ("damaged", "It arrived damaged"),
    ("wrong", "Wrong item sent"),
    ("not_needed", "I don’t need it any more"),
    ("fit", "It doesn’t fit / wrong size"),
    ("not_described", "Not as described"),
    ("other", "Other reason"),
]


class ReturnRequest(models.Model):
    reference = models.CharField(max_length=20, unique=True, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="returns")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="returns")
    reason = models.CharField(max_length=20, choices=RETURN_REASONS)
    comments = models.TextField(blank=True, max_length=500)
    photo = models.ImageField(upload_to="returns/", blank=True)
    method = models.CharField(max_length=10, choices=[("collect", "Collect from my halls reception (free)"), ("desk", "I’ll bring it to the campus pick-up desk")], default="collect")
    status = models.CharField(max_length=10, choices=ReturnStatus.choices, default=ReturnStatus.REQUESTED, db_index=True)
    decision_note = models.CharField(max_length=300, blank=True)
    restock = models.BooleanField(default=True, help_text="Put the items back into sellable stock when approved.")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = "PENDING"
        super().save(*args, **kwargs)
        if self.reference == "PENDING":
            self.reference = f"RET-{self.created_at:%y%m%d}-{self.pk:04d}"
            super().save(update_fields=["reference"])

    @property
    def refund_amount(self):
        return sum((ri.line.unit_price * ri.quantity for ri in self.items.select_related("line")), Decimal("0"))

    @property
    def reply_by(self):
        d = self.created_at
        added = 0
        while added < 2:
            d += timedelta(days=1)
            if d.weekday() < 5:
                added += 1
        return d


class ReturnItem(models.Model):
    request = models.ForeignKey(ReturnRequest, on_delete=models.CASCADE, related_name="items")
    line = models.ForeignKey(OrderLine, on_delete=models.CASCADE, related_name="return_items")
    quantity = models.PositiveSmallIntegerField(default=1)
