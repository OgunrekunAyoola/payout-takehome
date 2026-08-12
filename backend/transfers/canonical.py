"""Canonical fingerprinting of request payloads, for idempotent-create comparison.

A client retrying a create is under no obligation to reproduce byte-identical JSON — a
different library version, a re-serialised dict, a proxy that reformats, and the bytes
change while the request means exactly the same thing. What idempotency needs to know is
"is this semantically the same request as the one that already succeeded", so the payload
is serialised with sorted keys and no insignificant whitespace before hashing, and two
bodies that differ only in key order or spacing produce the same fingerprint.

That property is specific to idempotency. It must NOT be borrowed for anything
cryptographic: a webhook signature, for instance, is an HMAC over the exact bytes the
sender signed, and canonicalising before verifying means verifying something other than
what was sent.
"""

import hashlib
import json


def canonical_fingerprint(payload) -> str:
    """Return the SHA-256 hex digest of ``payload`` in canonical JSON form."""
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
