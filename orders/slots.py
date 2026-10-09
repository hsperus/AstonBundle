"""Delivery slots: we deliver to halls reception on one of the 3 days before the
student's arrival, or on the arrival day itself. Each slot has a fixed capacity."""
from datetime import date, timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .models import SLOTS, Order, OrderStatus

LEAD_DAYS = 2  # earliest delivery is 2 days after ordering
WINDOW_DAYS = 3


def earliest_date():
    return timezone.localdate() + timedelta(days=LEAD_DAYS)


def days_for(arrival: date):
    """List of dicts for each possible delivery day, with slot availability."""
    if arrival is None:
        return []
    start = max(arrival - timedelta(days=WINDOW_DAYS), earliest_date())
    if start > arrival:
        start = earliest_date()
        end = start + timedelta(days=WINDOW_DAYS)
    else:
        end = arrival
    counts = {
        (row["delivery_date"], row["delivery_slot"]): row["n"]
        for row in Order.objects.filter(delivery_date__range=(start, end))
        .exclude(status=OrderStatus.CANCELLED)
        .values("delivery_date", "delivery_slot")
        .annotate(n=Count("id"))
    }
    days = []
    d = start
    while d <= end:
        slots = []
        for code, label in SLOTS:
            used = counts.get((d, code), 0)
            slots.append({"code": code, "label": label, "full": used >= settings.SLOT_CAPACITY,
                          "left": max(0, settings.SLOT_CAPACITY - used)})
        days.append({"date": d, "slots": slots, "full": all(s["full"] for s in slots), "is_arrival": d == arrival})
        d += timedelta(days=1)
    return days


def slot_available(d: date, code: str, arrival: date | None = None):
    if d < earliest_date() or code not in dict(SLOTS):
        return False
    used = Order.objects.filter(delivery_date=d, delivery_slot=code).exclude(status=OrderStatus.CANCELLED).count()
    return used < settings.SLOT_CAPACITY
