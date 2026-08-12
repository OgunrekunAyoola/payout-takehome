from decimal import Decimal

from rest_framework import serializers

from .models import Transfer


class TransferSerializer(serializers.ModelSerializer):
    """Read shape for every response that returns a transfer.

    ``amount`` goes out as a string (DRF's default for decimals), deliberately: a JSON
    number invites the consumer to parse it as a float, and a float is where money
    precision goes to die. The internal pk stays internal; ``reference`` is the public
    handle.
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
    """Validation for the create payload — and the enforcement of the money rules.

    The model documents these constraints, but model validators only run on
    ``full_clean()``, which the ORM does not call on save. This serializer is where the
    API's guarantee actually lives:

    - ``min_value`` rejects zero and negative amounts — a payout of nothing is a bug in
      the caller, not a transfer.
    - ``decimal_places=2`` makes over-precise amounts a 400 rather than silently rounding.
      Rounding ``1.234`` would mean the customer and our ledger disagree by a fraction
      nobody chose; for money, refusing to guess is the feature.
    - ``currency`` is validated against the model's choices, so an unsupported code is a
      clear 400 naming the field.

    Status, reference, provider id and the idempotency columns are deliberately absent:
    a client cannot create a transfer in any state but ``pending``, and the idempotency
    fields are set by the view from the request context, not by the payload.
    """

    amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, min_value=Decimal("0.01")
    )

    class Meta:
        model = Transfer
        fields = ["amount", "currency", "recipient_ref"]
