"""All stock changes go through these functions so that stock can never go
below zero and every change is logged."""
from django.db import transaction

from catalog.models import Product

from .models import Reason, StockMovement


class StockError(ValueError):
    pass


@transaction.atomic
def adjust_stock(product_id, change, reason, by=None, note="", order=None):
    """Apply `change` (+/-) to a product's stock under a row lock."""
    if change == 0:
        raise StockError("The quantity must not be zero.")
    product = Product.objects.select_for_update().get(pk=product_id)
    new_qty = product.stock + change
    if new_qty < 0:
        raise StockError(f"Stock cannot be negative: {product.name} has {product.stock} available.")
    product.stock = new_qty
    product.save(update_fields=["stock", "updated_at"])
    StockMovement.objects.create(
        product=product, change=change, new_quantity=new_qty, reason=reason, note=note[:200], by=by, order=order
    )
    return product


@transaction.atomic
def reserve_for_order(requirements, order):
    """requirements: {product_id: qty}. Locks every row first (in id order to avoid
    deadlocks), checks all quantities, then decrements. All-or-nothing."""
    ids = sorted(requirements)
    products = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    problems = []
    for pid in ids:
        p = products.get(pid)
        if p is None or not p.is_active:
            problems.append((pid, 0))
        elif p.stock < requirements[pid]:
            problems.append((pid, p.stock))
    if problems:
        raise InsufficientStock(problems)
    for pid in ids:
        p = products[pid]
        p.stock -= requirements[pid]
        p.popularity += requirements[pid]
        p.save(update_fields=["stock", "popularity", "updated_at"])
        StockMovement.objects.create(
            product=p, change=-requirements[pid], new_quantity=p.stock, reason=Reason.ORDER, order=order
        )


class InsufficientStock(StockError):
    def __init__(self, problems):
        self.problems = problems  # list of (product_id, available)
        super().__init__("Some items no longer have enough stock.")


@transaction.atomic
def release_for_order(requirements, order, reason=Reason.CANCEL, by=None, note=""):
    for pid, qty in sorted(requirements.items()):
        if qty > 0:
            adjust_stock(pid, qty, reason, by=by, note=note, order=order)
