"""Minting of externally visible identifiers.

One recipe for every public id, so the entropy decision lives in one place. 16 hex chars
is 64 bits: both columns that store these are unique, so a collision surfaces as an
``IntegrityError`` — a 500 on the one path that must never half-fail — and at 64 bits the
birthday probability across a million rows is ~10⁻⁸, versus ~0.2% for the 12-char version
this replaces.

Never derived from the primary key: a sequential id in an external reference leaks how
many rows exist and lets anyone walk the table by counting.
"""

import uuid


def prefixed_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"
