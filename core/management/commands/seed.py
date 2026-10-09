"""Load the fictional AstonBundle catalogue, test accounts and a synthetic order
history (used for the dashboard and to train the AI models).

    python manage.py seed            # catalogue + accounts + history + train AI
    python manage.py seed --reset    # wipe orders/reviews/etc first
    python manage.py seed --no-history

Everything created here is TEST DATA. No real people, orders or payments.
"""
import math
import os
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files import File
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import DemoEmail, Role, User
from catalog.models import Bundle, BundleItem, Category, Product
from catalog.seed_data import BUNDLES, CATEGORIES, PRODUCTS
from inventory.models import PurchaseOrder, Reason, StockMovement
from orders.basket import allocate_bundle_price
from orders.models import Order, OrderEvent, OrderLine, OrderStatus, ReturnItem, ReturnRequest, ReturnStatus
from reviews.models import Review, refresh_product_rating
from support.models import Enquiry

SEED_IMAGES = settings.BASE_DIR / "catalog" / "seed_images"

DEMO_PASSWORDS = {
    "customer": os.environ.get("SEED_CUSTOMER_PASSWORD", "Student2026!demo"),
    "owner": os.environ.get("SEED_OWNER_PASSWORD", "Owner2026!demo"),
    "stock": os.environ.get("SEED_STOCK_PASSWORD", "Stock2026!demo"),
    "support": os.environ.get("SEED_SUPPORT_PASSWORD", "Support2026!demo"),
}

FIRST = ["Aylin", "Priya", "Chen", "Tolu", "Mehmet", "Sophie", "Wei", "Arjun", "Fatima", "Lucas", "Amara", "Yusuf",
         "Hannah", "Kwame", "Mei", "Omar", "Isabel", "Ravi", "Zara", "Daniel", "Aisha", "Jun", "Elif", "Samuel",
         "Nadia", "Hao", "Grace", "Ibrahim", "Lena", "Kofi", "Ananya", "Tom", "Leila", "Marco", "Ngozi", "Yuki"]
LAST = ["Demir", "Nair", "Wang", "Adeyemi", "Kaya", "Brown", "Li", "Patel", "Hassan", "Silva", "Okafor", "Khan",
        "Smith", "Mensah", "Zhang", "Ali", "Garcia", "Sharma", "Ahmed", "Jones", "Bello", "Liu", "Yildiz", "Owusu",
        "Rahman", "Chen", "Taylor", "Musa", "Fischer", "Boateng", "Iyer", "Evans", "Haddad", "Rossi", "Eze", "Sato"]
COURSES = ["MSc Business Analytics", "Mechanical Engineering", "Pharmacy", "Computer Science", "Psychology",
           "MSc Data Science", "Biomedical Science", "Optometry", "Law", "International Business",
           "Chemical Engineering", "MBA", "Economics", "Marketing", "Civil Engineering"]

REVIEW_TEXT = {
    5: [("Exactly what I needed", "Arrived at halls reception before I landed. Simple and good quality."),
        ("Great value", "Cheaper than buying in town during freshers week, and no carrying."),
        ("Very happy", "Works well and looks nice in my room. Would buy again."),
        ("Life saver", "I arrived late at night and everything was ready. Thank you!")],
    4: [("Good, small issue", "Good quality for the price. Packaging was a bit big."),
        ("Does the job", "Works as described. Delivery was on the day I chose."),
        ("Nice", "Happy with it. I would like more colour options.")],
    3: [("OK", "It is fine but not amazing. Fair for a student budget."),
        ("Average", "Works, but feels a bit cheap.")],
    2: [("Not great", "It works but quality is lower than I expected.")],
    1: [("Disappointed", "Did not last long. I requested a return.")],
}
PRODUCT_QUALITY = {}  # sku -> mean rating, set in _history


def daterange_weeks(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=7)


def intake_intensity(d):
    """Synthetic demand curve: big September intake, smaller January intake, low baseline."""
    def bump(center, width, height):
        days = (d - center).days
        return height * math.exp(-0.5 * (days / width) ** 2)

    total = 0.0
    for year in (d.year - 1, d.year, d.year + 1):
        total += bump(date(year, 9, 14), 16, 1.0)  # September intake
        total += bump(date(year, 1, 8), 10, 0.45)  # January intake
    return total


class Command(BaseCommand):
    help = "Load fictional catalogue, demo accounts and synthetic history (test data only)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete orders, reviews, enquiries and synthetic users first.")
        parser.add_argument("--no-history", action="store_true", help="Skip the synthetic order history and AI training.")
        parser.add_argument("--seed", type=int, default=2026)

    def handle(self, *args, **opts):
        self.rng = random.Random(opts["seed"])
        if opts["reset"]:
            self._reset()
        self._catalogue()
        self._accounts()
        if not opts["no_history"] and not Order.objects.filter(is_test_data=True).exists():
            self._history()
            self._demo_customer_orders()
            self._enquiries()
            self._stock_log()
            self._final_stock()
            self.stdout.write("Training AI models on the synthetic history…")
            call_command("train_models", verbosity=0)
        self.stdout.write(self.style.SUCCESS("Seed complete. Test accounts:"))
        self.stdout.write(f"  Customer: demo.student@aston.ac.uk / {DEMO_PASSWORDS['customer']}")
        self.stdout.write(f"  Owner:    owner@astonbundle.example / {DEMO_PASSWORDS['owner']}")
        self.stdout.write(f"  Stock:    stock@astonbundle.example / {DEMO_PASSWORDS['stock']}")
        self.stdout.write(f"  Support:  support@astonbundle.example / {DEMO_PASSWORDS['support']}")

    # ------------------------------------------------------------------
    def _reset(self):
        from ai.models import ModelRun

        ModelRun.objects.all().delete()
        ReturnRequest.objects.all().delete()
        Review.objects.all().delete()
        StockMovement.objects.all().delete()
        PurchaseOrder.objects.all().delete()
        Order.objects.all().delete()
        Enquiry.objects.all().delete()
        DemoEmail.objects.all().delete()
        User.objects.filter(is_test_data=True).delete()
        self.stdout.write("Reset done.")

    @transaction.atomic
    def _catalogue(self):
        cats = {}
        for i, (slug, name, icon, tone, desc) in enumerate(CATEGORIES):
            cats[slug], _ = Category.objects.update_or_create(
                slug=slug, defaults=dict(name=name, icon=icon, tone=tone, description=desc, sort=i)
            )
        for (sku, cat, name, price, stock, th, icon, tone, summary, alt, returnable, feats, specs, desc) in PRODUCTS:
            p, _ = Product.objects.update_or_create(
                sku=sku,
                defaults=dict(category=cats[cat], name=name, price=Decimal(price), low_stock_threshold=th, icon=icon,
                              tone=tone, summary=summary, image_alt=alt, returnable=returnable, features=feats,
                              specs=specs, description=desc, max_per_order=10),
            )
            # Product photos are AI-generated (see docs/AI_USE_NOTE.md); keep any image staff uploaded since.
            img = SEED_IMAGES / f"{sku}.webp"
            if img.exists() and not p.image:
                with img.open("rb") as f:
                    p.image.save(img.name, File(f), save=True)
        by_sku = {p.sku: p for p in Product.objects.all()}
        for (slug, name, tagline, price, icons, tone, sort, items, desc) in BUNDLES:
            b, _ = Bundle.objects.update_or_create(
                slug=slug, defaults=dict(name=name, tagline=tagline, price=Decimal(price), icons=icons, tone=tone,
                                         sort=sort, description=desc, featured=sort <= 4)
            )
            b.items.all().delete()
            for sku, q in items:
                BundleItem.objects.create(bundle=b, product=by_sku[sku], quantity=q)
        self.stdout.write(f"Catalogue: {Category.objects.count()} categories, {Product.objects.count()} products, {Bundle.objects.count()} bundles.")

    def _accounts(self):
        def ensure(email, name, role, pw, **extra):
            u = User.objects.filter(email=email).first()
            if u is None:
                if role == Role.CUSTOMER:
                    u = User.objects.create_user(email, pw, full_name=name, email_verified=True, **extra)
                else:
                    u = User.objects.create_staff(email, pw, role=role, full_name=name)
            return u

        ensure("owner@astonbundle.example", "Owner (demo)", Role.OWNER, DEMO_PASSWORDS["owner"])
        ensure("stock@astonbundle.example", "Stock manager (demo)", Role.STOCK, DEMO_PASSWORDS["stock"])
        ensure("support@astonbundle.example", "Support (demo)", Role.SUPPORT, DEMO_PASSWORDS["support"])
        ensure("demo.student@aston.ac.uk", "Aylin Demir", Role.CUSTOMER, DEMO_PASSWORDS["customer"],
               halls="Canal View Halls", room="C-214", arrival_date=date(2027, 1, 9))

    # ------------------------------------------------------------------
    def _history(self):
        rng = self.rng
        now = timezone.now()
        today = timezone.localdate()
        start = date(2024, 7, 29)
        products = {p.sku: p for p in Product.objects.all()}
        bundles = {b.slug: b for b in Bundle.objects.prefetch_related("items__product")}
        for sku in products:
            PRODUCT_QUALITY[sku] = rng.uniform(3.9, 4.8)
        PRODUCT_QUALITY["KT-004"] = 4.6
        PRODUCT_QUALITY["RB-001"] = 4.6

        personas = {
            # name: (bundle slug or None, bundle prob, [(sku, prob), ...])
            "arrival": ("international-arrival", 0.45, [("RB-001", .7), ("RB-002", .6), ("RB-003", .5), ("TP-001", .85),
                                                       ("TP-002", .6), ("TP-003", .7), ("KT-004", .5), ("RB-004", .3),
                                                       ("ST-009", .35), ("KT-008", .2),
                                                       ("TP-007", .2), ("ST-011", .2)]),
            "sleep": ("sleep-wash", 0.35, [("RB-001", .8), ("RB-002", .7), ("RB-006", .5), ("RB-003", .5), ("RB-005", .3),
                                     ("RB-007", .25), ("RB-008", .2), ("RB-009", .3), ("RB-010", .2)]),
            "kitchen": ("kitchen-starter", 0.35, [("KT-001", .7), ("KT-002", .6), ("KT-003", .6), ("KT-004", .5),
                                                 ("KT-005", .4), ("KT-006", .35), ("KT-007", .3), ("WR-006", .15),
                                                 ("KT-009", .25), ("KT-010", .2), ("KT-011", .25), ("KT-012", .1), ("KT-013", .2)]),
            "study": ("study-kit", 0.3, [("ST-001", .6), ("ST-002", .6), ("ST-003", .35), ("ST-004", .4), ("ST-005", .4),
                                        ("ST-006", .5), ("TP-005", .25), ("TP-004", .2),
                                        ("ST-007", .3), ("ST-008", .3), ("ST-009", .25),
                                        ("ST-010", .3), ("ST-011", .2), ("ST-012", .3), ("ST-013", .15)]),
            "winter": ("winter-ready", 0.3, [("WR-001", .6), ("WR-002", .55), ("WR-003", .5), ("WR-004", .45), ("WR-005", .3),
                                         ("WR-007", .35), ("WR-008", .3), ("WR-009", .25), ("WR-010", .2),
                                         ("WR-011", .2), ("WR-012", .25)]),
            "tech": (None, 0, [("TP-006", .6), ("TP-005", .45), ("TP-004", .4), ("TP-002", .4), ("TP-001", .3), ("ST-005", .2),
                                ("TP-007", .35), ("TP-008", .3), ("TP-009", .2), ("TP-010", .25)]),
        }

        def persona_weights(d, international_share):
            winter = 2.4 if d.month in (11, 12, 1) else (1.6 if d.month in (10, 2) else 0.6)
            return {
                "arrival": 3.0 * international_share,
                "sleep": 1.2,
                "kitchen": 1.6,
                "study": 1.5 if d.month in (9, 10, 1) else 0.8,
                "winter": winter,
                "tech": 1.0,
            }

        # synthetic customers (never sign in; emails on a reserved test domain)
        users = []
        n_users = 900
        for i in range(n_users):
            fn, ln = rng.choice(FIRST), rng.choice(LAST)
            users.append(User(email=f"student{i:04d}@test.astonbundle.example", full_name=f"{fn} {ln}",
                              halls=rng.choice(["Canal View Halls", "Lakeside Court", "Gosta Green House", "Woodcock Street Studios"]),
                              room=f"{rng.choice('ABCD')}-{rng.randint(101, 420)}", email_verified=True,
                              is_test_data=True, password="!"))
        User.objects.bulk_create(users, batch_size=500)
        users = list(User.objects.filter(is_test_data=True))

        orders, line_specs, order_meta = [], [], []
        week_starts = list(daterange_weeks(start, today))
        for ws in week_starts:
            years_in = (ws - start).days / 365.0
            growth = 1.0 + 0.3 * years_in
            mid = ws + timedelta(days=3)
            n = 6 + 115 * intake_intensity(mid) * growth
            n = max(0, int(rng.gauss(n, math.sqrt(n) + 1)))
            intl = 0.35 + 0.5 * intake_intensity(mid)
            weights = persona_weights(mid, intl)
            names, w = zip(*weights.items())
            for _ in range(n):
                created = datetime.combine(ws + timedelta(days=rng.randint(0, 6)), time(rng.randint(7, 23), rng.randint(0, 59)))
                created = timezone.make_aware(created)
                if created > now:
                    continue
                persona = rng.choices(names, weights=w)[0]
                bslug, bprob, items = personas[persona]
                chosen = []  # (product, qty, bundle)
                if bslug and rng.random() < bprob:
                    chosen.append(("bundle", bundles[bslug]))
                    extras = [s for s, p in items if rng.random() < p * 0.25]
                else:
                    extras = [s for s, p in items if rng.random() < p]
                if rng.random() < 0.25:  # cross-persona add-on
                    other = personas[rng.choice(names)][2]
                    extras.append(rng.choice(other)[0])
                if not chosen and not extras:
                    extras = [rng.choice(items)[0]]
                for sku in dict.fromkeys(extras):
                    chosen.append(("p", products[sku], 1 if rng.random() < 0.9 else 2))
                user = rng.choice(users)
                age = (now - created).days
                if age > 10:
                    status = OrderStatus.CANCELLED if rng.random() < 0.03 else OrderStatus.DELIVERED
                elif age > 5:
                    status = rng.choice([OrderStatus.DELIVERED, OrderStatus.DELIVERED, OrderStatus.DISPATCHED])
                elif age > 2:
                    status = rng.choice([OrderStatus.PROCESSING, OrderStatus.DISPATCHED])
                else:
                    status = rng.choice([OrderStatus.PLACED, OrderStatus.PROCESSING])
                deliv = (created + timedelta(days=rng.randint(2, 6))).date()
                orders.append(Order(number=f"TMP-{len(orders)}", user=user, status=status, recipient_name=user.full_name,
                                    halls=user.halls, room=user.room, delivery_date=deliv,
                                    delivery_slot=rng.choice(["09-13", "13-17", "17-20"]), created_at=created,
                                    payment_reference="TEST-HIST", is_test_data=True))
                line_specs.append(chosen)

        Order.objects.bulk_create(orders, batch_size=500)
        orders = list(Order.objects.filter(is_test_data=True).order_by("pk"))
        for o in orders:
            o.number = f"AB-{timezone.localtime(o.created_at):%y%m%d}-{o.pk:04d}"
        lines, events, totals = [], [], {}
        for o, chosen in zip(orders, line_specs):
            items_total = subtotal = Decimal("0")
            for c in chosen:
                if c[0] == "bundle":
                    b = c[1]
                    comps = [(i.product, i.quantity) for i in b.items.all()]
                    for p, q, unit in allocate_bundle_price(b.price, comps):
                        lines.append(OrderLine(order=o, product=p, bundle=b, bundle_name=b.name, name=p.name, icon=p.icon,
                                               tone=p.tone, list_price=p.price, unit_price=unit, quantity=q, returnable=p.returnable))
                        items_total += p.price * q
                    subtotal += b.price
                else:
                    _, p, q = c
                    lines.append(OrderLine(order=o, product=p, name=p.name, icon=p.icon, tone=p.tone, list_price=p.price,
                                           unit_price=p.price, quantity=q, returnable=p.returnable))
                    items_total += p.price * q
                    subtotal += p.price * q
            fee = Decimal("0") if subtotal >= 40 else Decimal("3.99")
            o.items_total, o.bundle_saving, o.delivery_fee, o.total = items_total, items_total - subtotal, fee, subtotal + fee
            # events
            t = o.created_at
            events.append(OrderEvent(order=o, status=OrderStatus.PLACED, created_at=t, note="Test payment accepted (simulation)"))
            path = {
                OrderStatus.PLACED: [],
                OrderStatus.PROCESSING: [OrderStatus.PROCESSING],
                OrderStatus.DISPATCHED: [OrderStatus.PROCESSING, OrderStatus.DISPATCHED],
                OrderStatus.DELIVERED: [OrderStatus.PROCESSING, OrderStatus.DISPATCHED, OrderStatus.DELIVERED],
                OrderStatus.CANCELLED: [OrderStatus.CANCELLED],
            }[o.status]
            for st in path:
                t = t + timedelta(hours=self.rng.randint(8, 30))
                events.append(OrderEvent(order=o, status=st, created_at=min(t, timezone.now())))
            if o.status in (OrderStatus.DISPATCHED, OrderStatus.DELIVERED):
                o.shipment_number = f"SHP-{o.pk:05d}"
        Order.objects.bulk_update(orders, ["number", "items_total", "bundle_saving", "delivery_fee", "total", "shipment_number"], batch_size=500)
        OrderLine.objects.bulk_create(lines, batch_size=1000)
        OrderEvent.objects.bulk_create(events, batch_size=1000)

        # sign-up dates: shortly before each user's first order
        first_order = {}
        for o in orders:
            first_order.setdefault(o.user_id, o.created_at)
        for u in users:
            fo = first_order.get(u.pk, timezone.now() - timedelta(days=self.rng.randint(5, 400)))
            u.date_joined = fo - timedelta(days=self.rng.randint(0, 20), hours=self.rng.randint(0, 20))
        User.objects.bulk_update(users, ["date_joined"], batch_size=500)

        self._reviews_and_returns(orders)
        # popularity = units sold in the last 90 days
        cutoff = timezone.now() - timedelta(days=90)
        for p in Product.objects.all():
            p.popularity = sum(OrderLine.objects.filter(product=p, order__created_at__gte=cutoff)
                               .exclude(order__status=OrderStatus.CANCELLED).values_list("quantity", flat=True))
            p.save(update_fields=["popularity"])
        self.stdout.write(f"History: {len(orders)} synthetic orders, {len(lines)} lines, {len(users)} synthetic customers.")

    def _reviews_and_returns(self, orders):
        rng = self.rng
        seen = set()
        reviews = []
        returns_made = 0
        now = timezone.now()
        delivered = [o for o in orders if o.status == OrderStatus.DELIVERED]
        lines_by_order = {}
        for line in OrderLine.objects.filter(order__in=delivered).select_related("product"):
            lines_by_order.setdefault(line.order_id, []).append(line)
        for o in delivered:
            for line in lines_by_order.get(o.pk, []):
                if line.product is None:
                    continue
                key = (line.product_id, o.user_id)
                if key not in seen and rng.random() < 0.16:
                    seen.add(key)
                    mean = PRODUCT_QUALITY.get(line.product.sku, 4.3)
                    rating = max(1, min(5, round(rng.gauss(mean, 0.8))))
                    title, body = rng.choice(REVIEW_TEXT[rating])
                    reviews.append(Review(product=line.product, user=o.user, rating=rating, title=title, body=body,
                                          course=rng.choice(COURSES), created_at=min(now - timedelta(hours=1), o.created_at + timedelta(days=rng.randint(4, 20)))))
                # a few returns
                if line.returnable and rng.random() < 0.012:
                    age = (now - o.created_at).days
                    status = ReturnStatus.REQUESTED if age < 12 else (ReturnStatus.REJECTED if rng.random() < 0.15 else ReturnStatus.APPROVED)
                    r = ReturnRequest(order=o, user=o.user, reason=rng.choice(["damaged", "not_needed", "fit", "not_described"]),
                                      comments="", status=status, created_at=min(now - timedelta(hours=3), o.created_at + timedelta(days=rng.randint(4, 12))))
                    r.save()
                    ReturnItem.objects.create(request=r, line=line, quantity=1)
                    if status != ReturnStatus.REQUESTED:
                        r.decided_at = r.created_at + timedelta(days=1)
                        r.decision_note = "" if status == ReturnStatus.APPROVED else "Item shows signs of use."
                        r.save(update_fields=["decided_at", "decision_note"])
                    if status == ReturnStatus.APPROVED:
                        line.returned_quantity = 1
                        line.save(update_fields=["returned_quantity"])
                    returns_made += 1
        Review.objects.bulk_create(reviews, batch_size=500, ignore_conflicts=True)
        for p in Product.objects.all():
            refresh_product_rating(p)
        self.stdout.write(f"Reviews: {len(reviews)}, returns: {returns_made}.")

    # ------------------------------------------------------------------
    def _demo_customer_orders(self):
        """Orders for the demo student that show every status in the UI."""
        u = User.objects.get(email="demo.student@aston.ac.uk")
        if u.orders.exists():
            return
        P = {p.sku: p for p in Product.objects.all()}
        B = {b.slug: b for b in Bundle.objects.prefetch_related("items__product")}
        now = timezone.now()

        def make(days_ago, status, items, bundle=None):
            created = now - timedelta(days=days_ago, hours=3)
            o = Order(user=u, status=status, recipient_name=u.full_name, halls=u.halls, room=u.room,
                      delivery_date=(created + timedelta(days=2)).date(), delivery_slot="09-13", created_at=created,
                      payment_reference="TEST-DEMO", is_test_data=True)
            o.save()
            o.number = f"AB-{timezone.localtime(created):%y%m%d}-{o.pk:04d}"
            items_total = subtotal = Decimal("0")
            if bundle:
                b = B[bundle]
                comps = [(i.product, i.quantity) for i in b.items.all()]
                for p, q, unit in allocate_bundle_price(b.price, comps):
                    OrderLine.objects.create(order=o, product=p, bundle=b, bundle_name=b.name, name=p.name, icon=p.icon,
                                             tone=p.tone, list_price=p.price, unit_price=unit, quantity=q, returnable=p.returnable)
                    items_total += p.price * q
                subtotal += b.price
            for sku, q in items:
                p = P[sku]
                OrderLine.objects.create(order=o, product=p, name=p.name, icon=p.icon, tone=p.tone, list_price=p.price,
                                         unit_price=p.price, quantity=q, returnable=p.returnable)
                items_total += p.price * q
                subtotal += p.price * q
            fee = Decimal("0") if subtotal >= 40 else Decimal("3.99")
            o.items_total, o.bundle_saving, o.delivery_fee, o.total = items_total, items_total - subtotal, fee, subtotal + fee
            t = created
            OrderEvent.objects.create(order=o, status=OrderStatus.PLACED, created_at=t, note="Test payment accepted (simulation)")
            path = {OrderStatus.PLACED: [], OrderStatus.PROCESSING: [OrderStatus.PROCESSING],
                    OrderStatus.DISPATCHED: [OrderStatus.PROCESSING, OrderStatus.DISPATCHED],
                    OrderStatus.DELIVERED: [OrderStatus.PROCESSING, OrderStatus.DISPATCHED, OrderStatus.DELIVERED],
                    OrderStatus.CANCELLED: [OrderStatus.CANCELLED]}[status]
            for st in path:
                t += timedelta(hours=20)
                OrderEvent.objects.create(order=o, status=st, created_at=t,
                                          note="Signed for by halls reception" if st == OrderStatus.DELIVERED else "")
            if status in (OrderStatus.DISPATCHED, OrderStatus.DELIVERED):
                o.shipment_number = f"SHP-{o.pk:05d}"
            o.save()
            return o

        make(1, OrderStatus.PLACED, [("ST-001", 1)])
        make(7, OrderStatus.PROCESSING, [("WR-002", 1), ("KT-004", 1)], bundle="international-arrival")
        make(12, OrderStatus.DISPATCHED, [("WR-003", 1)])
        kitchen = make(25, OrderStatus.DELIVERED, [], bundle="kitchen-starter")
        backpack = make(29, OrderStatus.DELIVERED, [("ST-004", 1)])
        make(37, OrderStatus.CANCELLED, [("TP-001", 1)])
        # open return on the plate set of the kitchen order
        line = kitchen.lines.get(product__sku="KT-003")
        r = ReturnRequest.objects.create(order=kitchen, user=u, reason="damaged", comments="One bowl arrived chipped.",
                                         created_at=now - timedelta(days=6))
        ReturnItem.objects.create(request=r, line=line, quantity=1)
        r2 = ReturnRequest.objects.create(order=backpack, user=u, reason="not_needed", created_at=now - timedelta(days=3))
        ReturnItem.objects.create(request=r2, line=backpack.lines.first(), quantity=1)

    def _enquiries(self):
        rng = self.rng
        now = timezone.now()
        samples = [
            ("order", "Can I change my delivery date? My flight moved to 11 January."),
            ("product", "Does the kettle have a UK plug or do I need an adapter?"),
            ("return", "One bowl in my kitchen set was chipped. I opened a return already."),
            ("account", "I did not receive my verification code. Can you help?"),
            ("other", "Do you deliver to Lakeside Court on Sundays?"),
            ("order", "My order says dispatched. Who signs for it at reception?"),
            ("product", "Is the duvet warm enough for January?"),
            ("other", "Will you sell bikes or bike locks?"),
        ]
        for i, (topic, msg) in enumerate(samples):
            fn, ln = rng.choice(FIRST), rng.choice(LAST)
            Enquiry.objects.create(name=f"{fn} {ln}", email=f"student{i + 2000}@test.astonbundle.example", topic=topic,
                                   message=msg, created_at=now - timedelta(hours=5 + i * 9),
                                   status=Enquiry.Status.UNREAD if i < 6 else Enquiry.Status.RESOLVED)

    def _stock_log(self):
        owner = User.objects.get(email="owner@astonbundle.example")
        stock = User.objects.get(email="stock@astonbundle.example")
        P = {p.sku: p for p in Product.objects.all()}
        now = timezone.now()
        log = [
            (P["WR-001"], -2, 0, Reason.DAMAGED, stock, 0),
            (P["TP-003"], 200, 212, Reason.DELIVERY, owner, 1),
            (P["ST-004"], 1, 18, Reason.RETURN_RESELLABLE, stock, 1),
            (P["RB-001"], -4, 3, Reason.CORRECTION, owner, 2),
        ]
        for p, ch, nq, reason, by, days in log:
            m = StockMovement.objects.create(product=p, change=ch, new_quantity=nq, reason=reason, by=by)
            StockMovement.objects.filter(pk=m.pk).update(created_at=now - timedelta(days=days, hours=3))

    def _final_stock(self):
        # Reset current stock to the designed values (history does not consume today's stock).
        for (sku, _cat, _n, _p, stock, *_rest) in PRODUCTS:
            Product.objects.filter(sku=sku).update(stock=stock)
