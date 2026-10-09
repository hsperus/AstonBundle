from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ContactForm
from .models import Enquiry

RATE_LIMIT = 5  # messages per hour per session/IP


def _client_key(request):
    ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "")).split(",")[0].strip()
    return f"contact:{ip}"


def contact(request):
    initial = {"order_number": request.GET.get("order", "")[:20]}
    if request.GET.get("order"):
        initial["topic"] = "order"
    if request.user.is_authenticated and not request.user.is_staff:
        initial.update(name=request.user.full_name, email=request.user.email)
    form = ContactForm(request.POST or None, initial=initial)
    limited = False
    if request.method == "POST":
        key = _client_key(request)
        count = cache.get(key, 0)
        if count >= RATE_LIMIT:
            limited = True
        elif form.is_valid():
            d = form.cleaned_data
            e = Enquiry.objects.create(name=d["name"], email=d["email"], topic=d["topic"], order_number=d["order_number"],
                                       message=d["message"],
                                       user=request.user if request.user.is_authenticated else None)
            cache.set(key, count + 1, 3600)
            request.session["last_enquiry"] = e.reference
            return redirect("support:sent")
    return render(request, "support/contact.html", {"form": form, "limited": limited})


def sent(request):
    ref = request.session.get("last_enquiry")
    if not ref:
        return redirect("support:contact")
    e = get_object_or_404(Enquiry, reference=ref)
    return render(request, "support/sent.html", {"e": e})
