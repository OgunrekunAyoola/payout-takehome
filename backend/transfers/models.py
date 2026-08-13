from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from .exceptions import ConcurrentTransition, IllegalTransition
from .ids import prefixed_id
from .states import TransferStatus, can_transition, is_terminal

# The shape of a public reference, owned here so tests and consumers assert against the
# declaration instead of restating it.
REFERENCE_PATTERN = r"^TRF-[0-9a-f]{16}$"


class Currency(models.TextChoices):
    NGN = "NGN", "Nigerian Naira"
    GBP = "GBP", "Pound Sterling"
    USD = "USD", "US Dollar"


def generate_reference() -> str:
    """Build a public transfer reference, e.g. ``TRF-3f9a2b7c1d04a8e2``.

    Deliberately not the primary key — see ``ids.prefixed_id`` for both that reasoning
    and the entropy choice. The auto primary key still exists and is still what foreign
    keys point at; it just is not the public handle.
    """
    return prefixed_id("TRF-")


class Transfer(models.Model):
    reference = models.CharField(
        max_length=20, unique=True, default=generate_reference, editable=False
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
        indexes = [
            # Backs the list endpoint's newest-first ordering. Without it every list is
            # a full scan plus a sort, and pagination alone doesn't help — a LIMIT still
            # pays for sorting the whole table first.
            models.Index(fields=["-created_at", "-id"], name="transfer_newest_first"),
        ]
        constraints = [
            # "No provider id" must be NULL and never the empty string. The column is
            # unique, so one blank row would be tolerated and the second would fail on the
            # unique constraint instead of on the thing that was actually wrong.
            models.CheckConstraint(
                condition=~models.Q(provider_transfer_id=""),
                name="provider_transfer_id_is_null_or_non_empty",
            ),
            # The serializer enforces this for the API, but the serializer is not the
            # only writer — factories, shells, management commands and future services
            # all reach the ORM directly, and none of them run field validators. For an
            # invariant of the money domain, the database is the one altitude nothing
            # can bypass.
            models.CheckConstraint(
                condition=models.Q(amount__gte=Decimal("0.01")),
                name="amount_at_least_one_minor_unit",
            ),
        ]

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

        The write is a compare-and-swap: the UPDATE only matches while the stored status is
        still the one we validated against, and no rows matched means somebody moved this
        transfer first. Checking in Python and then writing unconditionally would let two
        requests holding stale copies both pass the check and both write, and the second
        would silently win — a cancel landing on top of a submit would leave a cancelled
        transfer holding a live provider id, which is unrecoverable because cancelled is
        terminal and the provider's webhook could never correct it.

        Doing this as a conditional UPDATE rather than a row lock is deliberate: it is
        correct on SQLite too, where ``select_for_update`` is a no-op.
        """
        if not can_transition(self.status, new_status):
            raise IllegalTransition(self.status, new_status)

        expected_status = self.status
        now = timezone.now()
        # .update() bypasses save(), so auto_now does not fire and updated_at is set here.
        rows_matched = (
            type(self)
            ._default_manager.filter(pk=self.pk, status=expected_status)
            .update(status=new_status, updated_at=now, **fields)
        )
        if rows_matched == 0:
            # order_by() strips Meta.ordering — a dead ORDER BY on a pk probe. The
            # instance is deliberately NOT retargeted to `actual`: its other fields are
            # just as stale as its status, and silently half-updating it would hide
            # that. The exception carries what the caller needs to re-read.
            actual = (
                type(self)
                ._default_manager.order_by()
                .filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )
            raise ConcurrentTransition(expected_status, new_status, actual)

        self.status = new_status
        self.updated_at = now
        for name, value in fields.items():
            setattr(self, name, value)


class WebhookEventOutcome(models.TextChoices):
    # The row is inserted with RECEIVED *before* it is judged — insert-first is what makes
    # dedupe atomic — so a crash between insert and verdict leaves a visibly unjudged row
    # that redelivery will re-evaluate. There is deliberately no DUPLICATE outcome: a
    # duplicate delivery never gets a row (the unique constraint refuses it), so
    # "duplicate" is a property of a delivery, not of the stored event.
    RECEIVED = "received", "Received, not yet judged"
    APPLIED = "applied", "Applied"
    REJECTED_ILLEGAL_TRANSITION = (
        "rejected_illegal_transition",
        "Rejected: illegal transition",
    )
    REJECTED_UNKNOWN_TRANSFER = "rejected_unknown_transfer", "Rejected: unknown transfer"


class WebhookEvent(models.Model):
    """Every authenticated provider event we have seen, and what we did with it.

    Two jobs. First, dedupe: ``event_id`` is unique, and handling an event *begins* by
    trying to insert this row — an ``IntegrityError`` means we have seen it. The obvious
    alternative, check-then-insert, has a race a duplicate-happy provider will find: two
    deliveries of one event arrive together, both pass the check, both apply. Only the
    database can make that decision atomic.

    Second, audit: rejections are recorded, not just successes. The interesting events —
    contradictions after a terminal state, orphans with no matching transfer, arrivals
    before our submit committed — are exactly what someone reconciling a discrepancy
    needs, and storing only the happy path would erase them. The stored ``outcome`` is
    also what lets redelivery be handled asymmetrically: a duplicate of an *applied*
    event must be a no-op (its side effects already happened), while a duplicate of a
    *rejected* event is re-evaluated against current state — the rejection may have been
    a function of timing, and replaying it forever would strand the transfer.
    """

    event_id = models.CharField(max_length=128, unique=True)
    provider_transfer_id = models.CharField(max_length=64, db_index=True)
    # The full payload as received (post-signature, post-parse), so an investigation has
    # the evidence and not just our verdict on it.
    payload = models.JSONField()
    outcome = models.CharField(
        max_length=32,
        choices=WebhookEventOutcome.choices,
        default=WebhookEventOutcome.RECEIVED,
    )
    transfer = models.ForeignKey(
        Transfer,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="webhook_events",
    )
    occurred_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at", "-id"]

    def __str__(self) -> str:
        return f"{self.event_id} → {self.outcome}"
