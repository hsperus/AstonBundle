from datetime import date, timedelta

import pytest
from django.utils import timezone

from ai import forecast, recommender
from ai.models import ModelRun, ProductForecast
from catalog.models import Product
from inventory.models import PurchaseOrder
from orders.models import Order, OrderLine

pytestmark = pytest.mark.django_db


def make_orders(student, catalog, n=60):
    now = timezone.now()
    k, pan, ad, box = catalog["kettle"], catalog["pan"], catalog["adapter"], catalog["box"]
    for i in range(n):
        o = Order.objects.create(user=student, recipient_name="A", delivery_date=date.today(), delivery_slot="09-13",
                                 created_at=now - timedelta(days=n - i))
        items = [k, pan] if i % 2 == 0 else [ad, box]
        if i % 5 == 0:
            items.append(box)
        for p in dict.fromkeys(items):
            OrderLine.objects.create(order=o, product=p, name=p.name, list_price=p.price, unit_price=p.price, quantity=1)


def test_association_rules_learn_co_purchases(student, catalog):
    make_orders(student, catalog)
    run = recommender.train()
    assert run.metrics["hit_rate_at_3"] >= run.metrics["baseline_hit_rate_at_3"]
    recs = recommender.recommend([catalog["kettle"].pk], k=2)
    assert recs and recs[0] == catalog["pan"]


def test_recommendations_never_include_out_of_stock(student, catalog):
    make_orders(student, catalog)
    recommender.train()
    Product.objects.filter(pk=catalog["pan"].pk).update(stock=0)
    recs = recommender.recommend([catalog["kettle"].pk], k=4)
    assert catalog["pan"] not in recs


def test_rules_require_lift_above_one(student, catalog):
    make_orders(student, catalog)
    run = recommender.train()
    assert all(a.lift > 1 for a in run.associations.all())


def test_intake_period_helpers():
    s, e, intake = forecast.next_intake_period(date(2026, 10, 9))
    assert intake == date(2027, 1, 8) and s < intake < e and s.weekday() == 0
    s, e, last = forecast.last_completed_period(date(2026, 10, 9))
    assert last == date(2026, 9, 14)


def test_suggested_reorder_formula(catalog):
    run = ModelRun.objects.create(kind="forecast", version="t")
    p = catalog["adapter"]  # stock 3
    f = ProductForecast.objects.create(run=run, product=p, period_start=date.today(), period_end=date.today(), low=10,
                                       mid=20, high=30, confidence="High")
    assert f.suggested_reorder == 30 - 3
    PurchaseOrder.objects.create(product=p, quantity=10)
    assert f.suggested_reorder == 30 - 3 - 10
