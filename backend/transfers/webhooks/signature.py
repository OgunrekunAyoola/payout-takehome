"""Verification of the provider's webhook signature.

The provider sends ``X-Provider-Signature: sha256=<hex>``, an HMAC-SHA256 keyed with the
shared ``PROVIDER_WEBHOOK_SECRET`` and computed over the **raw request body** — the exact
bytes the provider put on the wire. Verification must pass before anything else looks at
the payload — before parsing feeds the serializer, before the transfer lookup, before
dedupe — so an unauthenticated caller can never use this endpoint to probe which provider
ids exist.

Raw bytes, never a re-serialisation: canonicalising the parsed payload and signing *that*
means verifying something other than what was sent (see canonical.py, whose tolerance is
for idempotency comparison only). A provider signs the bytes their serialiser produced,
and any provider whose key order or whitespace differs from ours — which is to say, any
real provider — would fail a canonalised check forever, as a permanent 401 their retries
can never escape.

Every malformed header — wrong prefix, not hex, wrong length — is an ordinary ``False``,
never an exception: this function's callers promise a uniform 401, and an unexpected 500
is both an information leak and the one status a provider retries forever.

Comparison is ``hmac.compare_digest`` rather than ``==``: string equality short-circuits
at the first differing byte, so how long it takes leaks how much of a guess was right.

A known limitation, accepted for this exercise: the signed material carries no timestamp,
so a captured request stays valid forever and can be replayed later (it re-enters the
dedupe and re-judging machinery, which bounds the damage but does not eliminate it). The
standard fix is signing ``timestamp || body`` and refusing stale timestamps; that needs
the provider's cooperation on header format, so it is documented in the README rather
than invented unilaterally here.
"""

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


def verify_signature(body: bytes, header: str, secret: str) -> bool:
    """Return True if ``header`` correctly signs the raw request ``body``."""
    if not header or not header.startswith(SIGNATURE_PREFIX):
        return False
    try:
        provided = bytes.fromhex(header[len(SIGNATURE_PREFIX):])
    except ValueError:
        # Not hex at all. compare_digest would raise on non-ASCII input, and a crash
        # here is a 500 where the contract promises an indistinguishable 401.
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return hmac.compare_digest(expected, provided)
