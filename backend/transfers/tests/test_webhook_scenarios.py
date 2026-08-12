from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from transfers.models import WebhookEvent, WebhookEventOutcome
from transfers.states import TransferStatus
from transfers.tests.factories import make_transfer
from transfers.tests.helpers import WEBHOOK_TEST_SECRET, post_webhook

PROVIDER_ID = "prov_" + "c" * 16


def event_payload(**overrides):
    payload = {
        "event_id": "evt_0001",
        "provider_transfer_id": PROVIDER_ID,
        "status": "completed",
        "occurred_at": "2026-08-10T12:00:00Z",
    }
    return {**payload, **overrides}


@override_settings(PROVIDER_WEBHOOK_SECRET=WEBHOOK_TEST_SECRET)
class WebhookHappyPathTests(APITestCase):
    def test_webhook_completes_processing_transfer(self):
        transfer = make_transfer(
            status=TransferStatus.PROCESSING, provider_transfer_id=PROVIDER_ID
        )

        response = post_webhook(self.client, event_payload())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["outcome"], WebhookEventOutcome.APPLIED)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.COMPLETED)
        event = WebhookEvent.objects.get()
        self.assertEqual(event.outcome, WebhookEventOutcome.APPLIED)
        self.assertEqual(event.transfer, transfer)
        self.assertEqual(event.payload["event_id"], "evt_0001")

    def test_webhook_fails_processing_transfer(self):
        transfer = make_transfer(
            status=TransferStatus.PROCESSING, provider_transfer_id=PROVIDER_ID
        )

        response = post_webhook(self.client, event_payload(status="failed"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.FAILED)

    def test_unknown_payload_fields_are_tolerated(self):
        # The opposite rule to the create API, on purpose: the provider owns this
        # contract, and them shipping a harmless new field must not take payouts down.
        make_transfer(status=TransferStatus.PROCESSING, provider_transfer_id=PROVIDER_ID)

        response = post_webhook(
            self.client, event_payload(retry_count=3, region="eu-west-1")
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unmapped_status_is_a_400_before_the_state_machine(self):
        make_transfer(status=TransferStatus.PROCESSING, provider_transfer_id=PROVIDER_ID)

        response = post_webhook(self.client, event_payload(status="reversed"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", response.json())
        self.assertEqual(WebhookEvent.objects.count(), 0)


@override_settings(PROVIDER_WEBHOOK_SECRET=WEBHOOK_TEST_SECRET)
class WebhookScenarioTests(APITestCase):
    """Scenarios A–D from the brief, one test each, named for their letter."""

    def test_scenario_a_same_event_id_delivered_twice_is_a_noop_200(self):
        # Event-level dedupe: the second delivery returns success and changes nothing.
        # Exactly one event row exists — the unique constraint refused the second insert.
        transfer = make_transfer(
            status=TransferStatus.PROCESSING, provider_transfer_id=PROVIDER_ID
        )

        first = post_webhook(self.client, event_payload())
        second = post_webhook(self.client, event_payload())

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertIn("already applied", second.json()["detail"])
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.COMPLETED)
        self.assertEqual(WebhookEvent.objects.count(), 1)

    def test_scenario_b_failed_after_completed_is_rejected_409(self):
        # A contradiction after a terminal state is not noise: our books say the money
        # landed, the provider now says it didn't, and exactly one of those is true.
        # 409 puts the disagreement in both parties' error metrics, and the stored
        # rejected event is what the human who reconciles it starts from.
        transfer = make_transfer(
            status=TransferStatus.PROCESSING, provider_transfer_id=PROVIDER_ID
        )
        post_webhook(self.client, event_payload(event_id="evt_done"))

        response = post_webhook(
            self.client, event_payload(event_id="evt_contradiction", status="failed")
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.COMPLETED)
        rejected = WebhookEvent.objects.get(event_id="evt_contradiction")
        self.assertEqual(
            rejected.outcome, WebhookEventOutcome.REJECTED_ILLEGAL_TRANSITION
        )
        self.assertEqual(rejected.transfer, transfer)

    def test_scenario_c_webhook_for_still_pending_transfer_is_rejected_409(self):
        # The reachable version of scenario C: the transfer HAS a provider id but is
        # still pending (a submit that assigned the id and died before committing, or a
        # provider webhook outrunning our submit response). pending → completed has no
        # edge, so the state machine refuses; the event is kept for redelivery, which
        # will be judged against fresh state (see the redelivery test below).
        transfer = make_transfer(provider_transfer_id=PROVIDER_ID)  # pending

        response = post_webhook(self.client, event_payload())

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.PENDING)
        event = WebhookEvent.objects.get()
        self.assertEqual(event.outcome, WebhookEventOutcome.REJECTED_ILLEGAL_TRANSITION)

    def test_scenario_c_webhook_for_never_submitted_transfer_is_404(self):
        # The literal version of scenario C: a transfer that was never submitted has no
        # provider_transfer_id at all, so lookup cannot match it — the case collapses
        # into "unknown provider id" and gets the same loud 404.
        make_transfer()  # pending, provider_transfer_id=None

        response = post_webhook(self.client, event_payload())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        event = WebhookEvent.objects.get()
        self.assertEqual(event.outcome, WebhookEventOutcome.REJECTED_UNKNOWN_TRANSFER)
        self.assertIsNone(event.transfer)

    def test_scenario_d_two_events_both_completed_second_is_rejected_409(self):
        # Distinct from A: the second event is genuinely new, so event-level dedupe is
        # silent. It is the state machine that refuses — completed → completed has no
        # edge. Two different defences for two different problems: the unique constraint
        # guards against the transport delivering one thing twice, the transition table
        # against the provider asserting something incompatible twice.
        transfer = make_transfer(
            status=TransferStatus.PROCESSING, provider_transfer_id=PROVIDER_ID
        )
        post_webhook(self.client, event_payload(event_id="evt_first"))

        response = post_webhook(self.client, event_payload(event_id="evt_second"))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.COMPLETED)
        self.assertEqual(
            WebhookEvent.objects.get(event_id="evt_second").outcome,
            WebhookEventOutcome.REJECTED_ILLEGAL_TRANSITION,
        )

    def test_unknown_provider_transfer_id_is_404_and_the_event_is_kept(self):
        # The signature already proved this is our provider, so an unmatchable id is a
        # real integration mismatch — wrong environment, a lost write, their success
        # against our failure. A soft 200 would end their retries and erase the only
        # evidence; the 404 keeps the disagreement alive and the stored event is the
        # dead letter an investigation starts from.
        response = post_webhook(self.client, event_payload())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        event = WebhookEvent.objects.get()
        self.assertEqual(event.outcome, WebhookEventOutcome.REJECTED_UNKNOWN_TRANSFER)

    def test_reused_event_id_with_different_content_is_rejected_409(self):
        # An event_id names one immutable fact. Reusing it for a different claim —
        # another transfer, the opposite outcome — must not be judged as if it were a
        # redelivery: judging would route the incoming claim by the stored event's
        # provider id, silently applying something no single event ever asserted. Here
        # that would mean 404-ing against the stored id and leaving `other` stuck in
        # processing with its real event swallowed.
        transfer = make_transfer(
            status=TransferStatus.PROCESSING, provider_transfer_id=PROVIDER_ID
        )
        other = make_transfer(
            status=TransferStatus.PROCESSING,
            provider_transfer_id="prov_" + "d" * 16,
        )
        post_webhook(self.client, event_payload())  # evt_0001 applied to `transfer`

        response = post_webhook(
            self.client,
            event_payload(
                provider_transfer_id=other.provider_transfer_id, status="failed"
            ),
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["event_id"], "evt_0001")
        # Neither transfer moved, and the stored event still records the original claim.
        other.refresh_from_db()
        self.assertEqual(other.status, TransferStatus.PROCESSING)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.COMPLETED)
        event = WebhookEvent.objects.get()
        self.assertEqual(event.outcome, WebhookEventOutcome.APPLIED)
        self.assertEqual(event.payload["provider_transfer_id"], PROVIDER_ID)
        self.assertEqual(event.payload["status"], "completed")

    def test_rejected_event_is_re_evaluated_on_redelivery(self):
        # The asymmetry that keeps transfers from sticking: a duplicate of an APPLIED
        # event must be a no-op (scenario A), but a duplicate of a REJECTED event is
        # judged again — its rejection may have been a function of timing. Here the
        # event arrives before any matching transfer exists (404, recorded), the
        # transfer then comes into being, and the provider's retry of the SAME event_id
        # must land, or the transfer sits in processing forever.
        first = post_webhook(self.client, event_payload())
        self.assertEqual(first.status_code, status.HTTP_404_NOT_FOUND)

        transfer = make_transfer(
            status=TransferStatus.PROCESSING, provider_transfer_id=PROVIDER_ID
        )
        retry = post_webhook(self.client, event_payload())

        self.assertEqual(retry.status_code, status.HTTP_200_OK)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.COMPLETED)
        event = WebhookEvent.objects.get()  # still one row: same event_id
        self.assertEqual(event.outcome, WebhookEventOutcome.APPLIED)
        self.assertEqual(event.transfer, transfer)
