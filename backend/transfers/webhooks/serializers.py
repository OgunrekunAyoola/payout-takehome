from rest_framework import serializers

from ..states import TransferStatus


class ProviderWebhookSerializer(serializers.Serializer):
    """The provider's event contract.

    ``status`` is restricted to the two things a provider can tell us — ``completed`` or
    ``failed`` — so an invented status (``reversed``) is a 400 naming the field before
    the state machine is ever consulted. The machine remains the backstop: even if a new
    status were added here, a move the table doesn't permit is still refused.

    Unknown fields are *tolerated* here, the opposite of the create serializer's rule,
    and deliberately so: we own the create contract, but the provider owns this one, and
    providers add fields to their payloads over time. A webhook handler that 400s the day
    the provider ships a harmless ``retry_count`` field takes payouts down for nothing.
    """

    event_id = serializers.CharField(max_length=128)
    provider_transfer_id = serializers.CharField(max_length=64)
    status = serializers.ChoiceField(
        choices=[TransferStatus.COMPLETED.value, TransferStatus.FAILED.value]
    )
    occurred_at = serializers.DateTimeField()
