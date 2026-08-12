"""Shared helpers for the API tests: URL builders and well-formed unknown identifiers.

URLs go through reverse() so routing knowledge lives only in config/urls.py; a renamed
route fails here with a NoReverseMatch naming the missing route, not as an opaque 404
assertion somewhere downstream.
"""

import hashlib
import hmac
import json

from django.urls import reverse

# Syntactically valid per REFERENCE_PATTERN, guaranteed never minted (ids are random hex).
UNKNOWN_REFERENCE = "TRF-" + "0" * 16

# The secret every webhook test signs with; tests override the setting to match.
WEBHOOK_TEST_SECRET = "test-webhook-secret"


def webhook_url() -> str:
    return reverse("provider-webhook")


def sign_body(body: bytes, secret: str = WEBHOOK_TEST_SECRET) -> str:
    """Compute the X-Provider-Signature header value for a raw body, as a sender does."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def post_webhook(
    client,
    payload: dict,
    *,
    secret: str = WEBHOOK_TEST_SECRET,
    header=None,
    body: bytes | None = None,
):
    """POST a provider webhook the way the provider would: serialise, sign the bytes, send.

    ``header`` overrides the computed signature header (pass "" to omit signing).
    ``body`` overrides the serialisation — the signature must bind to whatever bytes the
    sender actually produced, so a test can post the same payload spelled differently.
    """
    if body is None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = sign_body(body, secret) if header is None else header
    extra = {"HTTP_X_PROVIDER_SIGNATURE": signature} if signature else {}
    return client.post(
        webhook_url(), body, content_type="application/json", **extra
    )


def create_url() -> str:
    return reverse("transfer-list")


def detail_url(reference: str) -> str:
    return reverse("transfer-detail", args=[reference])


def submit_url(reference: str) -> str:
    return reverse("transfer-submit", args=[reference])


def cancel_url(reference: str) -> str:
    return reverse("transfer-cancel", args=[reference])
