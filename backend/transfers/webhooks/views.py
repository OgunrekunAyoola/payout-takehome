from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import services
from ..models import WebhookEventOutcome
from .serializers import ProviderWebhookSerializer
from .signature import verify_signature

SIGNATURE_HEADER = "X-Provider-Signature"


class ProviderWebhookView(APIView):
    """``POST /api/webhooks/provider/`` — the provider tells us how a transfer ended.

    A DRF view on purpose: the shared exception handler (api_errors.py) only fires inside
    DRF dispatch, and this endpoint depends on it to turn state-machine refusals into
    409s — an unhandled refusal would be a 500, and 500s are what providers retry
    forever.

    Order of checks is load-bearing:

    1. **Signature.** Nothing looks at the payload until the caller has proven they hold
       the shared secret; otherwise 404-vs-401 differences make this endpoint an oracle
       for which provider ids exist. Every signature failure returns the same 401 body —
       distinguishing "malformed header" from "wrong digest" is free information for a
       prober, so the distinction is logged server-side instead.
    2. **Shape validation.** 400s for missing fields or a status we have no mapping for.
    3. **Apply**, via the service layer: dedupe by event id, match by provider id,
       transition under the state machine. Refusals surface as 404/409 with the event
       recorded first.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        header = request.headers.get(SIGNATURE_HEADER, "")
        if not verify_signature(
            request.data, header, settings.PROVIDER_WEBHOOK_SECRET
        ):
            return Response(
                {"detail": "Invalid or missing webhook signature."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = ProviderWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        event, redelivered = services.apply_webhook_event(
            event_id=data["event_id"],
            provider_transfer_id=data["provider_transfer_id"],
            target_status=data["status"],
            occurred_at=data["occurred_at"],
            payload=request.data,
        )

        if redelivered and event.outcome == WebhookEventOutcome.APPLIED:
            detail = "Event already applied; no change."
        else:
            detail = "Event applied."
        return Response(
            {"detail": detail, "event_id": event.event_id, "outcome": event.outcome},
            status=status.HTTP_200_OK,
        )
