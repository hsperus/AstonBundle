from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMessage
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.models import HALLS
from ai.recommender import recommend
from catalog.models import Bundle, Product
from inventory.services import InsufficientStock

from . import payments, slots
from .basket import Basket
from .forms import DeliveryForm, ReturnForm
from .models import Order, OrderStatus, ReturnItem, ReturnRequest
from .services import OrderError, customer_cancel, place_order

CHECKOUT_KEY = "checkout"
PAY_KEY = "pending_payment"  # card id waiting for 3-D Secure, or "wallet" while the Apple Pay sheet is open


def _next(request, default):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return default


def _qty(value, default=1):
    try:
        q = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(10, q))


# ---------------------------------------------------------------- basket
@require_POST
def basket_add(request):
    basket = Basket(request)
    kind = request.POST.get("kind")
    try:
        obj_id = int(request.POST.get("id", ""))
    except ValueError:
        raise Http404
    qty = _qty(request.POST.get("qty"))
    if kind == "p":
        p = get_object_or_404(Product, pk=obj_id, is_active=True)
        already = basket.data.get(f"p:{p.pk}", 0)
        if p.stock <= 0:
            messages.error(request, f"Sorry, {p.name} is out of stock.")
        elif already + qty > p.order_limit:
            allowed = max(0, p.order_limit - already)
            if allowed:
                basket.add("p", p.pk, allowed)
                messages.warning(request, f"Only {p.order_limit} per order — we added {allowed}.", extra_tags="basket")
            else:
                messages.error(request, f"You already have the maximum of {p.name} in your basket.")
        else:
            basket.add("p", p.pk, qty)
            messages.success(request, f"Added {p.name} to your basket.", extra_tags="basket")
    elif kind == "b":
        b = get_object_or_404(Bundle, pk=obj_id, is_active=True)
        only = None
        if request.POST.get("customise"):
            valid = set(b.items.values_list("product_id", flat=True))
            try:
                only = sorted({int(x) for x in request.POST.getlist("only")} & valid)
            except ValueError:
                only = []
            if len(only) < 2:
                messages.error(request, "A customised bundle needs at least 2 items.")
                return redirect(_next(request, b.get_absolute_url()))
            if len(only) == len(valid):
                only = None
        comps = [(i.product, i.quantity) for i in b.items.select_related("product")]
        if only:
            comps = [(p, q) for p, q in comps if p.pk in only]
        if any(p.stock < q or not p.is_active for p, q in comps):
            messages.error(request, "Some items in this bundle are out of stock. Tick “Customise bundle” and remove them.")
            return redirect(_next(request, b.get_absolute_url()))
        basket.add("b", b.pk, qty, only=only)
        messages.success(request, f"Added {b.name}{' (customised)' if only else ''} to your basket.", extra_tags="basket")
    else:
        raise Http404
    return redirect(_next(request, reverse("orders:basket")))


@require_POST
def basket_add_many(request):
    basket = Basket(request)
    added = 0
    for pid in request.POST.getlist("p")[:10]:
        try:
            p = Product.objects.get(pk=int(pid), is_active=True)
        except (ValueError, Product.DoesNotExist):
            continue
        if p.stock > 0 and basket.data.get(f"p:{p.pk}", 0) < p.order_limit:
            basket.add("p", p.pk, 1)
            added += 1
    if added:
        messages.success(request, f"Added {added} item{'s' if added > 1 else ''} to your basket.", extra_tags="basket")
    else:
        messages.error(request, "Choose at least one item that is in stock.")
    return redirect(_next(request, reverse("orders:basket")))


def basket_view(request):
    basket = Basket(request)
    if request.method == "POST":
        key = request.POST.get("key", "")
        if "remove" in request.POST:
            basket.remove(key)
            messages.success(request, "Item removed from your basket.")
        elif "qty" in request.POST:
            try:
                q = int(request.POST.get("qty"))
            except (TypeError, ValueError):
                q = 1
            basket.set(key, max(0, min(10, q)))
        return redirect("orders:basket")
    lines = basket.lines()
    totals = Basket.totals(lines)
    product_ids = [l.obj.pk for l in lines if l.kind == "p"] + [p.pk for l in lines if l.kind == "b" for p, _ in l.components]
    recs = recommend(product_ids, k=1, exclude=product_ids) if lines else []
    blocked = any(l.max_quantity == 0 for l in lines)
    return render(request, "orders/basket.html", {"lines": lines, "totals": totals, "rec": recs[0] if recs else None,
                                                  "blocked": blocked, "count": sum(l.quantity for l in lines)})


# ---------------------------------------------------------------- checkout
def _checkout_guard(request):
    lines = Basket(request).lines()
    if not lines:
        messages.info(request, "Your basket is empty.")
        return None, redirect("orders:basket")
    if any(l.max_quantity == 0 or l.warning for l in lines):
        messages.error(request, "Please check your basket: some quantities changed.")
        return None, redirect("orders:basket")
    return lines, None


def _arrival(request):
    raw = request.GET.get("arrival") or request.session.get("arrival_date")
    try:
        d = date.fromisoformat(raw) if raw else None
    except ValueError:
        d = None
    if d is None and request.user.arrival_date:
        d = request.user.arrival_date
    if d is None or d < slots.earliest_date():
        d = slots.earliest_date() + timedelta(days=slots.WINDOW_DAYS)
    return d


@login_required
def checkout_delivery(request):
    if request.user.is_staff:
        messages.error(request, "Staff accounts can’t place orders. Sign in as a student.")
        return redirect("orders:basket")
    lines, resp = _checkout_guard(request)
    if resp:
        return resp
    arrival = _arrival(request)
    saved = request.session.get(CHECKOUT_KEY, {})
    u = request.user
    initial = saved or {"recipient_name": u.full_name, "halls": u.halls if u.halls != "Other / private housing" else "",
                        "room": u.room, "phone": u.phone, "delivery_type": "halls"}
    form = DeliveryForm(request.POST or None, initial=initial, available=slots.slot_available)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        request.session[CHECKOUT_KEY] = {**{k: v for k, v in d.items() if k != "delivery_date"},
                                         "delivery_date": d["delivery_date"].isoformat()}
        request.session["arrival_date"] = arrival.isoformat()
        return redirect("orders:checkout_review")
    days = slots.days_for(arrival)
    chosen_date = request.POST.get("delivery_date") or saved.get("delivery_date") or ""
    chosen_slot = request.POST.get("delivery_slot") or saved.get("delivery_slot") or ""
    return render(request, "orders/checkout_delivery.html", {
        "form": form, "days": days, "arrival": arrival, "lines": lines, "totals": Basket.totals(lines),
        "chosen_date": chosen_date, "chosen_slot": chosen_slot, "earliest": slots.earliest_date(), "step": 1,
        "halls_choices": [h for h in HALLS if h[0] != "Other / private housing"],
    })


def _saved_delivery(request):
    data = request.session.get(CHECKOUT_KEY)
    if not data:
        return None
    try:
        data = {**data, "delivery_date": date.fromisoformat(data["delivery_date"])}
    except (KeyError, ValueError):
        return None
    return data


@login_required
def checkout_review(request):
    lines, resp = _checkout_guard(request)
    if resp:
        return resp
    delivery = _saved_delivery(request)
    if not delivery:
        return redirect("orders:checkout_delivery")
    if request.method == "POST":
        return redirect("orders:checkout_payment")
    return render(request, "orders/checkout_review.html", {"lines": lines, "totals": Basket.totals(lines),
                                                           "d": delivery, "step": 2,
                                                           "slot_label": dict(slots.SLOTS)[delivery["delivery_slot"]]})


def _payment_context(request, lines, delivery, **extra):
    return {"lines": lines, "totals": Basket.totals(lines), "d": delivery, "step": 3,
            "slot_label": dict(slots.SLOTS)[delivery["delivery_slot"]], "cards": payments.TEST_CARDS, **extra}


def _payment_start(request):
    """Shared guard for every payment step: basket and delivery must still be valid."""
    lines, resp = _checkout_guard(request)
    if resp:
        return None, None, resp
    delivery = _saved_delivery(request)
    if not delivery:
        return None, None, redirect("orders:checkout_delivery")
    return lines, delivery, None


def _finish_order(request, lines, delivery, payment):
    """Create the order after a simulated payment has succeeded."""
    request.session.pop(PAY_KEY, None)
    if not slots.slot_available(delivery["delivery_date"], delivery["delivery_slot"]):
        messages.error(request, "Sorry, that delivery slot was just booked. Please choose another. No money was taken.")
        return redirect("orders:checkout_delivery")
    try:
        order = place_order(request.user, lines, delivery, payment)
    except InsufficientStock as e:
        names = ", ".join(Product.objects.filter(pk__in=[pid for pid, _ in e.problems]).values_list("name", flat=True))
        messages.error(request, f"Sorry, there is no longer enough stock for: {names}. We updated your basket. No money was taken.")
        return redirect("orders:basket")
    except OrderError as e:
        messages.error(request, str(e))
        return redirect("orders:basket")
    Basket(request).clear()
    request.session.pop(CHECKOUT_KEY, None)
    _confirmation_email(request, order)
    return redirect("orders:confirmation", number=order.number)


@login_required
def checkout_payment(request):
    lines, delivery, resp = _payment_start(request)
    if resp:
        return resp
    error, card_id = "", request.POST.get("card", "visa_ok")
    if request.method == "POST":
        method = request.POST.get("method")
        if request.POST.get("understand") != "1":
            error = "Please confirm that you understand this is a test order."
        elif method == payments.APPLE_PAY:
            request.session[PAY_KEY] = "wallet"
            return redirect("orders:checkout_wallet")
        elif method == payments.CARD:
            payment = payments.charge_card(card_id)
            if payment.status == "requires_action":
                request.session[PAY_KEY] = card_id
                return redirect("orders:checkout_authenticate")
            if payment.ok:
                return _finish_order(request, lines, delivery, payment)
            error = payment.message
        else:
            error = "Choose how you want to pay."
    return render(request, "orders/checkout_payment.html", _payment_context(request, lines, delivery, error=error,
                                                                            card_id=card_id))


@login_required
def checkout_authenticate(request):
    """Simulated 3-D Secure page, as a bank would show it."""
    lines, delivery, resp = _payment_start(request)
    if resp:
        return resp
    card_id = request.session.get(PAY_KEY)
    if card_id not in payments.TEST_CARDS:
        return redirect("orders:checkout_payment")
    if request.method == "POST":
        payment = payments.confirm_3ds(card_id, request.POST.get("action") == "approve")
        if payment.ok:
            return _finish_order(request, lines, delivery, payment)
        request.session.pop(PAY_KEY, None)
        return render(request, "orders/checkout_payment.html", _payment_context(request, lines, delivery,
                                                                                error=payment.message, card_id=card_id))
    _label, brand, last4, _o, _m = payments.TEST_CARDS[card_id]
    return render(request, "orders/checkout_authenticate.html", _payment_context(request, lines, delivery,
                                                                                 brand=brand, last4=last4))


@login_required
def checkout_wallet(request):
    """Simulated Apple Pay sheet."""
    lines, delivery, resp = _payment_start(request)
    if resp:
        return resp
    if request.session.get(PAY_KEY) != "wallet":
        return redirect("orders:checkout_payment")
    if request.method == "POST":
        if request.POST.get("action") == "pay":
            return _finish_order(request, lines, delivery, payments.charge_wallet())
        request.session.pop(PAY_KEY, None)
        messages.info(request, "Apple Pay was cancelled. No money was taken.")
        return redirect("orders:checkout_payment")
    brand, last4 = payments.WALLET_CARD
    return render(request, "orders/checkout_wallet.html", _payment_context(request, lines, delivery,
                                                                           brand=brand, last4=last4))


def _confirmation_email(request, order):
    from accounts.views import _allow_inbox

    items = "\n".join(f"- {l.quantity} × {l.name}" for l in order.lines.all())
    body = (f"Hello {order.user.first_name},\n\nThank you! Order {order.number} is confirmed (test order — no payment taken).\n\n"
            f"{items}\n\nTotal: £{order.total}\nDelivery: {order.delivery_date.strftime('%A')} {order.delivery_date.day} {order.delivery_date.strftime('%B')}, {order.slot_label}\n"
            f"To: {order.address_display}\n\nTrack your order: {request.build_absolute_uri(order.get_absolute_url())}")
    EmailMessage(f"Order {order.number} confirmed", body, settings.DEFAULT_FROM_EMAIL, [order.user.email],
                 headers={"X-AB-Kind": "order"}).send()
    _allow_inbox(request, order.user.email)


@login_required
def confirmation(request, number):
    order = get_object_or_404(Order.objects.prefetch_related("lines__product"), number=number, user=request.user)
    groups = _group_lines(order)
    change_until = order.delivery_date - timedelta(days=4)
    return render(request, "orders/confirmation.html", {"order": order, "groups": groups, "change_until": change_until})


def _group_lines(order):
    """Group bundle lines back into one row for summaries."""
    groups, seen = [], {}
    for l in order.lines.all():
        if l.bundle_name:
            if l.bundle_name not in seen:
                seen[l.bundle_name] = {"name": l.bundle_name, "icon": "gift", "tone": "n", "total": 0, "bundle": True}
                groups.append(seen[l.bundle_name])
            seen[l.bundle_name]["total"] += l.line_total
        else:
            groups.append({"name": l.name + (f" ×{l.quantity}" if l.quantity > 1 else ""), "icon": l.icon, "tone": l.tone,
                           "image": l.product.image.url if l.product and l.product.image else "",
                           "total": l.line_total, "bundle": False})
    return groups


# ---------------------------------------------------------------- customer orders
TABS = [("all", "All"), ("active", "Active"), ("delivered", "Delivered"), ("returns", "Returns")]


@login_required
def order_list(request):
    if request.user.is_staff:
        return redirect("staff:orders")
    qs = request.user.orders.prefetch_related("lines", "returns", "events")
    tab = request.GET.get("tab", "all")
    all_orders = list(qs)
    buckets = {
        "all": all_orders,
        "active": [o for o in all_orders if o.status in (OrderStatus.PLACED, OrderStatus.PROCESSING, OrderStatus.DISPATCHED)],
        "delivered": [o for o in all_orders if o.status == OrderStatus.DELIVERED],
        "returns": [o for o in all_orders if o.returns.all()],
    }
    if tab not in buckets:
        tab = "all"
    tabs = [(k, l, len(buckets[k])) for k, l in TABS]
    return render(request, "orders/order_list.html", {"orders": buckets[tab], "tab": tab, "tabs": tabs})


@login_required
def order_detail(request, number):
    order = get_object_or_404(Order.objects.prefetch_related("lines__product", "lines__return_items__request", "events", "returns"),
                              number=number, user=request.user)
    events = {e.status: e for e in order.events.all()}
    steps = []
    for st in [OrderStatus.PLACED, OrderStatus.PROCESSING, OrderStatus.DISPATCHED, OrderStatus.DELIVERED]:
        ev = events.get(st)
        steps.append({"label": OrderStatus(st).label, "done": ev is not None, "ev": ev})
    reviewed = set(request.user.reviews.values_list("product_id", flat=True))
    lines = []
    for l in order.lines.all():
        lines.append({"l": l, "block": l.return_block_reason(), "pending": l.pending_return(),
                      "can_review": order.status == OrderStatus.DELIVERED and l.product_id and l.product_id not in reviewed})
    bundle_names = sorted({l.bundle_name for l in order.lines.all() if l.bundle_name})
    return render(request, "orders/order_detail.html", {"order": order, "steps": steps, "lines": lines,
                                                        "cancelled": order.status == OrderStatus.CANCELLED,
                                                        "cancel_event": events.get(OrderStatus.CANCELLED),
                                                        "bundle_names": bundle_names})


@login_required
@require_POST
def order_cancel(request, number):
    order = get_object_or_404(Order, number=number, user=request.user)
    try:
        customer_cancel(order, request.user)
        messages.success(request, f"Order {order.number} has been cancelled. No payment was taken.")
    except OrderError as e:
        messages.error(request, str(e))
    return redirect(order.get_absolute_url())


@login_required
def return_request(request, number):
    order = get_object_or_404(Order.objects.prefetch_related("lines"), number=number, user=request.user)
    all_lines = list(order.lines.all())
    eligible = [l for l in all_lines if l.return_block_reason() is None]
    if not eligible:
        messages.error(request, "There are no items in this order that can be returned now.")
        return redirect(order.get_absolute_url())
    choices = [(str(l.pk), l.name) for l in eligible]
    pre = request.GET.get("line")
    form = ReturnForm(request.POST or None, request.FILES or None, line_choices=choices,
                      initial={"lines": [pre] if pre else [], "method": "collect"})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            r = ReturnRequest.objects.create(order=order, user=request.user, reason=d["reason"], comments=d["comments"],
                                             photo=d.get("photo") or "", method=d["method"])
            for lid in d["lines"]:
                line = next(l for l in eligible if str(l.pk) == lid)
                ReturnItem.objects.create(request=r, line=line, quantity=line.returnable_quantity())
        return redirect("orders:return_done", reference=r.reference)
    return render(request, "orders/return_form.html", {"order": order, "form": form, "all_lines": all_lines,
                                                       "eligible_ids": {str(l.pk) for l in eligible},
                                                       "selected": set(form["lines"].value() or [])})


@login_required
def return_done(request, reference):
    r = get_object_or_404(ReturnRequest.objects.select_related("order"), reference=reference, user=request.user)
    return render(request, "orders/return_done.html", {"r": r})
