"""The fake payout provider.

In the real system this is an HTTP client for the provider's API and the id comes back in
their response. Here, submitting just mints an id in their format. It is kept behind a
function so the seam where a real client would go is already in place — and so tests and
the webhook simulator agree on what a provider id looks like.
"""

import uuid


def submit_to_provider(transfer) -> str:
    """'Submit' the transfer to the provider and return their id for it."""
    return f"prov_{uuid.uuid4().hex[:12]}"
