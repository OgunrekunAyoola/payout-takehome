"""Fire a signed provider webhook at a running local server.

    python manage.py fire_webhook prov_1234abcd5678ef90 --status completed

Signs with the same PROVIDER_WEBHOOK_SECRET the server verifies against, so a locally
fired webhook authenticates out of the box. Uses only the standard library — this is a
dev tool, not worth a dependency.
"""

import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "POST a signed provider webhook to a running server."

    def add_arguments(self, parser):
        parser.add_argument("provider_transfer_id")
        parser.add_argument(
            "--status", choices=["completed", "failed"], default="completed"
        )
        parser.add_argument(
            "--event-id",
            default=None,
            help="Defaults to a fresh evt_<hex>. Reuse one to exercise idempotency.",
        )
        parser.add_argument(
            "--url", default="http://127.0.0.1:8000/api/webhooks/provider/"
        )

    def handle(self, provider_transfer_id, status, event_id, url, **options):
        payload = {
            "event_id": event_id or f"evt_{uuid.uuid4().hex[:16]}",
            "provider_transfer_id": provider_transfer_id,
            "status": status,
            "occurred_at": timezone.now().isoformat(),
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(
            settings.PROVIDER_WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()

        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Provider-Signature": f"sha256={signature}",
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                self.stdout.write(f"{response.status} {response.read().decode()}")
        except urllib.error.HTTPError as error:
            self.stdout.write(f"{error.code} {error.read().decode()}")
        except urllib.error.URLError as error:
            self.stderr.write(
                f"Could not reach {url} ({error.reason}). Is the server running?"
            )
