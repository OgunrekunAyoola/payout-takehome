"""Operations that move transfers, shared by every caller.

Views own request/response shape; this module owns orchestration — what happens around a
state change, and in what order. "How to submit a transfer" exists exactly once here, so
the ordering that matters cannot drift between the HTTP action, a future management
command, or anything else that needs it. The provider webhook's apply-event logic joins
this module when it lands.
"""

from .exceptions import IllegalTransition
from .models import Transfer
from .provider import submit_to_provider
from .states import TransferStatus, can_transition


def submit_transfer(transfer: Transfer) -> Transfer:
    """Submit a pending transfer to the provider: ``pending`` → ``processing``.

    The ordering is the point:

    1. **Ask the transition table first.** The provider must not learn about a transfer
       whose move would be refused — call-then-check turns a double-clicked submit into a
       second real payout instruction that the 409 then throws away, unreconcilable
       because no row anywhere holds its id. This consults the same single table the
       write enforces; it is not a second copy of the rules.
    2. Then the provider call.
    3. Then the compare-and-swap write, which attaches the provider id in the same UPDATE
       that moves the status — no moment where a transfer is ``processing`` with nothing
       for a webhook to match on.

    A window remains between 1 and 3: a concurrent cancel can win the race after the
    provider was called, and the CAS then refuses our write. With the mock provider that
    costs nothing; with a real one it is still an orphaned instruction. The genuine fix
    is an idempotent provider API keyed on our reference (every retry names the same
    payout, so nothing orphans) — noted in the README, out of scope for the mock.
    """
    if not can_transition(transfer.status, TransferStatus.PROCESSING):
        raise IllegalTransition(transfer.status, TransferStatus.PROCESSING)
    provider_id = submit_to_provider(transfer)
    transfer.transition_to(
        TransferStatus.PROCESSING, provider_transfer_id=provider_id
    )
    return transfer


def cancel_transfer(transfer: Transfer) -> Transfer:
    """Cancel a transfer that has not been submitted: ``pending`` → ``cancelled``.

    Only possible before submission — once the provider has it we cannot unilaterally
    withdraw it (brief scenario E). No pre-check needed: nothing external is contacted,
    so the transition table's own refusal is the whole story.
    """
    transfer.transition_to(TransferStatus.CANCELLED)
    return transfer
