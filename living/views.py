from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect, render

from support.models import Enquiry
from support.views import RATE_LIMIT, _client_key

from .forms import BookingRequestForm
from .models import Facility, RoomType
from .seed_data import BUILDING, INCLUDED


def building_image_url():
    path = f"living/{BUILDING['image']}.webp"
    return f"/{settings.MEDIA_URL.strip('/')}/{path}" if default_storage.exists(path) else ""


def _context(**extra):
    return {"rooms": RoomType.objects.filter(is_active=True), "facilities": Facility.objects.all(),
            "included": INCLUDED, "building": BUILDING, "building_image": building_image_url(),
            "active_category": "living", **extra}


def overview(request):
    return render(request, "living/overview.html", _context())


def room(request, slug):
    r = get_object_or_404(RoomType, slug=slug, is_active=True)
    form = BookingRequestForm(initial=_initial(request, r))
    return render(request, "living/room.html", _context(r=r, form=form))


def _initial(request, r):
    initial = {"room": r.slug if r else None}
    if request.user.is_authenticated and not request.user.is_staff:
        initial.update(name=request.user.full_name, email=request.user.email)
    return initial


def request_room(request):
    """Booking request: recorded as an enquiry for the residence team. Nothing is reserved or paid."""
    if request.method != "POST":
        return redirect("living:overview")
    form = BookingRequestForm(request.POST)
    key = _client_key(request)
    count = cache.get(key, 0)
    if count >= RATE_LIMIT:
        form.add_error(None, "Too many messages. Please wait an hour before sending another request.")
    elif form.is_valid():
        d = form.cleaned_data
        start = dict(form.fields["move_in"].choices)[d["move_in"]]
        msg = (f"Booking request: {d['room'].name} (£{d['room'].price_per_week}/week, {d['room'].contract_weeks} weeks)\n"
               f"Start: {start}\n\n{d['needs'] or 'No extra notes.'}")
        e = Enquiry.objects.create(name=d["name"], email=d["email"], topic="accommodation", message=msg,
                                   user=request.user if request.user.is_authenticated else None)
        cache.set(key, count + 1, 3600)
        request.session["last_enquiry"] = e.reference
        return redirect("support:sent")
    r = RoomType.objects.filter(slug=request.POST.get("room"), is_active=True).first() or RoomType.objects.filter(is_active=True).first()
    return render(request, "living/room.html", _context(r=r, form=form), status=200)
