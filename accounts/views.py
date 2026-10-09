from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordResetConfirmView
from django.core.mail import EmailMessage
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_encode
from django.views.decorators.http import require_POST

from orders.models import Order, OrderStatus

from .forms import DeleteAccountForm, ForgotForm, ProfileForm, RegisterForm, SignInForm, StrongSetPasswordForm, VerifyForm
from .models import DemoEmail, EmailVerification, Role, User

INBOX_KEY = "demo_inbox"


def _allow_inbox(request, email):
    allowed = set(request.session.get(INBOX_KEY, []))
    allowed.add(email.lower())
    request.session[INBOX_KEY] = sorted(allowed)[-10:]


def _send(to, subject, body, kind):
    EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [to], headers={"X-AB-Kind": kind}).send()


def send_verification(request, user):
    _obj, code = EmailVerification.issue(user)
    _send(user.email, f"Your verification code: {code}",
          f"Hello {user.first_name},\n\nUse this code to finish creating your AstonBundle account:\n\n{code}\n\n"
          f"The code works for {settings.VERIFICATION_CODE_TTL_MINUTES} minutes. If you did not ask for it, you can ignore this email.\n\n"
          "AstonBundle · A student project at Aston University, Birmingham", "verify")
    _allow_inbox(request, user.email)
    request.session["verify_uid"] = user.pk


def _safe_next(request, default):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return default


def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:overview")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            user = User.objects.filter(email__iexact=d["email"], email_verified=False).first()
            if user is None:
                user = User(email=d["email"])
            user.full_name = d["full_name"]
            user.role = Role.CUSTOMER
            user.set_password(d["password"])
            user.save()
        registered = set(request.session.get("registered_here", []))
        registered.add(user.email)
        request.session["registered_here"] = sorted(registered)[-10:]
        send_verification(request, user)
        return redirect("accounts:verify")
    return render(request, "accounts/register.html", {"form": form})


def verify(request):
    uid = request.session.get("verify_uid")
    user = User.objects.filter(pk=uid, email_verified=False).first() if uid else None
    if user is None:
        messages.info(request, "Sign in or create an account first.")
        return redirect("accounts:register")
    current = user.verifications.filter(used=False).first()
    form = VerifyForm(request.POST or None)
    error = ""
    if request.method == "POST":
        if "resend" in request.POST:
            recent = current and (timezone.now() - current.created_at).total_seconds() < 30
            if recent:
                error = "Please wait 30 seconds before asking for a new code."
            else:
                send_verification(request, user)
                messages.success(request, "We sent a new code. Check the Demo inbox.")
                return redirect("accounts:verify")
        elif form.is_valid():
            if current is None or current.expired:
                error = "This code has expired. Ask for a new code."
            elif current.attempts_left == 0:
                error = "Too many wrong attempts. Ask for a new code."
            elif current.verify(form.cleaned_data["code"]):
                user.email_verified = True
                user.save(update_fields=["email_verified"])
                request.session.pop("verify_uid", None)
                login(request, user, backend="accounts.backends.EmailBackend")
                messages.success(request, "Your email is verified. Welcome to AstonBundle!")
                return redirect(_safe_next(request, reverse("accounts:overview")))
            else:
                left = current.attempts_left
                error = f"That code is not right. {left} attempt{'s' if left != 1 else ''} left." if left else "Too many wrong attempts. Ask for a new code."
    seconds_left = max(0, int((current.expires_at - timezone.now()).total_seconds())) if current else 0
    return render(request, "accounts/verify.html", {
        "form": form, "email": user.email, "error": error, "seconds_left": seconds_left,
        "attempts_left": current.attempts_left if current else 0,
    })


def demo_inbox(request):
    """Simulated inbox. For privacy, it only shows mail for addresses used in this
    browser session (or the signed-in user's own address)."""
    if not settings.DEMO_INBOX_ENABLED:
        return render(request, "accounts/demo_inbox.html", {"disabled": True})
    allowed = set(request.session.get(INBOX_KEY, []))
    if request.user.is_authenticated:
        allowed.add(request.user.email.lower())
    to = (request.GET.get("to") or "").strip().lower()
    if to not in allowed:
        to = sorted(allowed)[0] if allowed else ""
    mails = DemoEmail.objects.filter(to_email=to)[:30] if to else []
    selected = None
    if mails:
        mid = request.GET.get("m")
        selected = next((m for m in mails if str(m.pk) == mid), mails[0])
        if not selected.read:
            DemoEmail.objects.filter(pk=selected.pk).update(read=True)
    code = ""
    if selected and selected.kind == "verify":
        code = "".join(ch for ch in selected.subject if ch.isdigit())[-6:]
    return render(request, "accounts/demo_inbox.html", {"to": to, "addresses": sorted(allowed), "mails": mails,
                                                        "selected": selected, "code": code})


def signin(request):
    if request.user.is_authenticated:
        return redirect(_safe_next(request, reverse("accounts:overview")))
    form = SignInForm(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        from django.contrib.auth import authenticate

        user = authenticate(request, email=form.cleaned_data["email"], password=form.cleaned_data["password"])
        if getattr(request, "auth_locked", False):
            error = f"Too many attempts. For your safety, sign-in is paused for {settings.LOGIN_LOCKOUT_MINUTES} minutes. You can reset your password."
        elif user is None:
            error = "Email or password is not right. Please check and try again."
        elif user.is_staff:
            error = "This is a staff account. Please use Staff sign-in."
        elif not user.email_verified:
            send_verification(request, user)
            messages.info(request, "Please verify your email first. We sent a new code.")
            return redirect("accounts:verify")
        else:
            login(request, user)
            if not form.cleaned_data.get("remember"):
                request.session.set_expiry(0)
            return redirect(_safe_next(request, reverse("accounts:overview")))
    return render(request, "accounts/signin.html", {"form": form, "error": error, "next": request.GET.get("next", "")})


@require_POST
def signout(request):
    logout(request)
    messages.success(request, "You have signed out. Your basket is saved on this device.")
    return redirect("accounts:signin")


def forgot(request):
    form = ForgotForm(request.POST or None)
    sent_to = ""
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True, role=Role.CUSTOMER).first()
        if user and user.has_usable_password():
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = request.build_absolute_uri(reverse("accounts:reset", args=[uid, token]))
            _send(user.email, "Reset your AstonBundle password",
                  f"Hello {user.first_name},\n\nSomeone asked to reset the password for your AstonBundle account.\n\n"
                  f"Set a new password here (the link works for 30 minutes):\n{link}\n\n"
                  "If this wasn’t you, ignore this email — your password will not change.", "reset")
        # Simulation safeguard: only reveal reset links in the Demo inbox for public test
        # accounts or an account created in this browser session, so nobody can read
        # another student's reset link. The page response is the same either way.
        if email in settings.DEMO_RESET_VISIBLE or email in request.session.get("registered_here", []):
            _allow_inbox(request, email)
        sent_to = email
    return render(request, "accounts/forgot.html", {"form": form, "sent_to": sent_to})


class ResetConfirm(PasswordResetConfirmView):
    template_name = "accounts/reset.html"
    form_class = StrongSetPasswordForm
    success_url = reverse_lazy("accounts:signin")
    post_reset_login = False

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        user.failed_logins = 0
        user.locked_until = None
        user.save(update_fields=["failed_logins", "locked_until"])
        messages.success(self.request, "Your password has been changed. Please sign in.")
        return response


def _customer_required(view):
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.is_staff:
            return redirect("staff:dashboard")
        return view(request, *args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


@_customer_required
def overview(request):
    user = request.user
    recent = user.orders.prefetch_related("lines__product", "returns").first()
    days_to_go = deliver_from = None
    if user.arrival_date:
        from datetime import timedelta

        days_to_go = (user.arrival_date - timezone.localdate()).days
        deliver_from = user.arrival_date - timedelta(days=3)
    return render(request, "accounts/overview.html", {"recent": recent, "days_to_go": days_to_go, "deliver_from": deliver_from})


@_customer_required
def profile(request):
    user = request.user
    pform = ProfileForm(instance=user)
    pwform = PasswordChangeForm(user)
    dform = DeleteAccountForm()
    open_section = ""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "details":
            pform = ProfileForm(request.POST, instance=user)
            if pform.is_valid():
                pform.save()
                if user.arrival_date:
                    request.session["arrival_date"] = user.arrival_date.isoformat()
                messages.success(request, "Your details have been saved.")
                return redirect("accounts:profile")
        elif action == "password":
            pwform = PasswordChangeForm(user, request.POST)
            if pwform.is_valid():
                pwform.save()
                update_session_auth_hash(request, pwform.user)
                messages.success(request, "Your password has been updated.")
                return redirect("accounts:profile")
            open_section = "password"
        elif action == "delete":
            dform = DeleteAccountForm(request.POST)
            if dform.is_valid():
                anonymise_user(user)
                logout(request)
                messages.success(request, "Your account has been deleted.")
                return redirect("core:home")
            open_section = "delete"
    open_orders = user.orders.filter(status__in=[OrderStatus.PLACED, OrderStatus.PROCESSING, OrderStatus.DISPATCHED])
    return render(request, "accounts/profile.html", {"pform": pform, "pwform": pwform, "dform": dform,
                                                     "open_section": open_section, "open_orders": open_orders})


@transaction.atomic
def anonymise_user(user):
    """Delete personal data but keep anonymous order records (needed for accounts/tax)."""
    user.orders.filter(status__in=[OrderStatus.DELIVERED, OrderStatus.CANCELLED]).update(
        recipient_name="Deleted user", room="", address_line="", postcode="", phone="")
    user.reviews.update(course="")
    DemoEmail.objects.filter(to_email=user.email).delete()
    user.email = f"deleted-{user.pk}@deleted.invalid"
    user.full_name = "Deleted user"
    user.halls = user.room = user.phone = ""
    user.arrival_date = None
    user.is_active = False
    user.set_unusable_password()
    user.save()
