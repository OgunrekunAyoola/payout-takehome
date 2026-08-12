from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from transfers.states import TransferStatus
from transfers.tests.factories import make_transfer


def submit_url(reference: str) -> str:
    return reverse("transfer-submit", args=[reference])


def cancel_url(reference: str) -> str:
    return reverse("transfer-cancel", args=[reference])


class SubmitTests(APITestCase):
    def test_submit_moves_pending_to_processing_and_assigns_provider_id(self):
        transfer = make_transfer()

        response = self.client.post(submit_url(transfer.reference))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["status"], TransferStatus.PROCESSING)
        self.assertRegex(body["provider_transfer_id"], r"^prov_[0-9a-f]{12}$")
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.PROCESSING)
        self.assertEqual(transfer.provider_transfer_id, body["provider_transfer_id"])

    def test_submit_twice_returns_409_and_keeps_the_first_provider_id(self):
        transfer = make_transfer()
        first = self.client.post(submit_url(transfer.reference))

        second = self.client.post(submit_url(transfer.reference))

        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        body = second.json()
        self.assertEqual(body["current_status"], TransferStatus.PROCESSING)
        self.assertEqual(body["attempted_status"], TransferStatus.PROCESSING)
        # A refused re-submit must not have minted a new provider id — that would break
        # the link the first submit created, and webhooks match on it.
        transfer.refresh_from_db()
        self.assertEqual(
            transfer.provider_transfer_id, first.json()["provider_transfer_id"]
        )

    def test_submit_cancelled_transfer_is_rejected_409(self):
        transfer = make_transfer()
        transfer.transition_to(TransferStatus.CANCELLED)

        response = self.client.post(submit_url(transfer.reference))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.CANCELLED)
        self.assertIsNone(transfer.provider_transfer_id)

    def test_submit_unknown_reference_is_404(self):
        response = self.client.post(submit_url("TRF-000000000000"))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CancelTests(APITestCase):
    def test_cancel_pending_succeeds(self):
        transfer = make_transfer()

        response = self.client.post(cancel_url(transfer.reference))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], TransferStatus.CANCELLED)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.CANCELLED)
        self.assertTrue(transfer.is_terminal)

    def test_scenario_e_cancel_after_submit_is_rejected_409(self):
        # Brief scenario E: once the provider has the transfer we cannot unilaterally
        # withdraw it. The refusal comes from the transition table, not a view check —
        # processing simply has no edge to cancelled.
        transfer = make_transfer()
        self.client.post(submit_url(transfer.reference))

        response = self.client.post(cancel_url(transfer.reference))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        body = response.json()
        self.assertEqual(body["current_status"], TransferStatus.PROCESSING)
        self.assertEqual(body["attempted_status"], TransferStatus.CANCELLED)
        # Still processing, still holding its provider id: the failed cancel changed
        # nothing, and the provider's eventual webhook can still land.
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.PROCESSING)
        self.assertIsNotNone(transfer.provider_transfer_id)

    def test_cancel_completed_transfer_is_rejected_409(self):
        transfer = make_transfer()
        transfer.transition_to(
            TransferStatus.PROCESSING, provider_transfer_id="prov_done"
        )
        transfer.transition_to(TransferStatus.COMPLETED)

        response = self.client.post(cancel_url(transfer.reference))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.COMPLETED)

    def test_cancel_twice_returns_409(self):
        # Terminal states are immutable — including to the action that made them
        # terminal. A second cancel is not "already done, fine": the caller believes
        # cancelling is possible, and correcting that belief is the useful response.
        transfer = make_transfer()
        self.client.post(cancel_url(transfer.reference))

        response = self.client.post(cancel_url(transfer.reference))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_cancel_unknown_reference_is_404(self):
        response = self.client.post(cancel_url("TRF-000000000000"))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
