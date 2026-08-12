"""Verification of the provider's webhook signature.

The provider sends ``X-Provider-Signature: sha256=<hex>``, an HMAC-SHA256 keyed with the
shared ``PROVIDER_WEBHOOK_SECRET``. Verification must pass before anything else looks at
the payload — before the transfer lookup, before dedupe — so an unauthenticated caller
can never use this endpoint to probe which provider ids exist.

Comparison is ``hmac.compare_digest`` rather than ``==``: string equality short-circuits
at the first differing byte, so how long it takes leaks how much of a guess was right.
"""

import hashlib
import hmac
import json

SIGNATURE_PREFIX = "sha256="


def verify_signature(payload, header: str, secret: str) -> bool:
    """Return True if ``header`` correctly signs ``payload``.

    The payload is serialised to canonical JSON (sorted keys, no insignificant
    whitespace) before computing the HMAC, the same normalisation the idempotency
    fingerprint uses — so differences in key order or spacing between the provider's
    serialiser and ours don't matter.
    """
    if not header or not header.startswith(SIGNATURE_PREFIX):
        return False
    provided = header[len(SIGNATURE_PREFIX):]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    expected = hmac.new(
        secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)
