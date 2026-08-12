"""One place where domain exceptions become HTTP responses.

The state machine raises ``IllegalTransition`` and ``ConcurrentTransition`` without knowing
or caring about HTTP. This handler is the single mapping from those to status codes, so
every endpoint that moves a transfer — submit, cancel, and the provider webhook — refuses
an illegal move with the same shape of 409. Clients get one error vocabulary to parse, and
changing the envelope later is one edit, not a hunt through views.

Both map to 409, but the bodies deliberately differ:

- ``IllegalTransition`` means the request itself asks for a forbidden move. Retrying it
  unchanged will fail forever; the client should stop.
- ``ConcurrentTransition`` means the move was legal for the state the caller read, but
  someone else moved the transfer first. The right response is to re-read and decide
  again — so the body says the state changed, not that the action is forbidden.
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .exceptions import ConcurrentTransition, IllegalTransition


def api_exception_handler(exc, context):
    if isinstance(exc, IllegalTransition):
        return Response(
            {
                "detail": str(exc),
                "current_status": exc.current,
                "attempted_status": exc.attempted,
            },
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, ConcurrentTransition):
        return Response(
            {
                "detail": str(exc),
                "current_status": exc.actual,
                "attempted_status": exc.attempted,
            },
            status=status.HTTP_409_CONFLICT,
        )
    return drf_exception_handler(exc, context)
