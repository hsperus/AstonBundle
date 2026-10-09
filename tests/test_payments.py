"""Simulated Stripe-style card payments and Apple Pay (orders/payments.py)."""
import pytest
from django.urls import reverse

from catalog.models import Product
from orders.models import Order
from orders import slots


@pytest.fixture
def at_payment(student_client, catalog):
    """A signed-in student with a kettle in the basket, on the payment step."""
    c = student_client
    c.post(reverse("orders:basket_add"), {"kind": "p", "id": catalog["kettle"].pk, "qty": 1})
    d = slots.earliest_date()
    r = c.post(reverse("orders:checkout_delivery") + f"?arrival={d.isoformat()}",
               {"delivery_type": "halls", "recipient_name": "Aylin Demir", "halls": "Canal View Halls", "room": "C-214",
                "phone": "", "delivery_date": d.isoformat(), "delivery_slot": "13-17"})
    assert r.status_code == 302
    return c


def pay(c, **data):
    return c.post(reverse("orders:checkout_payment"), {"understand": "1", **data})


def test_payment_page_has_no_card_number_field(at_payment):
    page = at_payment.get(reverse("orders:checkout_payment")).content.decode()
    assert "Apple Pay" in page and "Visa •••• 4242" in page
    assert 'name="number"' not in page and "cvc" not in page.lower() and "card number" not in page.lower()


def test_must_choose_a_method_and_tick_the_box(at_payment):
    assert "Choose how you want to pay" in pay(at_payment).content.decode()
    r = at_payment.post(reverse("orders:checkout_payment"), {"method": "card", "card": "visa_ok"})
    assert "test order" in r.content.decode()
    assert not Order.objects.exists()


@pytest.mark.parametrize("card, message", [("declined", "declined"), ("no_funds", "insufficient funds"),
                                           ("expired", "expired"), ("made-up", "Choose one of the test cards")])
def test_failed_card_creates_no_order_and_keeps_stock(at_payment, catalog, card, message):
    stock = Product.objects.get(pk=catalog["kettle"].pk).stock
    r = pay(at_payment, method="card", card=card)
    assert r.status_code == 200 and message in r.content.decode()
    assert not Order.objects.exists()
    assert Product.objects.get(pk=catalog["kettle"].pk).stock == stock
    assert at_payment.session.get("basket")  # basket kept so the student can try again


def test_successful_card_records_only_brand_last4_and_reference(at_payment):
    r = pay(at_payment, method="card", card="mc_ok")
    order = Order.objects.get()
    assert r.url == reverse("orders:confirmation", args=[order.number])
    assert (order.payment_method, order.card_brand, order.card_last4) == ("card", "Mastercard", "4444")
    assert order.payment_reference.startswith("pi_sim_")
    assert "Mastercard •••• 4444" in at_payment.get(r.url).content.decode()


def test_3d_secure_approve(at_payment):
    r = pay(at_payment, method="card", card="3ds")
    assert r.url == reverse("orders:checkout_authenticate") and not Order.objects.exists()
    assert "Confirm this payment" in at_payment.get(r.url).content.decode()
    r = at_payment.post(r.url, {"action": "approve"})
    order = Order.objects.get()
    assert r.url == reverse("orders:confirmation", args=[order.number]) and order.card_last4 == "3155"


def test_3d_secure_fail_creates_no_order(at_payment):
    pay(at_payment, method="card", card="3ds")
    r = at_payment.post(reverse("orders:checkout_authenticate"), {"action": "fail"})
    assert "could not authenticate" in r.content.decode() and not Order.objects.exists()
    # the pending payment is cleared, so the 3-D Secure page cannot be reused
    assert at_payment.get(reverse("orders:checkout_authenticate")).url == reverse("orders:checkout_payment")


def test_3d_secure_page_needs_a_pending_payment(at_payment):
    r = at_payment.post(reverse("orders:checkout_authenticate"), {"action": "approve"})
    assert r.url == reverse("orders:checkout_payment") and not Order.objects.exists()


def test_apple_pay_confirm(at_payment):
    r = pay(at_payment, method="apple_pay")
    assert r.url == reverse("orders:checkout_wallet")
    assert "Confirm with Face ID" in at_payment.get(r.url).content.decode()
    r = at_payment.post(r.url, {"action": "pay"})
    order = Order.objects.get()
    assert r.url == reverse("orders:confirmation", args=[order.number])
    assert order.payment_method == "apple_pay" and order.payment_label == "Apple Pay · Visa •••• 4242"


def test_apple_pay_cancel_and_direct_access(at_payment):
    pay(at_payment, method="apple_pay")
    r = at_payment.post(reverse("orders:checkout_wallet"), {"action": "cancel"})
    assert r.url == reverse("orders:checkout_payment") and not Order.objects.exists()
    r = at_payment.post(reverse("orders:checkout_wallet"), {"action": "pay"})  # sheet closed: cannot pay
    assert r.url == reverse("orders:checkout_payment") and not Order.objects.exists()
