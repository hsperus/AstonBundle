import difflib
import re
from decimal import Decimal, InvalidOperation

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.utils.html import escape
from django.utils.safestring import mark_safe

from ai.recommender import recommend
from reviews.models import Review

from .models import Bundle, Category, Product

SORTS = [
    ("popular", "Most popular"),
    ("price_asc", "Price: low to high"),
    ("price_desc", "Price: high to low"),
    ("rating", "Highest rated"),
    ("newest", "Newest"),
]
ORDERING = {
    "popular": ["-popularity", "name"],
    "price_asc": ["price", "name"],
    "price_desc": ["-price", "name"],
    "rating": ["-rating_avg", "-rating_count"],
    "newest": ["-created_at"],
    "relevance": ["-popularity"],
}
PER_PAGE = 12
MAX_QUERY = 80


def _decimal(value):
    try:
        d = Decimal(str(value).strip().replace("£", ""))
        return d if d >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def _highlight(text, terms):
    out = escape(text)
    for t in sorted(terms, key=len, reverse=True):
        if len(t) >= 2:
            out = re.sub(f"({re.escape(escape(t))})", r"<mark>\1</mark>", out, flags=re.I)
    return mark_safe(out)


def _filters(request, base_categories=None):
    """Read and validate filter parameters. Invalid values are ignored, not trusted."""
    f = {}
    slugs = request.GET.getlist("cat")
    valid = set(Category.objects.values_list("slug", flat=True))
    submitted = "f" in request.GET or "cat" in request.GET
    f["cats"] = [s for s in slugs if s in valid] if submitted or base_categories is None else base_categories
    f["min"] = _decimal(request.GET.get("min", "")) if request.GET.get("min") else None
    f["max"] = _decimal(request.GET.get("max", "")) if request.GET.get("max") else None
    f["errors"] = []
    if request.GET.get("min") and f["min"] is None:
        f["errors"].append("Minimum price must be a number, for example 5.")
    if request.GET.get("max") and f["max"] is None:
        f["errors"].append("Maximum price must be a number, for example 25.")
    if f["min"] is not None and f["max"] is not None and f["min"] > f["max"]:
        f["errors"].append("The minimum price is higher than the maximum.")
        f["min"], f["max"] = f["max"], f["min"]
    f["stock"] = request.GET.get("stock") == "1"
    try:
        f["rating"] = int(request.GET.get("rating", "0"))
    except ValueError:
        f["rating"] = 0
    f["rating"] = f["rating"] if f["rating"] in (3, 4) else 0
    return f


def _apply(qs, f):
    if f["cats"]:
        qs = qs.filter(category__slug__in=f["cats"])
    if f["min"] is not None:
        qs = qs.filter(price__gte=f["min"])
    if f["max"] is not None:
        qs = qs.filter(price__lte=f["max"])
    if f["stock"]:
        qs = qs.filter(stock__gt=0)
    if f["rating"]:
        qs = qs.filter(rating_avg__gte=f["rating"])
    return qs


def _listing(request, template, base_qs, f, extra, default_sort="popular"):
    sort = request.GET.get("sort", default_sort)
    sorts = list(SORTS)
    if default_sort == "relevance":
        sorts = [("relevance", "Best match")] + sorts
    if sort not in dict(sorts):
        sort = default_sort
    filtered = _apply(base_qs, f)
    hidden_out = 0
    if f["stock"]:
        hidden_out = _apply(base_qs, {**f, "stock": False}).filter(stock=0).count()
    paginator = Paginator(filtered.order_by(*ORDERING[sort]).select_related("category"), PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))
    # counts per category for the filter panel (respecting the other filters)
    counts = dict(
        _apply(base_qs, {**f, "cats": []}).values_list("category__slug").annotate(n=Count("id")).values_list("category__slug", "n")
    )
    def without(*keys, cat=None):
        q = request.GET.copy()
        q.pop("page", None)
        if cat is not None:
            q.setlist("cat", [c for c in f["cats"] if c != cat])
        for k in keys:
            q.pop(k, None)
        q["f"] = "1"
        return "?" + q.urlencode()

    names = dict(Category.objects.values_list("slug", "name"))
    active = [(names[slug], without(cat=slug)) for slug in f["cats"] if slug in names]
    if f["min"] is not None or f["max"] is not None:
        label = f"£{f['min'] or 0:g}–£{f['max']:g}" if f["max"] is not None else f"From £{f['min']:g}"
        active.append((label, without("min", "max")))
    if f["stock"]:
        active.append(("In stock", without("stock")))
    if f["rating"]:
        active.append((f"{f['rating']}★ and above", without("rating")))
    ctx = {
        "page": page,
        "f": f,
        "sort": sort,
        "sorts": sorts,
        "categories": Category.objects.all(),
        "cat_counts": counts,
        "active_filters": active,
        "hidden_out": hidden_out,
        "total": paginator.count,
    }
    ctx.update(extra)
    return render(request, template, ctx)


def category(request, slug):
    cat = get_object_or_404(Category, slug=slug)
    f = _filters(request, base_categories=[cat.slug])
    bundle = (Bundle.objects.filter(is_active=True)
              .annotate(n=Count("items", filter=Q(items__product__category=cat))).filter(n__gt=0).order_by("-n").first())
    return _listing(request, "catalog/listing.html", Product.objects.active(), f,
                    {"category": cat, "active_category": cat.slug, "title": cat.name, "bundle": bundle})


def all_products(request):
    f = _filters(request)
    return _listing(request, "catalog/listing.html", Product.objects.active(), f, {"title": "All products"})


def search(request):
    q = (request.GET.get("q") or "").strip()[:MAX_QUERY]
    terms = [t for t in re.split(r"\s+", q) if t]
    f = _filters(request)
    if not terms:
        return _listing(request, "catalog/listing.html", Product.objects.active(), f, {"title": "All products"})
    cond = Q()
    for t in terms:
        cond &= (Q(name__icontains=t) | Q(summary__icontains=t) | Q(description__icontains=t)
                 | Q(category__name__icontains=t) | Q(sku__iexact=t) | Q(features__icontains=t))
    base = Product.objects.active().filter(cond)
    bundle_cond = Q()
    for t in terms:
        bundle_cond &= (Q(name__icontains=t) | Q(tagline__icontains=t) | Q(items__product__name__icontains=t))
    bundles = list(Bundle.objects.filter(is_active=True).filter(bundle_cond).distinct().prefetch_related("items__product"))
    for b in bundles:
        hit = next((i.product for i in b.items.all() if any(t.lower() in i.product.name.lower() for t in terms)), None)
        b.match_note = _highlight(f"Includes {hit.name}", terms) if hit else ""
    suggestion, ideas = "", []
    if not base.exists() and not bundles:
        vocab = set()
        for name in Product.objects.active().values_list("name", flat=True):
            vocab.update(w.lower().strip(",.×") for w in name.split() if len(w) > 2)
        fixed = []
        for t in terms:
            m = difflib.get_close_matches(t.lower(), vocab, n=1, cutoff=0.7)
            fixed.append(m[0] if m else t)
        if [x.lower() for x in fixed] != [t.lower() for t in terms]:
            suggestion = " ".join(fixed)
        ideas = list(Product.objects.active().in_stock().order_by("-popularity")[:4])
    response = _listing(request, "catalog/search.html", base, f,
                        {"q": q, "terms": terms, "bundles": bundles, "suggestion": suggestion, "ideas": ideas,
                         "title": f"Results for “{q}”"}, default_sort="relevance")
    return response


def product(request, slug):
    p = get_object_or_404(Product.objects.select_related("category"), slug=slug, is_active=True)
    reviews_qs = Review.objects.filter(product=p, is_visible=True).select_related("user")
    sort = request.GET.get("rsort", "recent")
    reviews_qs = reviews_qs.order_by("-rating", "-created_at") if sort == "high" else (
        reviews_qs.order_by("rating", "-created_at") if sort == "low" else reviews_qs.order_by("-created_at"))
    show = 3 if request.GET.get("reviews") != "all" else 50
    dist = {i: 0 for i in range(1, 6)}
    for r, n in Review.objects.filter(product=p, is_visible=True).values_list("rating").annotate(n=Count("id")):
        dist[r] = n
    total = sum(dist.values())
    recommend_pct = round(100 * (dist[4] + dist[5]) / total) if total else 0
    bundles = Bundle.objects.filter(is_active=True, items__product=p).distinct().prefetch_related("items__product")
    can_review = False
    if request.user.is_authenticated:
        from orders.models import OrderLine, OrderStatus

        can_review = OrderLine.objects.filter(order__user=request.user, order__status=OrderStatus.DELIVERED, product=p).exists() \
            and not Review.objects.filter(product=p, user=request.user).exists()
    return render(request, "catalog/product.html", {
        "p": p,
        "active_category": p.category.slug,
        "reviews": list(reviews_qs[:show]),
        "review_total": total,
        "review_sort": sort,
        "dist": [(i, dist[i], round(100 * dist[i] / total) if total else 0) for i in range(5, 0, -1)],
        "recommend_pct": recommend_pct,
        "bundles": bundles,
        "recs": recommend([p.pk], k=4),
        "can_review": can_review,
        "show_all_reviews": show > 3,
    })


def bundles(request):
    items = Bundle.objects.filter(is_active=True).prefetch_related("items__product")
    return render(request, "catalog/bundles.html", {"bundles": items, "active_category": "bundles"})


def bundle(request, slug):
    b = get_object_or_404(Bundle.objects.prefetch_related("items__product__category"), slug=slug, is_active=True)
    lines = b.lines()
    return render(request, "catalog/bundle.html", {
        "b": b,
        "lines": lines,
        "available": b.available,
        "active_category": "bundles",
        "others": Bundle.objects.filter(is_active=True).exclude(pk=b.pk).prefetch_related("items__product")[:3],
    })


def how_suggestions_work(request):
    from ai.models import ModelRun

    return render(request, "catalog/how_suggestions.html", {"run": ModelRun.latest(ModelRun.Kind.RECOMMENDER)})
