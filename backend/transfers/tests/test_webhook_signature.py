import json

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from transfers.models import WebhookEvent
from transfers.states import TransferStatus
from transfers.tests.factories import make_transfer
from transfers.tests.helpers import (
    WEBHOOK_TEST_SECRET,
    post_webhook,
)


def event_payload(provider_transfer_id, **overrides):
    payload = {
        "event_id": "evt_0001",
        "provider_transfer_id": provider_transfer_id,
        "status": "completed",
        "occurred_at": "2026-08-10T12:00:00Z",
    }
    return {**payload, **overrides}


@override_settings(PROVIDER_WEBHOOK_SECRET=WEBHOOK_TEST_SECRET)
class WebhookSignatureTests(APITestCase):
    """Authentication of the webhook. Every failure is the same 401 with the same body —
    telling a caller *which* check failed is free information for a prober — and nothing
    about the payload is processed or stored until the signature passes."""

    def setUp(self):
        self.transfer = make_transfer(
            status=TransferStatus.PROCESSING,
            provider_transfer_id="prov_" + "c" * 16,
        )

    def test_missing_signature_header_returns_401(self):
        response = post_webhook(
            self.client,
            event_payload(self.transfer.provider_transfer_id),
            header="",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # Nothing was processed: no event stored, no state change.
        self.assertEqual(WebhookEvent.objects.count(), 0)
        self.transfer.refresh_from_db()
        self.assertEqual(self.transfer.status, TransferStatus.PROCESSING)

    def test_signature_binds_to_the_bytes_sent_not_to_our_canonical_form(self):
        # A real provider signs whatever their serialiser produced — their key order,
        # their whitespace. If verification re-canonicalised the parsed payload it would
        # be checking bytes the provider never sent, and every provider whose JSON
        # spelling differs from ours would be stuck in a permanent 401.
        payload = event_payload(self.transfer.provider_transfer_id)
        body = json.dumps(payload, indent=2).encode("utf-8")  # pretty-printed, unsorted

        response = post_webhook(self.client, payload, body=body)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.transfer.refresh_from_db()
        self.assertEqual(self.transfer.status, TransferStatus.COMPLETED)

    def test_malformed_signature_header_returns_401(self):
        # The last two digests are undecodable (non-hex, non-ASCII) — they must produce
        # the same 401 as any wrong signature, not a 500 the provider retries forever.
        for header in (
            "sha256=",
            "md5=abc123",
            "abc123",
            "sha256",
            "sha256=zz" + "0" * 62,
            "sha256=é" + "0" * 63,
        ):
            with self.subTest(header=header):
                response = post_webhook(
                    self.client,
                    event_payload(self.transfer.provider_transfer_id),
                    header=header,
                )
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_signature_from_wrong_secret_returns_401(self):
        response = post_webhook(
            self.client,
            event_payload(self.transfer.provider_transfer_id),
            secret="not-the-shared-secret",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_valid_signature_is_accepted(self):
        response = post_webhook(
            self.client, event_payload(self.transfer.provider_transfer_id)
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_signature_check_runs_before_transfer_lookup(self):
        # An unsigned caller probing a guessed provider id must get the same 401 as any
        # other signature failure — a 404 here would make the endpoint an oracle for
        # which provider ids exist.
        response = post_webhook(
            self.client,
            event_payload("prov_" + "f" * 16),  # matches nothing
            header="sha256=" + "0" * 64,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(WebhookEvent.objects.count(), 0)
