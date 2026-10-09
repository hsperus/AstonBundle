"""Simulated email: messages are written to the DemoEmail table and shown in the
Demo Inbox page. Nothing leaves the server, so no real student address is ever emailed."""
from django.core.mail.backends.base import BaseEmailBackend


class DemoInboxBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        from .models import DemoEmail

        count = 0
        for message in email_messages:
            kind = message.extra_headers.get("X-AB-Kind", "general") if message.extra_headers else "general"
            for recipient in message.to:
                DemoEmail.objects.create(to_email=recipient.lower(), subject=message.subject, body=message.body, kind=kind)
                count += 1
        return count
