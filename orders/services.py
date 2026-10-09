import secrets

from django.db import transaction
from django.utils import timezone

from inventory.models import Reason
from inventory.services import adjust_stock, release_for_order, reserve_for_order

from .basket import Basket, allocate_bundle_price
from .models import Order, OrderEvent, OrderLine, OrderStatus, ReturnStatus


class OrderError(Exception):
    pass


@transaction.atomic
def place_order(user, lines, delivery, payment=None):
    """Create an order from basket lines. `payment` is a succeeded orders.payments.Payment
    (None in tests and seed data). Stock for every product (including bundle
    components) is reserved in the same transaction; if anything is short, nothing
    is saved and InsufficientStock is raised."""
    if not lines:
        raise OrderError("Your basket is empty.")
    totals = Basket.totals(lines)
    order = Order.objects.create(
        user=user,
        recipient_name=delivery["recipient_name"],
        delivery_type=delivery.get("delivery_type", "halls"),
        halls=delivery.get("halls", ""),
        room=delivery.get("room", ""),
        address_line=delivery.get("address_line", ""),
        postcode=delivery.get("postcode", ""),
        phone=delivery.get("phone", ""),
        delivery_date=delivery["delivery_date"],
        delivery_slot=delivery["delivery_slot"],
        items_total=totals["items_total"],
        bundle_saving=totals["saving"],
        delivery_fee=totals["delivery"],
        total=totals["total"],
        payment_reference=payment.reference if payment else "TEST-" + secrets.token_hex(4).upper(),
        payment_method=payment.method if payment else "",
        card_brand=payment.brand if payment else "",
        card_last4=payment.last4 if payment else "",
    )
    reserve_for_order(Basket.requirements(lines), order)
    order_lines = []
    for line in lines:
        if line.kind == "p":
            p = line.obj
            order_lines.append(OrderLine(order=order, product=p, name=p.name, icon=p.icon, tone=p.tone,
                                         list_price=p.price, unit_price=p.price, quantity=line.quantity,
                                         returnable=p.returnable))
        else:
            b = line.obj
            for p, per, unit in allocate_bundle_price(line.price, line.components):
                order_lines.append(OrderLine(order=order, product=p, bundle=b, bundle_name=line.name, name=p.name,
                                             icon=p.icon, tone=p.tone, list_price=p.price, unit_price=unit,
                                             quantity=per * line.quantity, returnable=p.returnable))
    OrderLine.objects.bulk_create(order_lines)
    note = f"Simulated payment accepted: {order.payment_label}" if payment else "Test payment accepted (simulation)"
    OrderEvent.objects.create(order=order, status=OrderStatus.PLACED, note=note)
    return order


@transaction.atomic
def change_status(order, new_status, by=None, note=""):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if new_status not in order.allowed_transitions():
        raise OrderError(f"An order that is {order.get_status_display().lower()} can’t be changed to {OrderStatus(new_status).label.lower()}.")
    if new_status == OrderStatus.CANCELLED:
        release_for_order(order.product_requirements(), order, reason=Reason.CANCEL, by=by, note=f"{order.number} cancelled")
    if new_status == OrderStatus.DISPATCHED and not order.shipment_number:
        order.shipment_number = f"SHP-{order.pk:05d}"
    order.status = new_status
    order.save(update_fields=["status", "shipment_number", "updated_at"])
    OrderEvent.objects.create(order=order, status=new_status, note=note, by=by)
    return order


def customer_cancel(order, user):
    if order.user_id != user.pk:
        raise OrderError("Not your order.")
    if order.status != OrderStatus.PLACED:
        raise OrderError("Only orders that are not yet being processed can be cancelled.")
    return change_status(order, OrderStatus.CANCELLED, by=user, note="Cancelled by customer")


@transaction.atomic
def decide_return(ret, approve, by, note="", restock=True):
    ret = type(ret).objects.select_for_update().get(pk=ret.pk)
    if ret.status != ReturnStatus.REQUESTED:
        raise OrderError("This return has already been decided.")
    ret.status = ReturnStatus.APPROVED if approve else ReturnStatus.REJECTED
    ret.decision_note = note[:300]
    ret.decided_by = by
    ret.decided_at = timezone.now()
    ret.restock = bool(approve and restock)
    ret.save()
    if approve:
        for item in ret.items.select_related("line"):
            line = item.line
            line.returned_quantity = min(line.quantity, line.returned_quantity + item.quantity)
            line.save(update_fields=["returned_quantity"])
            if ret.restock and line.product_id:
                adjust_stock(line.product_id, item.quantity, Reason.RETURN_RESELLABLE, by=by,
                             note=f"{ret.reference}", order=ret.order)
    return ret
