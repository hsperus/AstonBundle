import secrets
from datetime import date

from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import render

from accounts.models import HALLS
from ai.recommender import recommend
from catalog.models import Bundle, Category, Product
from orders import slots


def _parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def home(request):
    from living.models import RoomType
    from living.views import building_image_url

    bundles = list(Bundle.objects.filter(is_active=True, featured=True).prefetch_related("items__product")[:4])
    categories = Category.objects.annotate(n=Count("products", filter=Q(products__is_active=True))).order_by("sort", "name")
    # "Frequently bought together": start from the most popular product in stock
    anchor = Product.objects.active().in_stock().order_by("-popularity").first()
    combo = []
    if anchor:
        combo = [anchor] + recommend([anchor.pk], k=2)
    arrival = _parse_date(request.session.get("arrival_date"))
    return render(request, "core/home.html", {
        "bundles": bundles,
        "categories": categories,
        "combo": combo,
        "combo_total": sum(p.price for p in combo),
        "halls": HALLS,
        "arrival": arrival,
        "earliest": slots.earliest_date(),
        "living_image": building_image_url(),
        "living_from": RoomType.objects.filter(is_active=True).order_by("price_per_week").first(),
    })


def about(request):
    team = [
        ("BR", "Bhargav Reddy Bommidi", "coral-50"),
        ("CS", "Charulata Sharma", "teal-50"),
        ("ÖY", "Ömer Tarık Yılmaz", "navy-50"),
        ("PS", "Pavankumar Samana", "amber-50"),
        ("RZ", "Rita Zambito", "coral-50"),
    ]
    return render(request, "core/about.html", {"team": team})


def guide(request):
    return render(request, "core/guide.html")


def delivery(request):
    """Delivery-date finder used by the home page 'When do you arrive?' form."""
    arrival = _parse_date(request.GET.get("arrival")) or _parse_date(request.session.get("arrival_date"))
    halls = request.GET.get("halls") or request.session.get("halls", "")
    error = ""
    if request.GET.get("arrival") and arrival is None:
        error = "Enter your arrival date, for example 09/01/2027."
    if arrival:
        if arrival < slots.earliest_date():
            error = f"We need at least {slots.LEAD_DAYS} days. Choose a date from {slots.earliest_date().day} {slots.earliest_date().strftime('%B %Y')}."
        else:
            request.session["arrival_date"] = arrival.isoformat()
            if halls in dict(HALLS):
                request.session["halls"] = halls
    days = slots.days_for(arrival) if arrival and not error else []
    return render(request, "core/delivery.html", {"arrival": arrival, "days": days, "halls": halls, "hall_choices": HALLS,
                                                  "error": error, "earliest": slots.earliest_date()})


PAGES = {
    "returns": "Returns policy",
    "privacy": "Privacy notice",
    "accessibility": "Accessibility statement",
    "terms": "Terms of use",
}


def page(request, slug):
    if slug == "delivery":
        return delivery(request)
    if slug not in PAGES:
        raise Http404
    return render(request, f"core/page_{slug}.html", {"title": PAGES[slug]})


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    ref = "500-AB-" + secrets.token_hex(3).upper()
    return render(request, "errors/500.html", {"ref": ref}, status=500)


def error_403(request, exception=None):
    return render(request, "errors/403.html", status=403)
