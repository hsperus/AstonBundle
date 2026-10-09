import csv
import secrets
import threading
from datetime import datetime, time, timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.db import close_old_connections, transaction
from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import PERMISSIONS, AuditLog, Role, StaffInvite, User
from ai.models import ModelRun, ProductAssociation, ProductForecast
from catalog.models import Bundle, BundleItem, Category, Product
from inventory.models import PurchaseOrder, Reason, StockMovement
from inventory.services import StockError, adjust_stock
from orders.models import CHIPS, Order, OrderStatus, ReturnRequest, ReturnStatus
from orders.services import OrderError, change_status, decide_return
from support.models import TOPICS, Enquiry

from .charts import forecast_chart, line_chart
from .forms import AcceptInviteForm, AdjustForm, InviteForm, ProductForm, StaffSignInForm

AREA_NAMES = {"dashboard": "the Dashboard", "products": "Products", "inventory": "Inventory", "ai": "AI insights",
              "orders": "Orders", "customers": "Customers", "returns": "Returns", "enquiries": "Enquiries",
              "access": "Staff & roles"}


def staff_area(area):
    """Server-side role check for every staff view (not just hiding menu items)."""
    def deco(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            u = request.user
            if not u.is_authenticated or not u.is_staff:
                return redirect(f"{reverse('staff:signin')}?next={request.path}")
            if not u.can(area):
                return render(request, "staff/403.html", {"area": AREA_NAMES.get(area, area)}, status=403)
            u.last_seen = timezone.now()
            User.objects.filter(pk=u.pk).update(last_seen=u.last_seen)
            return view(request, *args, **kwargs)
        return wrapped
    return deco


def _email(to, subject, body, kind="general"):
    EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [to], headers={"X-AB-Kind": kind}).send()


def _csv(filename, header, rows):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    w = csv.writer(resp)
    w.writerow(header)
    for r in rows:
        w.writerow([str(c).lstrip("=+-@") if isinstance(c, str) else c for c in r])  # avoid CSV formula injection
    return resp


# ------------------------------------------------------------------ auth
def signin(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("staff:dashboard")
    form = StaffSignInForm(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        user = authenticate(request, email=form.cleaned_data["email"], password=form.cleaned_data["password"])
        if getattr(request, "auth_locked", False):
            error = f"This account is locked for {settings.LOGIN_LOCKOUT_MINUTES} minutes after 5 failed attempts."
        elif user is None or not user.is_staff:
            error = "Email or password is not right."
        else:
            login(request, user)
            request.session.set_expiry(60 * 60 * 8)  # staff sessions end after 8 hours
            nxt = request.GET.get("next", "")
            return redirect(nxt if nxt.startswith("/staff/") else reverse("staff:dashboard"))
    return render(request, "staff/signin.html", {"form": form, "error": error})


@require_POST
def signout(request):
    logout(request)
    return redirect("staff:signin")


def accept_invite(request, token):
    invite = StaffInvite.objects.filter(token=token).first()
    if invite is None or not invite.is_valid:
        return render(request, "staff/invite_invalid.html", status=410)
    form = AcceptInviteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = User.objects.create_staff(invite.email, form.cleaned_data["password1"], role=invite.role,
                                             full_name=form.cleaned_data["full_name"])
            invite.accepted_at = timezone.now()
            invite.save(update_fields=["accepted_at"])
        login(request, user, backend="accounts.backends.EmailBackend")
        messages.success(request, "Welcome to the AstonBundle team.")
        return redirect("staff:dashboard")
    return render(request, "staff/invite_accept.html", {"form": form, "invite": invite})


@staff_area("dashboard")
def password(request):
    from django.contrib.auth import update_session_auth_hash
    from django.contrib.auth.forms import PasswordChangeForm

    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, form.user)
        messages.success(request, "Your password has been changed.")
        return redirect("staff:dashboard")
    return render(request, "staff/password.html", {"form": form, "nav": ""})


# ------------------------------------------------------------------ dashboard
def _week_start(d):
    return d - timedelta(days=d.weekday())


def orders_series(rng):
    now = timezone.localtime()
    today = now.date()
    qs = Order.objects.exclude(status=OrderStatus.CANCELLED)
    if rng == "30d":
        start = today - timedelta(days=29)
        rows = dict(qs.filter(created_at__date__gte=start).annotate(d=TruncDate("created_at")).values("d")
                    .annotate(n=Count("id")).values_list("d", "n"))
        return [(f"{(start + timedelta(days=i)).day} {(start + timedelta(days=i)).strftime('%b')}", rows.get(start + timedelta(days=i), 0)) for i in range(30)]
    if rng == "year":
        start = today.replace(day=1) - timedelta(days=335)
        start = start.replace(day=1)
        rows = {d.date() if hasattr(d, "date") else d: n for d, n in
                qs.filter(created_at__date__gte=start).annotate(m=TruncMonth("created_at")).values("m")
                .annotate(n=Count("id")).values_list("m", "n")}
        out, d = [], start
        while d <= today:
            out.append((f"{d:%b %y}", rows.get(d, 0)))
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        return out
    start = _week_start(today) - timedelta(weeks=11)
    rows = {d.date() if hasattr(d, "date") else d: n for d, n in
            qs.filter(created_at__date__gte=start).annotate(w=TruncWeek("created_at")).values("w")
            .annotate(n=Count("id")).values_list("w", "n")}
    return [(f"{(start + timedelta(weeks=i)).day} {(start + timedelta(weeks=i)).strftime('%b')}", rows.get(start + timedelta(weeks=i), 0)) for i in range(12)]


def _pct(a, b):
    if not b:
        return None
    return round(100 * (a - b) / b)


@staff_area("dashboard")
def dashboard(request):
    now = timezone.localtime()
    today = now.date()
    day_start = timezone.make_aware(datetime.combine(today, time.min))
    live = Order.objects.exclude(status=OrderStatus.CANCELLED)
    orders_today = live.filter(created_at__gte=day_start, created_at__lte=now).count()
    lw_start = day_start - timedelta(days=7)
    orders_lw = live.filter(created_at__gte=lw_start, created_at__lte=now - timedelta(days=7)).count()
    wk = timezone.make_aware(datetime.combine(_week_start(today), time.min))
    revenue_wk = live.filter(created_at__gte=wk).aggregate(s=Sum("total"))["s"] or 0
    revenue_lw = live.filter(created_at__gte=wk - timedelta(days=7), created_at__lte=now - timedelta(days=7)).aggregate(s=Sum("total"))["s"] or 0
    low = Product.objects.active().low_stock()
    out = Product.objects.active().out_of_stock()
    open_returns = ReturnRequest.objects.filter(status=ReturnStatus.REQUESTED)
    old_returns = open_returns.filter(created_at__lte=now - timedelta(days=2)).count()
    unread = Enquiry.objects.filter(status=Enquiry.Status.UNREAD)
    oldest_unread = unread.aggregate(m=Min("created_at"))["m"]
    rng = request.GET.get("range", "12w")
    if rng not in ("30d", "12w", "year"):
        rng = "12w"
    series = orders_series(rng)
    run = ModelRun.latest(ModelRun.Kind.FORECAST)
    forecasts = []
    if run:
        forecasts = sorted(run.forecasts.select_related("product"), key=lambda f: -f.suggested_reorder)[:5]
    return render(request, "staff/dashboard.html", {
        "nav": "dash", "today": today,
        "orders_today": orders_today, "orders_change": _pct(orders_today, orders_lw),
        "revenue_wk": revenue_wk, "revenue_change": _pct(float(revenue_wk), float(revenue_lw)),
        "low_count": low.count(), "out": list(out), "low_rows": list(Product.objects.active().filter(stock__lte=models_F_threshold()).order_by("stock")[:6]),
        "open_returns": open_returns.count(), "old_returns": old_returns,
        "unread": unread.count(), "oldest_unread": oldest_unread,
        "chart": line_chart(series, label="Orders over time"), "series": series, "range": rng,
        "run": run, "forecasts": forecasts,
        "signups": User.objects.filter(role=Role.CUSTOMER, email_verified=True).count(),
    })


def models_F_threshold():
    from django.db.models import F

    return F("low_stock_threshold")


@staff_area("dashboard")
def search(request):
    q = (request.GET.get("q") or "").strip()[:60]
    results = {}
    if q:
        u = request.user
        if u.can("orders"):
            results["orders"] = Order.objects.filter(Q(number__icontains=q) | Q(recipient_name__icontains=q))[:10]
        if u.can("products"):
            results["products"] = Product.objects.filter(Q(name__icontains=q) | Q(sku__icontains=q))[:10]
        if u.can("customers"):
            results["customers"] = User.objects.filter(role=Role.CUSTOMER, full_name__icontains=q)[:10]
    return render(request, "staff/search.html", {"q": q, "results": results, "nav": "dash"})


# ------------------------------------------------------------------ products
@staff_area("products")
def products(request):
    qs = Product.objects.select_related("category")
    q = (request.GET.get("q") or "").strip()[:60]
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    cat = request.GET.get("cat", "")
    if cat:
        qs = qs.filter(category__slug=cat)
    st = request.GET.get("st", "")
    if st == "ok":
        qs = qs.filter(stock__gt=models_F_threshold())
    elif st == "low":
        qs = qs.low_stock()
    elif st == "out":
        qs = qs.out_of_stock()
    elif st == "hidden":
        qs = qs.filter(is_active=False)
    if request.method == "POST":
        ids = [int(i) for i in request.POST.getlist("sel") if i.isdigit()]
        action = request.POST.get("bulk")
        chosen = Product.objects.filter(pk__in=ids)
        if not ids:
            messages.error(request, "Select at least one product.")
        elif action == "export":
            return _csv("products.csv", ["SKU", "Name", "Category", "Price", "Stock", "Threshold", "Visible"],
                        [(p.sku, p.name, p.category.name, p.price, p.stock, p.low_stock_threshold, p.is_active) for p in chosen.select_related("category")])
        elif action == "hide":
            n = chosen.update(is_active=False)
            messages.success(request, f"{n} product{'s' if n != 1 else ''} hidden from the shop.")
        elif action == "show":
            n = chosen.update(is_active=True)
            messages.success(request, f"{n} product{'s' if n != 1 else ''} visible in the shop.")
        elif action == "category":
            c = Category.objects.filter(slug=request.POST.get("to_cat")).first()
            if c:
                n = chosen.update(category=c)
                messages.success(request, f"Moved {n} product{'s' if n != 1 else ''} to {c.name}.")
            else:
                messages.error(request, "Choose a category to move to.")
        return redirect(request.get_full_path())
    page = Paginator(qs.order_by("name"), 15).get_page(request.GET.get("page"))
    return render(request, "staff/products.html", {"nav": "prod", "page": page, "q": q, "cat": cat, "st": st,
                                                   "categories": Category.objects.all(), "total": Product.objects.count()})


@staff_area("products")
def product_edit(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else None
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            p = form.save(commit=False)
            p.specs = form.cleaned_data["specs_text"]
            new_stock = form.cleaned_data["stock"]
            if product is None:
                p.stock = new_stock
                p.save()
                if new_stock:
                    StockMovement.objects.create(product=p, change=new_stock, new_quantity=new_stock, reason=Reason.DELIVERY,
                                                 note="Opening stock (new product)", by=request.user)
            else:
                old = Product.objects.get(pk=p.pk).stock
                p.stock = old
                p.save()
                if new_stock != old:
                    adjust_stock(p.pk, new_stock - old, Reason.CORRECTION, by=request.user, note="Edited in product form")
        messages.success(request, f"Saved {p.name}.")
        return redirect("staff:products")
    bundles = Bundle.objects.filter(items__product=product).distinct() if product else []
    return render(request, "staff/product_form.html", {"nav": "prod", "form": form, "product": product, "bundles": bundles})


@staff_area("products")
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    bundles = list(Bundle.objects.filter(items__product=product).distinct())
    error = ""
    if request.method == "POST":
        if bundles and request.POST.get("understand") != "1":
            error = "Tick the box to confirm the product will be removed from its bundles."
        else:
            name = product.name
            with transaction.atomic():
                BundleItem.objects.filter(product=product).delete()
                product.delete()
            messages.success(request, f"Deleted {name}. Past orders keep their records.")
            return redirect("staff:products")
    return render(request, "staff/product_delete.html", {"nav": "prod", "p": product, "bundles": bundles, "error": error})


# ------------------------------------------------------------------ inventory
@staff_area("inventory")
def inventory(request):
    products_qs = Product.objects.order_by("stock")
    q = (request.GET.get("q") or "").strip()[:60]
    if q:
        products_qs = products_qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    st = request.GET.get("st", "")
    if st == "low":
        products_qs = products_qs.low_stock()
    elif st == "out":
        products_qs = products_qs.out_of_stock()
    reserved = dict(
        Order.objects.filter(status__in=[OrderStatus.PLACED, OrderStatus.PROCESSING]).values("lines__product")
        .annotate(n=Sum("lines__quantity")).values_list("lines__product", "n")
    )
    selected = None
    sel = request.GET.get("p") or request.POST.get("product")
    if sel and str(sel).isdigit():
        selected = Product.objects.filter(pk=int(sel)).first()
    form = AdjustForm(request.POST or None, initial={"product": selected, "direction": "add"})
    if request.method == "POST" and request.POST.get("action") == "adjust":
        if form.is_valid():
            d = form.cleaned_data
            change = d["quantity"] if d["direction"] == "add" else -d["quantity"]
            try:
                p = adjust_stock(d["product"].pk, change, d["reason"], by=request.user, note=d["note"])
                messages.success(request, f"Stock updated: {p.name} now {p.stock}.")
                return redirect(f"{reverse('staff:inventory')}?p={p.pk}")
            except StockError as e:
                form.add_error("quantity", str(e))
        selected = form.cleaned_data.get("product") if hasattr(form, "cleaned_data") else selected
    if request.method == "POST" and request.POST.get("action") == "receive":
        po = get_object_or_404(PurchaseOrder, pk=request.POST.get("po"), status=PurchaseOrder.Status.OPEN)
        with transaction.atomic():
            adjust_stock(po.product_id, po.quantity, Reason.DELIVERY, by=request.user, note=f"Purchase order PO-{po.pk:04d}")
            po.status = PurchaseOrder.Status.RECEIVED
            po.received_at = timezone.now()
            po.save()
        messages.success(request, f"Received PO-{po.pk:04d}: {po.quantity} × {po.product.name} added to stock.")
        return redirect("staff:inventory")
    rows = []
    for p in products_qs:
        level = 0 if p.low_stock_threshold == 0 else min(100, round(100 * p.stock / max(1, p.low_stock_threshold * 3)))
        rows.append({"p": p, "reserved": reserved.get(p.pk, 0), "level": level})
    counts = {"ok": Product.objects.filter(stock__gt=models_F_threshold()).count(),
              "low": Product.objects.low_stock().count(), "out": Product.objects.out_of_stock().count()}
    history = StockMovement.objects.select_related("product", "by").exclude(reason=Reason.ORDER)
    if request.GET.get("export") == "log":
        return _csv("stock-log.csv", ["Date", "Product", "Change", "New qty", "Reason", "Note", "By"],
                    [(m.created_at.strftime("%Y-%m-%d %H:%M"), m.product.name, m.change, m.new_quantity,
                      m.get_reason_display(), m.note, m.by.full_name if m.by else "System") for m in history[:2000]])
    return render(request, "staff/inventory.html", {
        "nav": "inv", "rows": rows, "counts": counts, "form": form, "selected": selected, "q": q, "st": st,
        "history": history[:20], "pos": PurchaseOrder.objects.filter(status=PurchaseOrder.Status.OPEN).select_related("product"),
    })


@staff_area("inventory")
@require_POST
def create_po(request):
    product = get_object_or_404(Product, pk=request.POST.get("product"))
    try:
        qty = int(request.POST.get("quantity", "0"))
    except ValueError:
        qty = 0
    if not 1 <= qty <= 10000:
        messages.error(request, "Enter a quantity from 1 to 10,000.")
    else:
        po = PurchaseOrder.objects.create(product=product, quantity=qty, created_by=request.user,
                                          source=request.POST.get("source", "manual")[:40])
        messages.success(request, f"Purchase order PO-{po.pk:04d} created: {qty} × {product.name}. Mark it received in Inventory when it arrives.")
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/staff/") else reverse("staff:inventory"))


# ------------------------------------------------------------------ AI
_training_lock = threading.Lock()


def _retrain_background():
    from ai import forecast, recommender

    if not _training_lock.acquire(blocking=False):
        return
    try:
        close_old_connections()
        recommender.train()
        forecast.train()
    finally:
        close_old_connections()
        _training_lock.release()


@staff_area("ai")
def ai_insights(request):
    if request.method == "POST" and request.POST.get("action") == "retrain":
        if _training_lock.locked():
            messages.info(request, "Training is already running.")
        else:
            threading.Thread(target=_retrain_background, daemon=True).start()
            messages.success(request, "Retraining started. Refresh this page in about a minute.")
        return redirect("staff:ai")
    tab = request.GET.get("tab", "forecast")
    run = ModelRun.latest(ModelRun.Kind.FORECAST)
    rec_run = ModelRun.latest(ModelRun.Kind.RECOMMENDER)
    ctx = {"nav": "ai", "tab": tab, "run": run, "rec_run": rec_run, "training": _training_lock.locked()}
    if run:
        fcs = list(run.forecasts.select_related("product").order_by("-high"))
        if request.GET.get("export") == "csv":
            return _csv("forecast.csv", ["Product", "SKU", "Period start", "Period end", "Low (P10)", "Mid", "High (P90)",
                                         "Confidence", "Stock now", "Suggested reorder"],
                        [(f.product.name, f.product.sku, f.period_start, f.period_end, f.low, f.mid, f.high, f.confidence,
                          f.product.stock, f.suggested_reorder) for f in fcs])
        sel = request.GET.get("p")
        current = next((f for f in fcs if str(f.product_id) == sel), None) or (fcs[0] if fcs else None)
        if sel is None:
            current = next((f for f in fcs if f.product.sku == "TP-001"), current)
        ctx.update(forecasts=fcs, current=current, chart=forecast_chart(current.series) if current else "",
                   metrics=run.metrics)
    if rec_run:
        rules = (ProductAssociation.objects.filter(run=rec_run).select_related("source", "target").order_by("-score")[:12])
        ctx.update(rules=rules)
    return render(request, "staff/ai.html", ctx)


# ------------------------------------------------------------------ orders
@staff_area("orders")
def orders(request):
    qs = Order.objects.select_related("user")
    status = request.GET.get("status", "")
    if status in OrderStatus.values:
        qs = qs.filter(status=status)
    q = (request.GET.get("q") or "").strip()[:60]
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(recipient_name__icontains=q) | Q(user__email__iexact=q))
    dfrom, dto = request.GET.get("from", ""), request.GET.get("to", "")
    try:
        if dfrom:
            qs = qs.filter(created_at__date__gte=datetime.fromisoformat(dfrom).date())
        if dto:
            qs = qs.filter(created_at__date__lte=datetime.fromisoformat(dto).date())
    except ValueError:
        messages.error(request, "Use a real date in the date filter.")
    selected = None
    num = request.GET.get("o") or request.POST.get("order")
    if num:
        selected = Order.objects.filter(number=num).prefetch_related("lines", "events").select_related("user").first()
    if request.method == "POST" and selected:
        new = request.POST.get("status")
        try:
            change_status(selected, new, by=request.user, note=request.POST.get("note", "")[:200])
            selected.refresh_from_db()
            _email(selected.user.email, f"Order {selected.number}: {selected.get_status_display()}",
                   f"Hello {selected.user.first_name},\n\nYour order {selected.number} is now: {selected.get_status_display()}.\n\n"
                   f"Delivery: {selected.delivery_date.strftime('%A')} {selected.delivery_date.day} {selected.delivery_date.strftime('%B')}, {selected.slot_label}.", "order")
            messages.success(request, f"{selected.number} is now {selected.get_status_display().lower()}. The customer was emailed.")
        except (OrderError, ValueError) as e:
            messages.error(request, str(e))
        return redirect(f"{reverse('staff:orders')}?o={selected.number}")
    status_counts = dict(Order.objects.values("status").annotate(n=Count("id")).values_list("status", "n"))
    if request.GET.get("export") == "csv":
        return _csv("orders.csv", ["Order", "Placed", "Status", "Total", "Delivery date", "Slot"],
                    [(o.number, o.created_at.strftime("%Y-%m-%d %H:%M"), o.status, o.total, o.delivery_date, o.slot_label) for o in qs[:5000]])
    page = Paginator(qs.order_by("-created_at"), 15).get_page(request.GET.get("page"))
    return render(request, "staff/orders.html", {
        "nav": "ord", "page": page, "status": status, "q": q, "from": dfrom, "to": dto, "selected": selected,
        "statuses": [(s.value, s.label, status_counts.get(s.value, 0)) for s in OrderStatus], "total": Order.objects.count(),
    })


# ------------------------------------------------------------------ customers
REVEAL_KEY = "revealed_customers"


@staff_area("customers")
def customers(request):
    qs = User.objects.filter(role=Role.CUSTOMER).exclude(email__endswith="@deleted.invalid").annotate(n_orders=Count("orders"))
    if request.GET.get("status") == "suspended":
        qs = qs.filter(is_active=False)
    q = (request.GET.get("q") or "").strip()[:60]
    if q:
        qs = qs.filter(full_name__icontains=q)
    selected = None
    cid = request.GET.get("c") or request.POST.get("customer")
    if cid and str(cid).isdigit():
        selected = User.objects.filter(pk=int(cid), role=Role.CUSTOMER).first()
    revealed = request.session.get(REVEAL_KEY, {})
    if request.method == "POST" and selected and request.POST.get("action") == "reveal":
        AuditLog.objects.create(actor=request.user, action="reveal_customer", target=f"user:{selected.pk}")
        revealed[str(selected.pk)] = (timezone.now() + timedelta(minutes=5)).isoformat()
        request.session[REVEAL_KEY] = revealed
        messages.info(request, "Details shown for 5 minutes. This was logged.")
        return redirect(f"{reverse('staff:customers')}?c={selected.pk}")
    if request.method == "POST" and selected and request.POST.get("action") in ("suspend", "restore"):
        suspend = request.POST.get("action") == "suspend"
        selected.is_active = not suspend
        selected.save(update_fields=["is_active"])
        AuditLog.objects.create(actor=request.user, action="suspend_customer" if suspend else "restore_customer",
                                target=f"user:{selected.pk}")
        messages.success(request, "Account suspended: the student can no longer sign in." if suspend else "Account restored.")
        return redirect(f"{reverse('staff:customers')}?c={selected.pk}")
    if request.method == "POST" and selected and request.POST.get("action") in ("disable", "enable"):
        enable = request.POST.get("action") == "enable"
        selected.is_active = enable
        selected.save(update_fields=["is_active"])
        AuditLog.objects.create(actor=request.user, action="enable_customer" if enable else "disable_customer",
                                target=f"user:{selected.pk}")
        messages.success(request, f"Account {'enabled' if enable else 'disabled'}. The student {'can' if enable else 'can no longer'} sign in.")
        return redirect(f"{reverse('staff:customers')}?c={selected.pk}")
    is_revealed = False
    if selected and str(selected.pk) in revealed:
        is_revealed = datetime.fromisoformat(revealed[str(selected.pk)]) > timezone.now()
    page = Paginator(qs.order_by("-date_joined"), 15).get_page(request.GET.get("page"))
    log = AuditLog.objects.filter(target=f"user:{selected.pk}").select_related("actor")[:6] if selected else []
    return render(request, "staff/customers.html", {
        "nav": "cus", "page": page, "q": q, "selected": selected, "revealed": is_revealed,
        "sel_orders": selected.orders.prefetch_related("returns", "lines")[:6] if selected else [],
        "total": User.objects.filter(role=Role.CUSTOMER, email_verified=True).count(), "log": log,
    })


# ------------------------------------------------------------------ returns
@staff_area("returns")
def returns(request):
    tab = request.GET.get("tab", "requested")
    if tab not in ReturnStatus.values:
        tab = "requested"
    if request.method == "POST":
        r = get_object_or_404(ReturnRequest, pk=request.POST.get("ret"))
        action = request.POST.get("action")
        note = request.POST.get("note", "").strip()
        try:
            if action == "approve":
                restock = request.POST.get("restock") == "1"
                decide_return(r, True, request.user, note=note, restock=restock)
                _email(r.user.email, f"Return {r.reference} approved",
                       f"Hello {r.user.first_name},\n\nYour return {r.reference} is approved. We will collect it from your halls reception.\n"
                       f"Refund (simulated): £{r.refund_amount}.", "return")
                messages.success(request, f"Return {r.reference} approved.{' Items added back to stock.' if restock else ''}")
            elif action == "reject":
                if len(note) < 5:
                    messages.error(request, "Write a short reason so the student understands.")
                    return redirect(f"{reverse('staff:returns')}?reject={r.pk}")
                decide_return(r, False, request.user, note=note)
                _email(r.user.email, f"Return {r.reference}: not approved",
                       f"Hello {r.user.first_name},\n\nWe could not approve return {r.reference}.\nReason: {note}\n\nReply via the Contact page if you have questions.", "return")
                messages.success(request, f"Return {r.reference} rejected. The student was emailed the reason.")
        except OrderError as e:
            messages.error(request, str(e))
        return redirect(f"{reverse('staff:returns')}?tab={tab}")
    qs = ReturnRequest.objects.filter(status=tab).select_related("user", "order").prefetch_related("items__line")
    counts = dict(ReturnRequest.objects.values("status").annotate(n=Count("id")).values_list("status", "n"))
    page = Paginator(qs.order_by("created_at" if tab == "requested" else "-decided_at"), 15).get_page(request.GET.get("page"))
    for r in page.object_list:
        r.age_days = (timezone.now() - r.created_at).days
    reject_id = request.GET.get("reject", "")
    return render(request, "staff/returns.html", {"nav": "ret", "page": page, "tab": tab, "counts": counts,
                                                  "reject_id": reject_id, "now": timezone.now()})


@staff_area("returns")
def return_photo(request, pk):
    from django.http import FileResponse, Http404

    r = get_object_or_404(ReturnRequest, pk=pk)
    if not r.photo:
        raise Http404
    return FileResponse(r.photo.open("rb"), content_type="image/jpeg" if r.photo.name.lower().endswith((".jpg", ".jpeg")) else None)


# ------------------------------------------------------------------ enquiries
@staff_area("enquiries")
def enquiries(request):
    tab = request.GET.get("tab", "open")
    topic = request.GET.get("topic", "")
    qs = Enquiry.objects.all()
    qs = qs.filter(status=Enquiry.Status.RESOLVED) if tab == "resolved" else qs.exclude(status=Enquiry.Status.RESOLVED)
    if topic in dict(TOPICS):
        qs = qs.filter(topic=topic)
    selected = None
    eid = request.GET.get("e") or request.POST.get("enquiry")
    if eid and str(eid).isdigit():
        selected = Enquiry.objects.filter(pk=int(eid)).first()
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action == "reply":
            reply = request.POST.get("reply", "").strip()
            if len(reply) < 10:
                messages.error(request, "Write a reply of at least 10 characters.")
                return redirect(f"{reverse('staff:enquiries')}?e={selected.pk}")
            selected.reply = reply[:4000]
            selected.replied_by = request.user
            selected.replied_at = timezone.now()
            selected.status = Enquiry.Status.RESOLVED
            selected.save()
            _email(selected.email, f"Re: your message {selected.reference}", reply, "support")
            messages.success(request, f"Reply sent to {selected.email} and the enquiry is resolved.")
        elif action == "resolve":
            selected.status = Enquiry.Status.RESOLVED
            selected.save(update_fields=["status"])
            messages.success(request, "Marked as resolved.")
        elif action == "unread":
            selected.status = Enquiry.Status.UNREAD
            selected.save(update_fields=["status"])
        return redirect(f"{reverse('staff:enquiries')}?tab={tab}&e={selected.pk}")
    if selected and selected.status == Enquiry.Status.UNREAD:
        selected.status = Enquiry.Status.READ
        selected.save(update_fields=["status"])
    page = Paginator(qs.order_by("-created_at"), 20).get_page(request.GET.get("page"))
    if selected is None and page.object_list:
        selected = page.object_list[0]
    open_count = Enquiry.objects.exclude(status=Enquiry.Status.RESOLVED).count()
    return render(request, "staff/enquiries.html", {"nav": "enq", "page": page, "tab": tab, "topic": topic, "topics": TOPICS,
                                                    "selected": selected, "open_count": open_count})


# ------------------------------------------------------------------ staff & roles
@staff_area("access")
def access(request):
    form = InviteForm(request.POST if request.method == "POST" and request.POST.get("action") == "invite" else None)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "invite" and form.is_valid():
            token = secrets.token_urlsafe(32)
            inv = StaffInvite.objects.create(email=form.cleaned_data["email"], role=form.cleaned_data["role"], token=token,
                                             invited_by=request.user, expires_at=timezone.now() + timedelta(hours=48))
            link = request.build_absolute_uri(reverse("staff:accept_invite", args=[token]))
            _email(inv.email, "You’re invited to AstonBundle staff",
                   f"Hello,\n\n{request.user.full_name} invited you to join AstonBundle as {inv.get_role_display()}.\n\n"
                   f"Set up your account here (works once, for 48 hours):\n{link}", "invite")
            from accounts.views import _allow_inbox

            _allow_inbox(request, inv.email)
            messages.success(request, f"Invitation sent to {inv.email} (see the Demo inbox).")
            return redirect("staff:access")
        if action in ("role", "remove"):
            member = get_object_or_404(User, pk=request.POST.get("user"), is_staff=True)
            if member == request.user:
                messages.error(request, "You can’t change your own access.")
            elif member.role == Role.OWNER:
                messages.error(request, "The Owner account can’t be changed here.")
            elif action == "remove":
                member.is_active = False
                member.save(update_fields=["is_active"])
                AuditLog.objects.create(actor=request.user, action="remove_staff", target=member.email)
                messages.success(request, f"Access removed for {member.email}.")
            else:
                role = request.POST.get("role")
                if role in (Role.STOCK, Role.SUPPORT):
                    member.role = role
                    member.save(update_fields=["role"])
                    AuditLog.objects.create(actor=request.user, action="change_role", target=f"{member.email}:{role}")
                    messages.success(request, f"{member.full_name} is now {member.get_role_display()}.")
            return redirect("staff:access")
    staff = User.objects.filter(is_staff=True).order_by("role", "email")
    invites = StaffInvite.objects.filter(accepted_at__isnull=True, expires_at__gt=timezone.now())
    matrix = [(AREA_NAMES[a].replace("the ", "").capitalize(), [r in PERMISSIONS[a] for r in (Role.OWNER, Role.STOCK, Role.SUPPORT)])
              for a in ["dashboard", "products", "inventory", "ai", "orders", "customers", "returns", "enquiries", "access"]]
    return render(request, "staff/access.html", {"nav": "acc", "staff": staff, "invites": invites, "form": form,
                                                 "matrix": matrix, "roles": [(Role.STOCK, Role.STOCK.label), (Role.SUPPORT, Role.SUPPORT.label)],
                                                 "log": AuditLog.objects.select_related("actor")[:10]})
