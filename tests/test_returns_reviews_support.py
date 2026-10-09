import pytest
from django.urls import reverse

from catalog.models import Product
from orders.models import OrderStatus, ReturnRequest
from orders.services import change_status, decide_return, place_order
from reviews.models import Review
from support.models import Enquiry

from .test_shop import _lines

pytestmark = pytest.mark.django_db


def delivered(catalog, student, delivery_data, items):
    order = place_order(student, _lines(None, catalog, items), delivery_data)
    for st in (OrderStatus.PROCESSING, OrderStatus.DISPATCHED, OrderStatus.DELIVERED):
        change_status(order, st)
    return order


def test_return_only_after_delivery_and_not_hygiene_items(student_client, catalog, student, delivery_data):
    order = place_order(student, _lines(None, catalog, [("p", catalog["pan"], 1)]), delivery_data)
    r = student_client.get(reverse("orders:return", args=[order.number]))
    assert r.status_code == 302  # not delivered yet
    order = delivered(catalog, student, delivery_data, [("p", catalog["pan"], 1), ("p", catalog["box"], 1)])
    box_line = order.lines.get(product=catalog["box"])
    assert box_line.return_block_reason()
    r = student_client.post(reverse("orders:return", args=[order.number]), {"lines": [box_line.pk], "reason": "damaged", "method": "collect"})
    assert r.status_code == 200 and not ReturnRequest.objects.exists()
    pan_line = order.lines.get(product=catalog["pan"])
    r = student_client.post(reverse("orders:return", args=[order.number]), {"lines": [pan_line.pk], "reason": "not_needed", "method": "collect"})
    assert r.status_code == 302 and ReturnRequest.objects.count() == 1


def test_approved_return_restocks(catalog, student, delivery_data, owner):
    order = delivered(catalog, student, delivery_data, [("p", catalog["pan"], 2)])
    line = order.lines.get()
    ret = ReturnRequest.objects.create(order=order, user=student, reason="not_needed")
    ret.items.create(line=line, quantity=2)
    decide_return(ret, True, owner, restock=True)
    assert Product.objects.get(pk=catalog["pan"].pk).stock == 10
    line.refresh_from_db()
    assert line.returned_quantity == 2


def test_reject_needs_reason(client, catalog, student, delivery_data, owner):
    order = delivered(catalog, student, delivery_data, [("p", catalog["pan"], 1)])
    ret = ReturnRequest.objects.create(order=order, user=student, reason="not_needed")
    ret.items.create(line=order.lines.get(), quantity=1)
    client.force_login(owner)
    client.post(reverse("staff:returns"), {"ret": ret.pk, "action": "reject", "note": ""})
    ret.refresh_from_db()
    assert ret.status == "requested"
    client.post(reverse("staff:returns"), {"ret": ret.pk, "action": "reject", "note": "Item was used."})
    ret.refresh_from_db()
    assert ret.status == "rejected"


def test_only_buyers_can_review_once(student_client, catalog, student, delivery_data):
    url = reverse("reviews:write", args=[catalog["kettle"].slug])
    assert student_client.get(url).status_code == 302  # has not bought it
    delivered(catalog, student, delivery_data, [("p", catalog["kettle"], 1)])
    r = student_client.post(url, {"rating": 4, "title": "Fast", "body": "Boils quickly and quietly.", "course": ""})
    assert r.status_code == 302
    p = Product.objects.get(pk=catalog["kettle"].pk)
    assert p.rating_count == 1 and float(p.rating_avg) == 4.0
    student_client.post(url, {"rating": 1, "title": "Again", "body": "Second review attempt."})
    assert Review.objects.count() == 1


def test_contact_form_validation_and_storage(client):
    url = reverse("support:contact")
    r = client.post(url, {"name": "Mateo", "email": "m@gmail.com", "topic": "delivery", "message": "Hi"})
    html = r.content.decode()
    assert "aston.ac.uk" in html and "at least 20 characters" in html
    r = client.post(url, {"name": "Mateo", "email": "m.r@aston.ac.uk", "topic": "delivery",
                          "message": "Can you deliver the morning after I land?"})
    assert r.status_code == 302 and Enquiry.objects.count() == 1
    assert Enquiry.objects.get().reference.startswith("ENQ-")


def test_contact_honeypot_blocks_bots(client):
    client.post(reverse("support:contact"), {"name": "Bot", "email": "b.b@aston.ac.uk", "topic": "other",
                                             "message": "Buy cheap things now please now", "website": "spam.example"})
    assert not Enquiry.objects.exists()
