"""The fake payout provider.

In the real system this is an HTTP client for the provider's API and the id comes back in
their response. Here, submitting mints an id in their format behind the same seam, so the
place where a real client goes is already in place and everything else — tests, the
webhook simulator — agrees on what a provider id looks like via ``PROVIDER_ID_PATTERN``.

Two things the mock deliberately cannot express, both listed in the README's limitations:
it never fails, so no test can exercise "provider accepted, our write failed"; and it has
no vocabulary for the ambiguous timeout (provider accepted but the response was lost),
which is the dominant real-world failure and the reason a real integration wants an
idempotent submit keyed on our reference.

The ``transfer`` argument is unused by the mock but is the real seam's signature: an
actual submission sends the amount, currency and recipient reference.
"""

from .ids import prefixed_id

PROVIDER_ID_PATTERN = r"^prov_[0-9a-f]{16}$"


def submit_to_provider(transfer) -> str:
    """'Submit' the transfer to the provider and return their id for it."""
    return prefixed_id("prov_")
