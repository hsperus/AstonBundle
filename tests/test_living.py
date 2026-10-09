"""AstonBundle Living: residence pages and booking requests."""
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from living.models import Facility, RoomType
from support.models import Enquiry


@pytest.fixture
def rooms(db):
    classic = RoomType.objects.create(name="Classic En-suite", slug="classic-ensuite", summary="s", description="d",
                                      price_per_week=Decimal("189.00"), contract_weeks=44, size_m2=13, bed="Small double",
                                      bathroom="En-suite", kitchen="Shared", rooms_available=3, image_alt="room", sort=1)
    full = RoomType.objects.create(name="Studio", slug="studio", summary="s", description="d",
                                   price_per_week=Decimal("259.00"), contract_weeks=51, size_m2=21, bed="Double",
                                   bathroom="En-suite", kitchen="Private", rooms_available=0, image_alt="studio", sort=2)
    Facility.objects.create(name="Cinema room", slug="cinema", summary="Film nights", icon="spark", image_alt="cinema")
    return classic, full


def valid(room="classic-ensuite", **extra):
    return {"name": "Aylin Demir", "email": "aylin@example.com", "room": room, "move_in": "2027-01-09",
            "needs": "Quiet floor please", "agree": "on", **extra}


def test_overview_lists_rooms_facilities_and_is_in_nav(client, rooms):
    r = client.get(reverse("living:overview"))
    page = r.content.decode()
    assert r.status_code == 200
    assert "Classic En-suite" in page and "Studio" in page and "Cinema room" in page
    assert "Waiting list only" in page  # studio has no rooms left
    assert reverse("living:overview") in client.get(reverse("core:home")).content.decode()


def test_room_page_shows_price_contract_total_and_form(client, rooms):
    r = client.get(reverse("living:room", args=["classic-ensuite"]))
    page = r.content.decode()
    assert r.status_code == 200
    assert "£189.00" in page and "£8,316.00" in page  # 189 × 44 weeks
    assert 'name="move_in"' in page and "no payment is taken" in page.lower()
    assert client.get(reverse("living:room", args=["no-such-room"])).status_code == 404


def test_booking_request_creates_enquiry_for_staff(client, rooms):
    r = client.post(reverse("living:request"), valid())
    assert r.status_code == 302 and r.url == reverse("support:sent")
    e = Enquiry.objects.get()
    assert e.topic == "accommodation" and "Classic En-suite" in e.message and "January 2027" in e.message
    assert e.email == "aylin@example.com"


@pytest.mark.parametrize("change, error", [
    ({"agree": None}, "request, not a booking"),
    ({"move_in": ""}, "Choose a start date"),
    ({"room": "not-a-room"}, "Select a valid choice"),
    ({"email": "nope"}, "Enter an email address"),
])
def test_booking_request_validation(client, rooms, change, error):
    data = {k: v for k, v in {**valid(), **change}.items() if v is not None}
    r = client.post(reverse("living:request"), data)
    assert r.status_code == 200 and error in r.content.decode()
    assert not Enquiry.objects.exists()


def test_booking_request_honeypot_and_get(client, rooms):
    r = client.post(reverse("living:request"), valid(website="spam"))
    assert r.status_code == 200 and not Enquiry.objects.exists()
    assert client.get(reverse("living:request")).url == reverse("living:overview")


def test_room_price_must_be_positive(rooms):
    with pytest.raises(IntegrityError), transaction.atomic():
        RoomType.objects.filter(slug="studio").update(price_per_week=0)


def test_staff_sees_accommodation_requests(client, rooms):
    from accounts.models import Role
    from tests.conftest import make_staff

    client.post(reverse("living:request"), valid())
    client.force_login(make_staff(Role.SUPPORT))
    page = client.get(reverse("staff:enquiries")).content.decode()
    assert "Accommodation" in page
