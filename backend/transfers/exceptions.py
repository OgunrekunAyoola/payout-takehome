class TransferConflict(Exception):
    """Base for every refusal to change a transfer's state.

    Carries the transfer's current status and the attempted target under one pair of
    names, so the HTTP layer renders a single 409 envelope for every kind of conflict —
    submit, cancel and the provider webhook all speak it. Subclasses differ in the advice
    their message carries, not in shape.
    """

    def __init__(self, current, attempted: str, message: str) -> None:
        self.current = current
        self.attempted = attempted
        super().__init__(message)


class IllegalTransition(TransferConflict):
    """The request itself asks for a forbidden move.

    Retrying it unchanged will fail forever; the caller should stop. The brief is explicit
    that invalid transitions must return a clear 4xx rather than being silently ignored,
    and a caller can only act on that if the error names the move it rejected.
    """

    def __init__(self, current: str, attempted: str) -> None:
        super().__init__(
            current,
            attempted,
            f"A transfer in '{current}' cannot move to '{attempted}'.",
        )


class ConcurrentTransition(TransferConflict):
    """The transfer was moved by someone else between our read and our write.

    Distinct from ``IllegalTransition``: the move we attempted was legal for the status we
    had read, and the reason it failed is that our copy was stale. The caller's correct
    response is to re-read and decide again, not to conclude the action is forbidden —
    same status code, opposite advice.

    ``current`` is the status the row holds *now* (``None`` if the row is gone entirely),
    ``expected`` the stale status the caller validated against.
    """

    def __init__(self, expected: str, attempted: str, actual) -> None:
        self.expected = expected
        self.actual = actual
        if actual is None:
            message = (
                f"Transfer was modified concurrently: expected it to still be "
                f"'{expected}' when moving to '{attempted}', but it no longer exists."
            )
        else:
            message = (
                f"Transfer was modified concurrently: expected it to still be "
                f"'{expected}' when moving to '{attempted}', but it is now '{actual}'."
            )
        super().__init__(actual, attempted, message)


class WebhookEventMismatch(Exception):
    """A delivery reused an event_id but carried different content.

    An event_id names one immutable fact; a redelivery is byte-for-byte the same claim,
    retried. A delivery that reuses the id while asserting a different transfer or a
    different outcome is not a redelivery — it contradicts the recorded event, and
    honouring either half silently would corrupt whichever one was true. Refused as a
    409 naming the event, never re-judged: re-judging would apply the *incoming* claim
    under the *stored* event's identity, and the audit trail would attribute a move to
    an event that never asserted it.
    """

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(
            f"event_id '{event_id}' was already used by an event with different "
            "content. Redeliveries must repeat the original event unchanged."
        )
