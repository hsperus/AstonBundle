import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import AuditLog, Role, StaffInvite
from catalog.models import Product
from inventory.models import StockMovement

from .conftest import PW, make_staff

pytestmark = pytest.mark.django_db


def test_anonymous_and_customers_cannot_open_admin(client, student):
    assert reverse("staff:signin") in client.get(reverse("staff:dashboard")).url
    client.force_login(student)
    assert reverse("staff:signin") in client.get(reverse("staff:products")).url


@pytest.mark.parametrize("role,url,expected", [
    (Role.SUPPORT, "staff:products", 403), (Role.SUPPORT, "staff:inventory", 403), (Role.SUPPORT, "staff:customers", 200),
    (Role.STOCK, "staff:customers", 403), (Role.STOCK, "staff:inventory", 200), (Role.STOCK, "staff:access", 403),
    (Role.OWNER, "staff:access", 200),
])
def test_role_permissions_checked_on_server(client, catalog, role, url, expected):
    client.force_login(make_staff(role))
    assert client.get(reverse(url)).status_code == expected


def test_no_public_admin_registration(client):
    assert client.get("/staff/register/").status_code == 404


def test_staff_invite_flow(client, owner):
    client.force_login(owner)
    r = client.post(reverse("staff:access"), {"action": "invite", "email": "new@gmail.com", "role": Role.STOCK})
    assert "@astonbundle.example" in r.content.decode()
    client.post(reverse("staff:access"), {"action": "invite", "email": "new@astonbundle.example", "role": Role.STOCK})
    inv = StaffInvite.objects.get()
    c2 = Client()
    r = c2.post(reverse("staff:accept_invite", args=[inv.token]), {"full_name": "New Staff", "password1": "Warehouse2026!", "password2": "Warehouse2026!"})
    assert r.status_code == 302
    assert c2.get(reverse("staff:accept_invite", args=[inv.token])).status_code == 410  # works once


def test_stock_adjustment_needs_reason_and_is_logged(client, catalog):
    client.force_login(make_staff(Role.STOCK))
    p = catalog["adapter"]
    client.post(reverse("staff:inventory"), {"action": "adjust", "product": p.pk, "direction": "add", "quantity": 5, "reason": ""})
    assert Product.objects.get(pk=p.pk).stock == 3
    client.post(reverse("staff:inventory"), {"action": "adjust", "product": p.pk, "direction": "remove", "quantity": 9, "reason": "damaged"})
    assert Product.objects.get(pk=p.pk).stock == 3  # would go negative
    client.post(reverse("staff:inventory"), {"action": "adjust", "product": p.pk, "direction": "add", "quantity": 5, "reason": "delivery", "note": "PO"})
    assert Product.objects.get(pk=p.pk).stock == 8
    assert StockMovement.objects.filter(product=p, change=5).exists()


def test_product_form_rejects_negative_stock_and_missing_alt(client, catalog):
    client.force_login(make_staff(Role.STOCK))
    p = catalog["kettle"]
    r = client.post(reverse("staff:product_edit", args=[p.pk]), {
        "name": p.name, "category": p.category_id, "sku": p.sku, "summary": "s", "description": "d", "features": "",
        "price": "13.99", "stock": "-3", "low_stock_threshold": 10, "max_per_order": 10, "icon": "kettle", "tone": "",
        "image_alt": "", "is_active": "on", "returnable": "on", "specs_text": ""})
    html = r.content.decode()
    assert "Stock cannot be negative" in html and "alt text" in html.lower()


def test_customer_details_masked_and_reveal_logged(client, student):
    client.force_login(make_staff(Role.SUPPORT))
    r = client.get(reverse("staff:customers") + f"?c={student.pk}")
    assert student.email not in r.content.decode()
    client.post(reverse("staff:customers"), {"customer": student.pk, "action": "reveal"})
    assert AuditLog.objects.filter(action="reveal_customer").count() == 1
    r = client.get(reverse("staff:customers") + f"?c={student.pk}")
    assert student.email in r.content.decode()


def test_csrf_is_enforced(catalog):
    c = Client(enforce_csrf_checks=True)
    r = c.post(reverse("orders:basket_add"), {"kind": "p", "id": catalog["kettle"].pk})
    assert r.status_code == 403


def test_security_headers(client):
    r = client.get(reverse("core:home"))
    assert "default-src 'self'" in r["Content-Security-Policy"]
    assert r["X-Frame-Options"] == "DENY"
    assert r["X-Content-Type-Options"] == "nosniff"


def test_support_can_suspend_and_restore_customer(client, student):
    client.force_login(make_staff(Role.SUPPORT))
    client.post(reverse("staff:customers"), {"customer": student.pk, "action": "suspend"})
    student.refresh_from_db()
    assert not student.is_active
    c2 = Client()
    assert not c2.login(email=student.email, password=PW)
    client.post(reverse("staff:customers"), {"customer": student.pk, "action": "restore"})
    student.refresh_from_db()
    assert student.is_active
    assert AuditLog.objects.filter(action="suspend_customer").exists()


def test_return_photos_are_not_public(client, student, catalog, settings, tmp_path):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from orders.models import Order, ReturnRequest

    settings.MEDIA_ROOT = tmp_path
    from datetime import date
    order = Order.objects.create(user=student, recipient_name="A", delivery_date=date.today(), delivery_slot="09-13")
    r = ReturnRequest.objects.create(order=order, user=student, reason="damaged",
                                     photo=SimpleUploadedFile("dent.jpg", b"\xff\xd8\xff fake", content_type="image/jpeg"))
    assert client.get("/media/" + r.photo.name).status_code == 404
    client.force_login(student)
    assert client.get(reverse("staff:return_photo", args=[r.pk])).status_code == 302
    client.force_login(make_staff(Role.SUPPORT))
    assert client.get(reverse("staff:return_photo", args=[r.pk])).status_code == 200


def test_staff_can_change_own_password(client):
    staff = make_staff(Role.STOCK)
    client.force_login(staff)
    r = client.post(reverse("staff:password"), {"old_password": PW, "new_password1": "Warehouse2027!x", "new_password2": "Warehouse2027!x"})
    assert r.status_code == 302
    staff.refresh_from_db()
    assert staff.check_password("Warehouse2027!x")


def test_staff_can_change_password(client):
    u = make_staff(Role.STOCK)
    client.force_login(u)
    r = client.post(reverse("staff:password"), {"old_password": PW, "new_password1": "Warehouse2027!", "new_password2": "Warehouse2027!"})
    assert r.status_code == 302
    u.refresh_from_db()
    assert u.check_password("Warehouse2027!")


def test_support_can_disable_customer_and_it_is_logged(client, student):
    client.force_login(make_staff(Role.SUPPORT))
    client.post(reverse("staff:customers"), {"customer": student.pk, "action": "disable"})
    student.refresh_from_db()
    assert not student.is_active
    assert AuditLog.objects.filter(action="disable_customer").exists()
