import uuid
from decimal import Decimal

from transfers.models import Currency, Transfer


def make_transfer(**overrides) -> Transfer:
    """Create a Transfer directly, bypassing the API.

    The state machine lives on the model, not in a view, so it should be testable without
    an HTTP layer — and at this point in the build there is not one to go through. The
    idempotency key is randomised because the column is unique and most tests do not care
    what it contains.
    """
    defaults = {
        "amount": Decimal("100.00"),
        "currency": Currency.NGN,
        "recipient_ref": "recipient-0001",
        "idempotency_key": f"key-{uuid.uuid4().hex}",
        "request_fingerprint": "0" * 64,
    }
    return Transfer.objects.create(**{**defaults, **overrides})
