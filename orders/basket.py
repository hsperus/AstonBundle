"""Session-based basket. Works for guests and signed-in students; the session is
stored in the database, so it persists between visits."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

from catalog.models import Bundle, Product

SESSION_KEY = "basket"
MAX_LINE_QTY = 10


@dataclass
class BasketLine:
    key: str
    kind: str  # "p" or "b"
    obj: object
    quantity: int
    warning: str = ""
    components: list = field(default_factory=list)  # for bundles: [(product, qty_per_bundle)]
    price: Decimal = None  # unit price (bundle price, or customised bundle price)
    customised: bool = False

    def __post_init__(self):
        if self.price is None:
            self.price = self.obj.price

    @property
    def unit_price(self):
        return self.price

    @property
    def line_total(self):
        return self.price * self.quantity

    @property
    def name(self):
        if self.kind == "b" and self.customised:
            return f"{self.obj.name} (customised)"
        return self.obj.name

    @property
    def full_price(self):
        """Price if every item were bought separately."""
        if self.kind == "b":
            return sum((p.price * q for p, q in self.components), Decimal("0")) * self.quantity
        return self.line_total

    @property
    def saving(self):
        return self.full_price - self.line_total

    @property
    def max_quantity(self):
        if self.kind == "b":
            if not self.components:
                return 0
            avail = min(p.stock // q if p.is_active else 0 for p, q in self.components)
            return max(0, min(MAX_LINE_QTY, avail))
        return self.obj.order_limit

    @property
    def is_bundle(self):
        return self.kind == "b"


class Basket:
    def __init__(self, request):
        self.session = request.session
        raw = self.session.get(SESSION_KEY) or {}
        self.data = {k: int(v) for k, v in raw.items() if isinstance(v, (int, str)) and str(v).isdigit()}

    # ---- persistence -------------------------------------------------
    def save(self):
        self.session[SESSION_KEY] = self.data
        self.session.modified = True

    def clear(self):
        self.data = {}
        self.save()

    # ---- mutations -----------------------------------------------------
    def add(self, kind, obj_id, quantity=1, only=None):
        key = f"{kind}:{obj_id}"
        if kind == "b" and only:
            key += ":" + "-".join(str(i) for i in sorted(set(only)))
        self.data[key] = min(MAX_LINE_QTY, self.data.get(key, 0) + max(1, int(quantity)))
        self.save()

    def set(self, key, quantity):
        if key not in self.data:
            return
        quantity = int(quantity)
        if quantity <= 0:
            self.data.pop(key)
        else:
            self.data[key] = min(MAX_LINE_QTY, quantity)
        self.save()

    def remove(self, key):
        self.data.pop(key, None)
        self.save()

    # ---- reading -------------------------------------------------------
    @property
    def count(self):
        return sum(self.data.values())

    def lines(self, adjust=True):
        """Build basket lines from the database. When `adjust` is True, quantities
        larger than the stock allows are reduced and a warning is attached."""
        pids = [int(k.split(":")[1]) for k in self.data if k.startswith("p:") and k.split(":")[1].isdigit()]
        bids = [int(k.split(":")[1]) for k in self.data if k.startswith("b:") and k.split(":")[1].isdigit()]
        products = {p.pk: p for p in Product.objects.filter(pk__in=pids, is_active=True)}
        bundles = {
            b.pk: b for b in Bundle.objects.filter(pk__in=bids, is_active=True).prefetch_related("items__product")
        }
        result, changed = [], False
        for key, qty in list(self.data.items()):
            parts = key.split(":")
            kind, sid = parts[0], parts[1] if len(parts) > 1 else ""
            obj = (products if kind == "p" else bundles).get(int(sid)) if sid.isdigit() and kind in ("p", "b") else None
            if obj is None:
                self.data.pop(key)
                changed = True
                continue
            line = None
            if kind == "b":
                comps = [(i.product, i.quantity) for i in obj.items.all()]
                customised = False
                if len(parts) == 3:
                    try:
                        keep = {int(x) for x in parts[2].split("-") if x}
                    except ValueError:
                        keep = set()
                    chosen = [(p, q) for p, q in comps if p.pk in keep]
                    if len(chosen) < 2:
                        self.data.pop(key)
                        changed = True
                        continue
                    customised = len(chosen) < len(comps)
                    comps = chosen
                price = custom_bundle_price(obj, comps) if customised else obj.price
                line = BasketLine(key, kind, obj, qty, components=comps, price=price, customised=customised)
            else:
                line = BasketLine(key, kind, obj, qty)
            limit = line.max_quantity
            if adjust and qty > limit:
                if limit == 0:
                    line.warning = "This item is now out of stock. Remove it to continue."
                else:
                    line.warning = f"Only {limit} available — quantity adjusted."
                    line.quantity = limit
                    self.data[key] = limit
                    changed = True
            result.append(line)
        if changed:
            self.save()
        return result

    @staticmethod
    def totals(lines):
        items_total = sum((l.full_price for l in lines), Decimal("0"))
        subtotal = sum((l.line_total for l in lines), Decimal("0"))
        saving = items_total - subtotal
        if not lines or subtotal >= settings.FREE_DELIVERY_THRESHOLD:
            delivery = Decimal("0")
        else:
            delivery = Decimal(settings.DELIVERY_FEE)
        return {
            "items_total": items_total,
            "subtotal": subtotal,
            "saving": saving,
            "delivery": delivery,
            "total": subtotal + delivery,
            "free_delivery_gap": max(Decimal("0"), Decimal(settings.FREE_DELIVERY_THRESHOLD) - subtotal),
        }

    @staticmethod
    def requirements(lines):
        """{product_id: units needed} across single items and bundle components."""
        req = {}
        for line in lines:
            if line.kind == "p":
                req[line.obj.pk] = req.get(line.obj.pk, 0) + line.quantity
            else:
                for product, per in line.components:
                    req[product.pk] = req.get(product.pk, 0) + per * line.quantity
        return req


def allocate_bundle_price(bundle_price, components):
    """Split a bundle price across its products in proportion to their list prices,
    so each order line has a fair 'price paid' (used for partial refunds).
    Returns [(product, qty, unit_price)]; rounding difference goes on the first line."""
    full = sum((p.price * q for p, q in components), Decimal("0"))
    if full == 0:
        return [(p, q, Decimal("0")) for p, q in components]
    out, allocated = [], Decimal("0")
    for p, q in components:
        unit = (p.price * bundle_price / full).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out.append([p, q, unit])
        allocated += unit * q
    diff = bundle_price - allocated
    if diff and out:
        p, q, unit = out[0]
        out[0][2] = unit + (diff / q).quantize(Decimal("0.01"))
    return [tuple(x) for x in out]


def custom_bundle_price(bundle, components):
    """A customised bundle keeps the same percentage discount as the full bundle."""
    full = sum((i.product.price * i.quantity for i in bundle.items.all()), Decimal("0"))
    chosen = sum((p.price * q for p, q in components), Decimal("0"))
    if full == 0:
        return chosen
    return (chosen * bundle.price / full).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
