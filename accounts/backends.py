from datetime import timedelta

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.utils import timezone

from .models import User


class EmailBackend(ModelBackend):
    """Email + password sign-in with a lockout after repeated failures."""

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        email = (email or username or "").strip().lower()
        if not email or not password:
            return None
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            User().set_password(password)  # equalise timing
            return None
        if user.is_locked:
            if request is not None:
                request.auth_locked = True
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            if user.failed_logins:
                user.failed_logins = 0
                user.locked_until = None
                user.save(update_fields=["failed_logins", "locked_until"])
            return user
        user.failed_logins += 1
        if user.failed_logins >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            user.locked_until = timezone.now() + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
            user.failed_logins = 0
            if request is not None:
                request.auth_locked = True
        user.save(update_fields=["failed_logins", "locked_until"])
        return None
