import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

HALLS = [
    ("Canal View Halls", "Canal View Halls"),
    ("Lakeside Court", "Lakeside Court"),
    ("Gosta Green House", "Gosta Green House"),
    ("Woodcock Street Studios", "Woodcock Street Studios"),
    ("Other / private housing", "Other / private housing"),
]


class Role(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    OWNER = "owner", "Owner"
    STOCK = "stock", "Stock manager"
    SUPPORT = "support", "Customer support"


# Which staff role may use which admin area. Checked on the server for every request.
PERMISSIONS = {
    "dashboard": {Role.OWNER, Role.STOCK, Role.SUPPORT},
    "products": {Role.OWNER, Role.STOCK},
    "inventory": {Role.OWNER, Role.STOCK},
    "ai": {Role.OWNER, Role.STOCK},
    "orders": {Role.OWNER, Role.STOCK, Role.SUPPORT},
    "customers": {Role.OWNER, Role.SUPPORT},
    "returns": {Role.OWNER, Role.SUPPORT},
    "enquiries": {Role.OWNER, Role.SUPPORT},
    "access": {Role.OWNER},
}


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("role", Role.CUSTOMER)
        return self._create_user(email, password, **extra)

    def create_staff(self, email, password=None, role=Role.STOCK, **extra):
        extra.update(is_staff=True, role=role, email_verified=True)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, role=Role.OWNER, email_verified=True)
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Customers and staff share one table; `role` decides what they can do.

    Personal data is kept to the minimum the shop needs: name, email,
    halls + room for delivery, an optional arrival date and optional phone.
    """

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=120)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    halls = models.CharField(max_length=60, choices=HALLS, blank=True)
    room = models.CharField(max_length=20, blank=True)
    arrival_date = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(null=True, blank=True)
    failed_logins = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    is_test_data = models.BooleanField(default=False, help_text="Synthetic record created by the seed script.")

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return self.email

    @property
    def first_name(self):
        return (self.full_name or self.email).split()[0]

    @property
    def initials(self):
        parts = (self.full_name or "?").split()
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    @property
    def is_customer(self):
        return self.role == Role.CUSTOMER

    def can(self, area):
        return self.is_active and self.is_staff and self.role in PERMISSIONS.get(area, set())

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    @property
    def masked_email(self):
        local, _, domain = self.email.partition("@")
        return f"{local[:2]}{'•' * max(3, len(local) - 2)}@{domain}"

    @property
    def masked_name(self):
        parts = self.full_name.split()
        if not parts:
            return "•••"
        return " ".join([parts[0]] + [p[0] + "•••" for p in parts[1:]])


def _hash_code(code: str) -> str:
    return hashlib.sha256((settings.SECRET_KEY + code).encode()).hexdigest()


class EmailVerification(models.Model):
    """A 6-digit code sent (to the Demo Inbox) to prove the student owns the address.
    Only a hash of the code is stored."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verifications")
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def issue(cls, user):
        cls.objects.filter(user=user, used=False).update(used=True)
        code = f"{secrets.randbelow(10**6):06d}"
        obj = cls.objects.create(
            user=user,
            code_hash=_hash_code(code),
            expires_at=timezone.now() + timedelta(minutes=settings.VERIFICATION_CODE_TTL_MINUTES),
        )
        return obj, code

    @property
    def expired(self):
        return timezone.now() >= self.expires_at

    @property
    def attempts_left(self):
        return max(0, settings.VERIFICATION_MAX_ATTEMPTS - self.attempts)

    def verify(self, code: str) -> bool:
        if self.used or self.expired or self.attempts_left == 0:
            return False
        self.attempts += 1
        ok = secrets.compare_digest(self.code_hash, _hash_code(code))
        if ok:
            self.used = True
        self.save(update_fields=["attempts", "used"])
        return ok


class DemoEmail(models.Model):
    """Simulated outbox. Shown on the Demo Inbox page; never delivered."""

    to_email = models.EmailField(db_index=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    kind = models.CharField(max_length=30, default="general")
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.to_email}: {self.subject}"


class StaffInvite(models.Model):
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Role.choices)
    token = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_valid(self):
        return self.accepted_at is None and timezone.now() < self.expires_at


class AuditLog(models.Model):
    """Records sensitive staff actions, e.g. revealing a customer's details."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    action = models.CharField(max_length=60)
    target = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    LABELS = {"reveal_customer": "revealed details", "suspend_customer": "suspended account",
              "restore_customer": "restored account", "remove_staff": "removed staff access", "change_role": "changed role"}

    def get_action_label(self):
        return self.LABELS.get(self.action, self.action.replace("_", " "))
