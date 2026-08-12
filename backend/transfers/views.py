from django.db import IntegrityError, transaction
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from .canonical import canonical_fingerprint
from .models import Transfer
from .serializers import TransferCreateSerializer, TransferSerializer

IDEMPOTENCY_HEADER = "Idempotency-Key"


class TransferViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create, list and retrieve transfers.

    Lookup is by public reference (``/api/transfers/TRF-.../``), never by primary key.
    Listing is newest-first via the model's default ordering.
    """

    queryset = Transfer.objects.all()
    serializer_class = TransferSerializer
    lookup_field = "reference"

    def create(self, request, *args, **kwargs):
        """Create a transfer, idempotently.

        The contract, in order:

        - No ``Idempotency-Key`` header → 400. The header is how a client that never saw
          our response can safely retry; making it optional would make double-charging an
          opt-out.
        - Known key, same payload (by canonical fingerprint, so key order and whitespace
          don't matter) → 200 with the original transfer. 200 rather than 201 because
          nothing was created — a replay is a *success* whose effect already happened.
        - Known key, different payload → 409. The client is reusing a key for a different
          request; honouring either interpretation silently would be wrong, so refuse
          loudly and let the caller mint a new key.
        - New key → validate, create, 201.

        The existence check runs first because replays are the common retry path, but it
        cannot be the only defence: two identical creates racing both find nothing, and
        both insert. The unique constraint on ``idempotency_key`` breaks that tie, and the
        loser catches ``IntegrityError`` and serves the winner's row — same outcome as if
        it had arrived second.
        """
        key = request.headers.get(IDEMPOTENCY_HEADER)
        if not key:
            return Response(
                {"detail": f"The {IDEMPOTENCY_HEADER} header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fingerprint = canonical_fingerprint(request.data)
        existing = Transfer.objects.filter(idempotency_key=key).first()

        if existing is None:
            serializer = TransferCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                # atomic() so the failed INSERT is rolled back cleanly and the
                # connection is usable for the lookup that follows.
                with transaction.atomic():
                    transfer = serializer.save(
                        idempotency_key=key, request_fingerprint=fingerprint
                    )
            except IntegrityError:
                # Lost a race with an identical concurrent create. Fall through and
                # treat the winner's row exactly as if it had been found up front.
                existing = Transfer.objects.filter(idempotency_key=key).first()
                if existing is None:
                    # The IntegrityError was not the idempotency key after all —
                    # nothing sane to serve, so let it surface.
                    raise
            else:
                return Response(
                    TransferSerializer(transfer).data, status=status.HTTP_201_CREATED
                )

        if existing.request_fingerprint == fingerprint:
            return Response(TransferSerializer(existing).data, status=status.HTTP_200_OK)

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
