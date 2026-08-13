import json

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from transfers.models import Transfer
from transfers.states import TransferStatus
from transfers.tests.factories import make_transfer

PAYLOAD = {"amount": "150.00", "currency": "NGN", "recipient_ref": "acct-778"}


def create_url() -> str:
    return reverse("transfer-list")


def detail_url(reference: str) -> str:
    return reverse("transfer-detail", args=[reference])


class CreateTransferTests(APITestCase):
    def create(self, payload=PAYLOAD, key="key-1", content_type=None):
        """POST to the create endpoint.

        ``payload`` may be a dict (sent as JSON) or a pre-serialised string with
        ``content_type``, for tests that need to control the exact bytes on the wire.
        """
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
        if isinstance(payload, str):
            return self.client.post(
                create_url(), payload, content_type=content_type, **headers
            )
        return self.client.post(create_url(), payload, format="json", **headers)

    def test_create_returns_201_and_pending_status(self):
        response = self.create()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["status"], TransferStatus.PENDING)
        self.assertEqual(body["amount"], "150.00")
        self.assertEqual(body["currency"], "NGN")
        self.assertRegex(body["reference"], r"^TRF-[0-9a-f]{12}$")
        self.assertIsNone(body["provider_transfer_id"])
        # The idempotency machinery is internal; the response shape should not leak it.
        self.assertNotIn("idempotency_key", body)
        self.assertNotIn("request_fingerprint", body)
        self.assertNotIn("id", body)

    def test_create_requires_idempotency_key_header(self):
        missing = self.create(key=None)
        blank = self.create(key="   ")

        for response in (missing, blank):
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("Idempotency-Key", response.json()["detail"])
        self.assertEqual(Transfer.objects.count(), 0)

    def test_overlong_idempotency_key_is_a_400_not_a_500(self):
        # The key reaches the database via serializer.save(**kwargs), which bypasses
        # field validation. Unchecked, an over-long key is stored silently on SQLite and
        # raises DataError (not IntegrityError) on Postgres — a 500 the client retries.
        response = self.create(key="k" * 129)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("128", response.json()["detail"])
        self.assertEqual(Transfer.objects.count(), 0)

    def test_same_key_same_body_replays_original_transfer_200(self):
        first = self.create()
        second = self.create()

        # 200, not 201: nothing was created the second time, and the codes should say so.
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(Transfer.objects.count(), 1)

    def test_same_key_different_body_returns_409(self):
        self.create()
        response = self.create(payload={**PAYLOAD, "amount": "999.00"})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        # The original transfer is untouched — a key collision must never mutate what the
        # key originally created.
        transfer = Transfer.objects.get()
        self.assertEqual(str(transfer.amount), "150.00")

    def test_same_key_reordered_body_is_treated_as_same_request(self):
        # A retrying client is under no obligation to reproduce byte-identical JSON.
        # Same fields, different key order and spacing: semantically the same request,
        # so it must replay, not 409.
        self.create()
        reordered = json.dumps(
            {"recipient_ref": "acct-778", "currency": "NGN", "amount": "150.00"},
            indent=2,
        )
        response = self.create(payload=reordered, content_type="application/json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Transfer.objects.count(), 1)

    def test_same_key_amount_as_json_number_is_treated_as_same_request(self):
        # The retry's JSON library re-serialises the string "150.00" as the number 150.0.
        # The fingerprint is taken over *validated* data, which quantizes both spellings
        # to the same Decimal — so this replays. Fingerprinting the raw body would 409
        # here, and the 409's advice to mint a new key would be an instruction to pay
        # out twice.
        self.create()
        response = self.create(
            payload='{"amount": 150.0, "currency": "NGN", "recipient_ref": "acct-778"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Transfer.objects.count(), 1)

    def test_rejects_zero_and_negative_amounts(self):
        for amount in ("0.00", "-25.00"):
            with self.subTest(amount=amount):
                response = self.create(
                    payload={**PAYLOAD, "amount": amount}, key=f"key-{amount}"
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("amount", response.json())
        self.assertEqual(Transfer.objects.count(), 0)

    def test_rejects_amount_with_more_than_two_decimal_places(self):
        # 1.234 is a 400, not silently rounded: rounding would mean the customer and our
        # ledger disagree by a fraction nobody chose.
        response = self.create(payload={**PAYLOAD, "amount": "1.234"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("amount", response.json())
        self.assertEqual(Transfer.objects.count(), 0)

    def test_rejects_unsupported_currency(self):
        response = self.create(payload={**PAYLOAD, "currency": "EUR"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("currency", response.json())

    def test_rejects_missing_recipient_ref(self):
        payload = {k: v for k, v in PAYLOAD.items() if k != "recipient_ref"}
        response = self.create(payload=payload)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("recipient_ref", response.json())

    def test_unknown_fields_are_rejected_not_silently_ignored(self):
        # DRF's default is to drop unknown fields, which on a money API is a quiet lie:
        # a client posting status=completed would get a 201 and believe it created a
        # completed transfer.
        response = self.create(payload={**PAYLOAD, "status": "completed"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", response.json())
        self.assertEqual(Transfer.objects.count(), 0)

    def test_validation_failure_does_not_burn_the_idempotency_key(self):
        # A 400 must not consume the key: the client's natural next step is to fix the
        # payload and retry with the same key, and that retry has to be allowed to create.
        bad = self.create(payload={**PAYLOAD, "amount": "0.00"})
        good = self.create()

        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(good.status_code, status.HTTP_201_CREATED)


class ReadTransferTests(APITestCase):
    """List and retrieve, built on the factory so read coverage does not depend on the
    write path — a create regression should fail create tests, not these."""

    def test_list_returns_newest_first_paginated(self):
        transfers = [make_transfer(recipient_ref=f"acct-{i}") for i in range(3)]

        response = self.client.get(create_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["count"], 3)
        self.assertEqual(
            [t["reference"] for t in body["results"]],
            [t.reference for t in reversed(transfers)],
        )

    def test_retrieve_by_public_reference(self):
        transfer = make_transfer()

        response = self.client.get(detail_url(transfer.reference))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["reference"], transfer.reference)
        self.assertEqual(body["status"], TransferStatus.PENDING)

    def test_unknown_reference_is_404(self):
        response = self.client.get(detail_url("TRF-000000000000"))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
