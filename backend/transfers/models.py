import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from .exceptions import IllegalTransition
from .states import TransferStatus, can_transition, is_terminal


class Currency(models.TextChoices):
    NGN = "NGN", "Nigerian Naira"
    GBP = "GBP", "Pound Sterling"
    USD = "USD", "US Dollar"


def generate_reference() -> str:
    """Build a public transfer reference, e.g. ``TRF-3f9a2b7c1d04``.

    Deliberately not the primary key. A sequential integer in an externally visible
    reference tells anyone who sees one roughly how many transfers exist, and lets them
    walk the table by counting. The auto primary key still exists and is still what
    foreign keys point at; it just is not the public handle.
    """
    return f"TRF-{uuid.uuid4().hex[:12]}"


class Transfer(models.Model):
    reference = models.CharField(
        max_length=16, unique=True, default=generate_reference, editable=False
    )
    # Money is never a float. 18 digits with 2 decimal places covers every currency here
    # with room to spare, and the minimum of 0.01 makes "pay out nothing" impossible.
    #
    # Note that model validators only run on full_clean(), which the ORM does not call on
    # save(). This validator documents the rule and protects anything going through a
    # form; the guarantee that the *API* cannot create a zero-amount transfer comes from
    # the serializer, which arrives with the create endpoint.
    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(max_length=3, choices=Currency.choices)
    recipient_ref = models.CharField(max_length=128)
    status = models.CharField(
        max_length=16,
        choices=TransferStatus.choices,
        default=TransferStatus.PENDING,
        db_index=True,
    )
    # Null until the transfer is submitted. Unique because it is what inbound webhooks are
    # matched on — two transfers sharing one provider id would make that lookup ambiguous,
    # and the ambiguity would be resolved by whichever row happened to come back first.
    provider_transfer_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    # SHA-256 hex of the canonicalised create payload, used to tell a genuine retry apart
    # from a different request reusing the same key. Populated by the create endpoint.
    request_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Newest first, which is what the list endpoint wants. The id tiebreak keeps
        # ordering stable when two rows share a timestamp.
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.reference} {self.amount} {self.currency} ({self.status})"

    @property
    def is_terminal(self) -> bool:
        return is_terminal(self.status)

    def transition_to(self, new_status: str, **fields) -> None:
        """Move this transfer to ``new_status``, or raise ``IllegalTransition``.

        This is the only sanctioned way to change a transfer's status; nothing else should
        assign to ``self.status``. Both the ops endpoints and the provider webhook go
        through here, which is what stops the two paths developing different opinions
        about what is legal.

        ``fields`` lets a caller set related columns in the same write — submitting a
        transfer needs to record ``provider_transfer_id`` at the same moment it becomes
        ``processing``, and doing that in one UPDATE means there is no window in which a
        transfer is processing with no provider id attached.
        """
        if not can_transition(self.status, new_status):
            raise IllegalTransition(self.status, new_status)

        self.status = new_status
        for name, value in fields.items():
            setattr(self, name, value)
        self.save(update_fields=["status", "updated_at", *fields])
