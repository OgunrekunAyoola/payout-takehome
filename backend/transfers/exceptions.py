class IllegalTransition(Exception):
    """Raised when a status change is not permitted by the transition table.

    It carries both statuses so the HTTP layer can turn it into a 409 whose message names
    the actual move that was refused. The brief is explicit that invalid transitions must
    return a clear 4xx rather than being silently ignored, and a caller can only act on
    that if the error says what it rejected.
    """

    def __init__(self, current: str, attempted: str) -> None:
        self.current = current
        self.attempted = attempted
        super().__init__(f"A transfer in '{current}' cannot move to '{attempted}'.")


class ConcurrentTransition(Exception):
    """Raised when a transfer was moved by someone else between our read and our write.

    Distinct from ``IllegalTransition``: the move we attempted was legal for the status we
    had read, and the reason it failed is that our copy of the transfer was already stale.
    The caller's correct response is to re-read and decide again, not to conclude the
    transition is forbidden — so the two cases are worth telling apart even though both
    end up as a 409.
    """

    def __init__(self, expected: str, attempted: str, actual: str) -> None:
        self.expected = expected
        self.attempted = attempted
        self.actual = actual
        super().__init__(
            f"Transfer was modified concurrently: expected it to still be "
            f"'{expected}' when moving to '{attempted}', but it is now '{actual}'."
        )
