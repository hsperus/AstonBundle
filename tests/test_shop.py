from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from catalog.models import Product
from inventory.models import StockMovement
from inventory.services import InsufficientStock, StockError, adjust_stock
from orders.basket import Basket
from orders.models import Order, OrderStatus
from orders.services import change_status, place_order

pytestmark = pytest.mark.django_db


def test_category_and_price_filters(client, catalog):
    r = client.get(reverse("catalog:category", args=["kitchen"]) + "?f=1&cat=kitchen&min=10&max=20")
    html = r.content.decode()
    assert "1.7L Kettle" in html and "Pan Set" not in html and "Food Containers" not in html


def test_invalid_price_filter_is_reported_not_crashing(client, catalog):
    r = client.get(reverse("catalog:all") + "?min=abc")
    assert r.status_code == 200 and "must be a number" in r.content.decode()


def test_search_highlights_and_suggests(client, catalog):
    r = client.get(reverse("catalog:search") + "?q=adapter")
    assert "<mark>Adapter</mark>" in r.content.decode()
    r = client.get(reverse("catalog:search") + "?q=adaptor")
    assert "Did you mean" in r.content.decode()


def test_search_escapes_html(client, catalog):
    r = client.get(reverse("catalog:search") + "?q=<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in r.content.decode()


def test_stock_badges(catalog):
    assert catalog["adapter"].stock_label == "Only 3 left"
    assert catalog["lead"].stock_status == "out"


def test_basket_caps_quantity_to_stock(client, catalog):
    client.post(reverse("orders:basket_add"), {"kind": "p", "id": catalog["adapter"].pk, "qty": 10})
    client.get(reverse("orders:basket"))
    # low stock: max 3 per order, and only 3 in stock
    assert client.session["basket"][f"p:{catalog['adapter'].pk}"] <= 3


def test_cannot_add_out_of_stock(client, catalog):
    client.post(reverse("orders:basket_add"), {"kind": "p", "id": catalog["lead"].pk})
    assert not client.session.get("basket")


def test_checkout_requires_login(client, catalog):
    client.post(reverse("orders:basket_add"), {"kind": "p", "id": catalog["kettle"].pk})
    r = client.get(reverse("orders:checkout_delivery"))
    assert r.status_code == 302 and reverse("accounts:signin") in r.url


def _lines(request_like, catalog, items):
    class S(dict):
        modified = False

    class R:
        session = S()
    req = R()
    b = Basket(req)
    for kind, obj, qty in items:
        b.add(kind, obj.pk, qty)
    return b.lines()


def test_order_reduces_stock_including_bundle_components(catalog, student, delivery_data):
    lines = _lines(None, catalog, [("b", catalog["bundle"], 1), ("p", catalog["kettle"], 2)])
    order = place_order(student, lines, delivery_data)
    k = Product.objects.get(pk=catalog["kettle"].pk)
    assert k.stock == 20 - 3
    assert order.total == Decimal("30.00") + Decimal("13.99") * 2
    assert order.bundle_saving == Decimal("13.99") + Decimal("22.00") + Decimal("9.50") - Decimal("30.00")
    assert StockMovement.objects.filter(order=order).count() == 3
    # bundle price is split across its lines
    assert sum(l.line_total for l in order.lines.filter(bundle__isnull=False)) == Decimal("30.00")


def test_insufficient_stock_rolls_back_everything(catalog, student, delivery_data):
    lines = _lines(None, catalog, [("p", catalog["kettle"], 1), ("p", catalog["adapter"], 3)])
    Product.objects.filter(pk=catalog["adapter"].pk).update(stock=1)
    with pytest.raises(InsufficientStock):
        place_order(student, lines, delivery_data)
    assert Order.objects.count() == 0
    assert Product.objects.get(pk=catalog["kettle"].pk).stock == 20


def test_cancel_returns_stock(catalog, student, delivery_data):
    order = place_order(student, _lines(None, catalog, [("p", catalog["pan"], 2)]), delivery_data)
    change_status(order, OrderStatus.CANCELLED)
    assert Product.objects.get(pk=catalog["pan"].pk).stock == 10


def test_invalid_status_transition_rejected(catalog, student, delivery_data):
    from orders.services import OrderError

    order = place_order(student, _lines(None, catalog, [("p", catalog["pan"], 1)]), delivery_data)
    with pytest.raises(OrderError):
        change_status(order, OrderStatus.DELIVERED)


def test_stock_can_never_be_negative(catalog):
    with pytest.raises(StockError):
        adjust_stock(catalog["adapter"].pk, -4, "correction")
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.filter(pk=catalog["adapter"].pk).update(stock=-1)


def test_full_checkout_journey(student_client, catalog, student):
    from orders import slots

    c = student_client
    c.post(reverse("orders:basket_add"), {"kind": "p", "id": catalog["kettle"].pk, "qty": 1})
    c.post(reverse("orders:basket_add"), {"kind": "b", "id": catalog["bundle"].pk})
    d = slots.earliest_date()
    r = c.post(reverse("orders:checkout_delivery") + f"?arrival={d.isoformat()}",
               {"delivery_type": "halls", "recipient_name": "Aylin Demir", "halls": "Canal View Halls", "room": "C-214",
                "phone": "", "delivery_date": d.isoformat(), "delivery_slot": "13-17"})
    assert r.status_code == 302, r.content.decode()[:500]
    assert c.get(reverse("orders:checkout_review")).status_code == 200
    page = c.get(reverse("orders:checkout_payment")).content.decode()
    assert "Do not enter real card details" in page and "card number" not in page.lower()
    r = c.post(reverse("orders:checkout_payment"), {})
    assert "test order" in r.content.decode()  # must tick the box
    r = c.post(reverse("orders:checkout_payment"), {"understand": "1", "method": "card", "card": "visa_ok"})
    order = Order.objects.get()
    assert r.url == reverse("orders:confirmation", args=[order.number])
    assert not c.session.get("basket")
    assert order.user == student and order.status == OrderStatus.PLACED
    assert order.payment_label == "Visa •••• 4242" and order.payment_reference.startswith("pi_sim_")


def test_halls_delivery_needs_room(student_client, catalog):
    from orders import slots

    student_client.post(reverse("orders:basket_add"), {"kind": "p", "id": catalog["kettle"].pk})
    d = slots.earliest_date()
    r = student_client.post(reverse("orders:checkout_delivery"), {"delivery_type": "halls", "recipient_name": "A B",
                                                                  "halls": "", "room": "", "delivery_date": d.isoformat(),
                                                                  "delivery_slot": "09-13"})
    assert r.status_code == 200 and "Choose your halls" in r.content.decode()


def test_customised_bundle_keeps_discount(client, catalog):
    b = catalog["bundle"]
    client.post(reverse("orders:basket_add"), {"kind": "b", "id": b.pk, "customise": "1",
                                               "only": [catalog["kettle"].pk, catalog["pan"].pk]})
    key = next(iter(client.session["basket"]))
    assert key.count(":") == 2
    r = client.get(reverse("orders:basket"))
    line = r.context["lines"][0]
    full = Decimal("13.99") + Decimal("22.00") + Decimal("9.50")
    assert line.price == ((Decimal("13.99") + Decimal("22.00")) * Decimal("30.00") / full).quantize(Decimal("0.01"))


def test_users_cannot_see_other_orders(client, catalog, student, delivery_data):
    from accounts.models import User

    order = place_order(student, _lines(None, catalog, [("p", catalog["pan"], 1)]), delivery_data)
    other = User.objects.create_user("other.s@aston.ac.uk", "Student2026!demo", full_name="O S", email_verified=True)
    client.force_login(other)
    assert client.get(order.get_absolute_url()).status_code == 404
