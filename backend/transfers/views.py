from django.db import IntegrityError, transaction
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from .canonical import canonical_fingerprint
from .models import Transfer
from .serializers import TransferCreateSerializer, TransferSerializer

IDEMPOTENCY_HEADER = "Idempotency-Key"
# Mirrors Transfer.idempotency_key.max_length. Checked here because the value reaches the
# database via serializer.save(**kwargs), which bypasses field validation — on SQLite an
# over-long key would be stored silently, and on Postgres it would raise DataError, which
# is not IntegrityError and would surface as a 500 instead of a 400 naming the header.
IDEMPOTENCY_KEY_MAX_LENGTH = 128


class TransferViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create, list and retrieve transfers.

    Lookup is by public reference (``/api/transfers/TRF-.../``), never by primary key.
    Listing is newest-first and paginated. No ``CreateModelMixin``: ``create`` is defined
    below with idempotency semantics the mixin does not have, and the router maps POST to
    it by name.
    """

    queryset = Transfer.objects.all()
    serializer_class = TransferSerializer
    lookup_field = "reference"

    def get_serializer_class(self):
        # OPTIONS metadata, the browsable API's POST form and schema generators all ask
        # the view for its serializer. Routing them to the write shape on create keeps
        # introspection honest — otherwise the API advertises a POST with no writable
        # fields.
        if self.action == "create":
            return TransferCreateSerializer
        return TransferSerializer

    def create(self, request, *args, **kwargs):
        """Create a transfer, idempotently.

        The contract, in order:

        - Missing, blank or over-long ``Idempotency-Key`` header → 400. The header is how
          a client that never saw our response can safely retry; making it optional would
          make double-charging an opt-out. The key is stripped of surrounding whitespace
          so a proxy or SDK appending a space cannot turn one key into two.
        - Invalid payload → 400, and the key is NOT consumed: the client's natural next
          step is to fix the payload and retry with the same key, and that retry must be
          allowed to create.
        - Known key, same request → 200 with the original transfer. "Same" is judged on
          the *validated* payload, so key order, whitespace and JSON scalar spelling
          (``"150.00"`` vs ``150.00`` vs ``150``) do not matter — a retry that means the
          same thing must replay, because the 409's advice to use a new key is, for a
          semantically identical retry, an instruction to pay out twice.
        - Known key, different request → 409. Honouring either interpretation silently
          would be wrong; refuse loudly and let the caller mint a new key.
        - New key → create, 201.

        The existence check runs first because replays are the common retry path, but it
        cannot be the only defence: two identical creates racing both find nothing, and
        both insert. The unique constraint on ``idempotency_key`` breaks that tie, and the
        loser catches ``IntegrityError`` and serves the winner's row — same outcome as if
        it had arrived second.
        """
        key = (request.headers.get(IDEMPOTENCY_HEADER) or "").strip()
        if not key:
            return Response(
                {"detail": f"The {IDEMPOTENCY_HEADER} header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
            return Response(
                {
                    "detail": (
                        f"The {IDEMPOTENCY_HEADER} header must be at most "
                        f"{IDEMPOTENCY_KEY_MAX_LENGTH} characters."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validation before fingerprinting, always — including on the replay path. The
        # fingerprint is taken over validated data because validation is what normalises
        # the noise a retrying client may introduce (see canonical.py). A replay therefore
        # re-validates its payload; that is harmless for a genuine retry and turns
        # garbage-with-a-known-key into the 400 it deserves.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fingerprint = canonical_fingerprint(serializer.validated_data)

        # order_by() clears the model's newest-first Meta.ordering, which is dead weight
        # on a unique-column probe.
        existing = (
            Transfer.objects.order_by().filter(idempotency_key=key).first()
        )
        if existing is not None:
            return self._replay_or_conflict(existing, fingerprint)

        try:
            # atomic() so the failed INSERT is rolled back cleanly and the connection is
            # usable for the lookup that follows.
            with transaction.atomic():
                transfer = serializer.save(
                    idempotency_key=key, request_fingerprint=fingerprint
                )
        except IntegrityError:
            # Lost a race with an identical concurrent create. Serve the winner's row
            # exactly as if it had been found up front.
            existing = (
                Transfer.objects.order_by().filter(idempotency_key=key).first()
            )
            if existing is None:
                # The IntegrityError was not the idempotency key after all — nothing
                # sane to serve, so let it surface.
                raise
            return self._replay_or_conflict(existing, fingerprint)

        return Response(self._read_data(transfer), status=status.HTTP_201_CREATED)

    def _replay_or_conflict(self, existing: Transfer, fingerprint: str) -> Response:
        """200 with the original transfer for a genuine retry, 409 for a key reuse.

        200 rather than 201 because nothing was created — a replay is a success whose
        effect already happened, and a caller's retry loop can tell the two apart.
        """
        if existing.request_fingerprint == fingerprint:
            return Response(self._read_data(existing), status=status.HTTP_200_OK)
        return Response(
            {
                "detail": (
                    f"This {IDEMPOTENCY_HEADER} was already used for a different "
                    "request body. Retry the original request unchanged, or use a "
                    "new key for a new request."
                )
            },
            status=status.HTTP_409_CONFLICT,
        )

    def _read_data(self, transfer: Transfer) -> dict:
        return TransferSerializer(
            transfer, context=self.get_serializer_context()
        ).data
