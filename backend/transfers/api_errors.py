"""One place where domain exceptions become HTTP responses.

The state machine raises ``TransferConflict`` subclasses without knowing or caring about
HTTP. This handler is the single mapping from those to a 409, so every endpoint that moves
a transfer — submit, cancel, and the provider webhook — refuses an illegal move with the
same envelope: ``{detail, current_status, attempted_status}``. Clients get one error
vocabulary to parse, and changing the envelope later is one edit.

The *advice* differs by subclass and travels in ``detail``: an ``IllegalTransition`` means
retrying unchanged will fail forever (stop); a ``ConcurrentTransition`` means the state
moved underneath the caller (re-read and decide again). Same code, opposite next steps —
a client that needs to distinguish them programmatically can compare ``current_status``
with ``attempted_status``.

The domain exceptions deliberately do not subclass DRF's ``APIException``: models.py must
stay ignorant of HTTP, or the domain layer grows a framework dependency for the privilege
of setting a status code. Note the handler only fires for exceptions raised inside DRF's
dispatch — anything that moves transfers must be a DRF view to inherit this mapping.
"""

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.views import set_rollback

from .exceptions import ConcurrentTransition, TransferConflict, WebhookEventMismatch

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    if isinstance(exc, WebhookEventMismatch):
        set_rollback()
        # Not client noise: the provider (the signature proved it is them) asserted two
        # different facts under one event id. That is an integration bug on one side or
        # the other, and it should be visible in logs before it is visible in a ledger.
        logger.warning("Webhook event reused with different content: %s", exc)
        return Response(
            {"detail": str(exc), "event_id": exc.event_id},
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, TransferConflict):
        # Mirror DRF's own handler: mark the transaction for rollback before returning,
        # so a refused request can never commit partial work if this view later runs
        # under ATOMIC_REQUESTS or an enclosing atomic() block.
        set_rollback()
        if isinstance(exc, ConcurrentTransition):
            # An IllegalTransition is client misuse and deserves silence, but a lost
            # race is a server-side concurrency signal: unlogged, a spike of them is
            # indistinguishable from ordinary 409 noise.
            logger.warning("Concurrent transition lost: %s", exc)
        return Response(
            {
                "detail": str(exc),
                "current_status": exc.current,
                "attempted_status": exc.attempted,
            },
            status=status.HTTP_409_CONFLICT,
        )
    return drf_exception_handler(exc, context)
