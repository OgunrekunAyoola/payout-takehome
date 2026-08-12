"""Transfer lifecycle rules.

``ALLOWED_TRANSITIONS`` is the only place the legal status moves are declared. Two
independent paths change a transfer's status — an ops user calling ``/submit/`` or
``/cancel/``, and a provider webhook arriving asynchronously — and if each carried its own
idea of what was legal they would eventually disagree with each other. Keeping the table
here means a rule can only be wrong in one place.
"""

from django.db import models


class TransferStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


# Each status maps to the statuses it may legally move to. An empty set means terminal.
ALLOWED_TRANSITIONS = {
    TransferStatus.PENDING: frozenset(
        {TransferStatus.PROCESSING, TransferStatus.CANCELLED}
    ),
    TransferStatus.PROCESSING: frozenset(
        {TransferStatus.COMPLETED, TransferStatus.FAILED}
    ),
    TransferStatus.COMPLETED: frozenset(),
    TransferStatus.FAILED: frozenset(),
    TransferStatus.CANCELLED: frozenset(),
}


def can_transition(current: str, new: str) -> bool:
    """Return True if moving from ``current`` to ``new`` is legal.

    Both arguments are coerced through ``TransferStatus`` so an unrecognised status
    raises ``ValueError`` rather than quietly falling through and behaving like a
    terminal state.
    """
    return TransferStatus(new) in ALLOWED_TRANSITIONS[TransferStatus(current)]


def is_terminal(status: str) -> bool:
    """Return True if no further transitions are possible from ``status``.

    Derived from the transition table rather than kept as a separate ``TERMINAL``
    constant. Two declarations of the same fact drift apart the first time someone adds a
    status, and the drift would show up as a terminal transfer accepting an update.
    """
    return not ALLOWED_TRANSITIONS[TransferStatus(status)]


TERMINAL_STATUSES = frozenset(
    status for status in TransferStatus if is_terminal(status)
)
