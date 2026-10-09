from decimal import Decimal

from django import template
from django.conf import settings
from django.utils.html import format_html

register = template.Library()

SYMBOLS = {"TRY": "₺", "INR": "₹", "CNY": "¥", "NGN": "₦", "PKR": "₨"}


@register.filter
def money(value):
    """£1,234.56 (always two decimals, GBP)."""
    try:
        v = Decimal(value)
    except Exception:
        return value
    sign = "−" if v < 0 else ""
    return f"{sign}£{abs(v):,.2f}"


@register.simple_tag
def fx(value, codes="TRY,INR,CNY"):
    """Home-currency estimate shown next to GBP prices (indicative only)."""
    out = []
    for code in codes.split(","):
        rate = settings.FX_RATES.get(code)
        if rate:
            amount = Decimal(value) * Decimal(str(rate))
            amount = int(round(amount, -1)) if amount >= 100 else int(round(amount))
            out.append(f"≈ {SYMBOLS.get(code, code)}{amount:,}")
    return " · ".join(out)


@register.simple_tag
def fx_date():
    return settings.FX_RATES_AS_OF


@register.inclusion_tag("partials/stock_badge.html")
def stock_badge(product, size=""):
    return {"p": product, "size": size}


@register.inclusion_tag("partials/stars.html")
def stars(rating, size=""):
    try:
        r = float(rating)
    except (TypeError, ValueError):
        r = 0
    full = round(r)
    return {"icons": ["starf" if i <= full else "star" for i in range(1, 6)], "rating": r, "size": size}


@register.inclusion_tag("partials/chip.html")
def order_chip(order, big=False):
    cls, icon, label = order.chip
    return {"cls": cls, "icon": icon, "label": label, "big": big}


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Current query string with some parameters replaced (None/'' removes)."""
    q = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            q.pop(k, None)
        else:
            q[k] = v
    s = q.urlencode()
    return f"?{s}" if s else "?"


@register.simple_tag
def qs_without(request, key, value=None):
    q = request.GET.copy()
    if value is None:
        q.pop(key, None)
    else:
        vals = [v for v in q.getlist(key) if v != str(value)]
        q.setlist(key, vals)
    q.pop("page", None)
    s = q.urlencode()
    return f"?{s}" if s else "?"


@register.filter
def pct(value, total):
    try:
        return round(100 * float(value) / float(total)) if float(total) else 0
    except (TypeError, ValueError):
        return 0


@register.filter
def icon(name, size=""):
    return format_html('<span class="i i-{}{}" aria-hidden="true"></span>', name, f" {size}" if size else "")


@register.filter
def get(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def highlight(text, terms):
    """Wrap search terms in <mark> (input is escaped first)."""
    import re

    from django.utils.html import escape
    from django.utils.safestring import mark_safe

    out = escape(text)
    for t in sorted(terms or [], key=len, reverse=True):
        if len(t) >= 2:
            out = re.sub(f"({re.escape(escape(t))})", r"<mark>\1</mark>", out, flags=re.I)
    return mark_safe(out)


@register.filter
def elided(paginator, number):
    return paginator.get_elided_page_range(number, on_each_side=1, on_ends=1)
