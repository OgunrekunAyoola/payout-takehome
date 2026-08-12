import json

from rest_framework import status
from rest_framework.test import APITestCase

from transfers.models import Transfer
from transfers.states import TransferStatus

CREATE_URL = "/api/transfers/"

PAYLOAD = {"amount": "150.00", "currency": "NGN", "recipient_ref": "acct-778"}


class CreateTransferTests(APITestCase):
    def create(self, payload=PAYLOAD, key="key-1", **extra):
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
        return self.client.post(CREATE_URL, payload, format="json", **headers, **extra)

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
        response = self.create(key=None)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Idempotency-Key", response.json()["detail"])
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
        response = self.client.post(
            CREATE_URL,
            reordered,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="key-1",
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

    def test_validation_failure_does_not_burn_the_idempotency_key(self):
        # A 400 must not consume the key: the client's natural next step is to fix the
        # payload and retry with the same key, and that retry has to be allowed to create.
        bad = self.create(payload={**PAYLOAD, "amount": "0.00"})
        good = self.create()

        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(good.status_code, status.HTTP_201_CREATED)


class ReadTransferTests(APITestCase):
    def test_list_returns_newest_first(self):
        refs = []
        for i in range(3):
            response = self.client.post(
                CREATE_URL,
                {**PAYLOAD, "recipient_ref": f"acct-{i}"},
                format="json",
                HTTP_IDEMPOTENCY_KEY=f"key-{i}",
            )
            refs.append(response.json()["reference"])

        listed = self.client.get(CREATE_URL).json()

        self.assertEqual([t["reference"] for t in listed], list(reversed(refs)))

    def test_retrieve_by_public_reference(self):
        created = self.client.post(
            CREATE_URL, PAYLOAD, format="json", HTTP_IDEMPOTENCY_KEY="key-1"
        ).json()

        response = self.client.get(f"{CREATE_URL}{created['reference']}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), created)

    def test_unknown_reference_is_404(self):
        response = self.client.get(f"{CREATE_URL}TRF-000000000000/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
