from rest_framework import serializers

from .models import Transfer


class TransferSerializer(serializers.ModelSerializer):
    """Read shape for every response that returns a transfer.

    ``amount`` goes out as a string (DRF's default for decimals), deliberately: a JSON
    number invites the consumer to parse it as a float, and a float is where money
    precision goes to die. The internal pk and the idempotency bookkeeping stay internal;
    ``reference`` is the public handle.
    """

    class Meta:
        model = Transfer
        fields = [
            "reference",
            "amount",
            "currency",
            "recipient_ref",
            "status",
            "provider_transfer_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TransferCreateSerializer(serializers.ModelSerializer):
    """Validation for the create payload — where the money rules are enforced for the API.

    The rules themselves are declared once, on the model, and DRF derives the serializer
    field from that declaration: ``max_digits``/``decimal_places`` are copied across, and
    the model's ``MinValueValidator`` becomes the field's ``min_value``. No hand-copied
    numbers here to drift out of step with the schema.

    The serializer still matters, because model validators only run on ``full_clean()``,
    which the ORM does not call on save — this is the layer that actually rejects:

    - zero and negative amounts (a payout of nothing is a bug in the caller),
    - more than two decimal places (a 400, not a silent round — rounding ``1.234`` would
      mean the customer and our ledger disagree by a fraction nobody chose),
    - unsupported currencies, as a clear 400 naming the field.

    Status, reference, provider id and the idempotency columns are deliberately absent —
    and unknown fields are *rejected*, not silently dropped. DRF's default is to ignore
    them, which on a money API is a quiet lie: a client posting ``"status": "completed"``
    would get a 201 and believe it created a completed transfer. Refusing loudly tells the
    caller their mental model of the API is wrong before their ledger disagrees with ours.
    """

    class Meta:
        model = Transfer
        fields = ["amount", "currency", "recipient_ref"]

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {field: "Unknown field." for field in sorted(unknown)}
            )
        return attrs
