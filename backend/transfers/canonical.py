"""Canonical fingerprinting of create payloads, for idempotent-create comparison.

A client retrying a create is under no obligation to reproduce byte-identical JSON — a
different library version may reorder keys, change whitespace, or re-serialise the amount
``"150.00"`` as the JSON number ``150.00``. All of those are the same request, and telling
that client 409 "you reused this key for a different request" invites the one response that
must never happen: minting a fresh key and paying out twice.

So the fingerprint is taken over the *validated* payload, not the raw body. Validation is
what normalises the noise — DRF coerces and quantizes the amount to a canonical Decimal,
unknown fields never reach the output — and hashing its result compares what the request
means rather than how it happened to be serialised. ``sort_keys`` removes the last
non-semantic variation, key order.

``default=str`` exists for exactly one input: validated data carries ``Decimal`` amounts,
which ``json.dumps`` cannot serialise natively, and ``str(Decimal)`` is deterministic once
DRF has quantized it. Nothing else unexpected should reach this function — it is only ever
fed serializer output.

That tolerance is specific to idempotency. It must NOT be borrowed for anything
cryptographic: a webhook signature is an HMAC over the exact bytes the sender signed, and
canonicalising before verifying means verifying something other than what was sent.
"""

import hashlib
import json


def canonical_fingerprint(payload) -> str:
    """Return the SHA-256 hex digest of ``payload`` in canonical JSON form."""
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
