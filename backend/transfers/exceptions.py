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
