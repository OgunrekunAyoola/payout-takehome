from unittest import mock

from rest_framework import status
from rest_framework.test import APITestCase

from transfers.provider import PROVIDER_ID_PATTERN
from transfers.states import TransferStatus
from transfers.tests.factories import make_transfer
from transfers.tests.helpers import UNKNOWN_REFERENCE, cancel_url, submit_url


class SubmitTests(APITestCase):
    def test_submit_moves_pending_to_processing_and_assigns_provider_id(self):
        transfer = make_transfer()

        response = self.client.post(submit_url(transfer.reference))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["status"], TransferStatus.PROCESSING)
        self.assertRegex(body["provider_transfer_id"], PROVIDER_ID_PATTERN)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.PROCESSING)
        self.assertEqual(transfer.provider_transfer_id, body["provider_transfer_id"])

    def test_submit_twice_returns_409_and_never_contacts_the_provider_again(self):
        # The DB column staying unchanged is not enough to assert here: with a real
        # provider client, "call then let the state machine refuse" would instruct a
        # second payout whose id no row ever records. The seam's call count is the
        # invariant that matters.
        transfer = make_transfer()
        with mock.patch(
            "transfers.services.submit_to_provider", return_value="prov_" + "a" * 16
        ) as provider:
            first = self.client.post(submit_url(transfer.reference))
            second = self.client.post(submit_url(transfer.reference))

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(provider.call_count, 1)
        body = second.json()
        self.assertEqual(body["current_status"], TransferStatus.PROCESSING)
        self.assertEqual(body["attempted_status"], TransferStatus.PROCESSING)
        # And the refused re-submit kept the first provider id — webhooks match on it.
        transfer.refresh_from_db()
        self.assertEqual(transfer.provider_transfer_id, "prov_" + "a" * 16)

    def test_submit_cancelled_transfer_is_rejected_without_contacting_provider(self):
        transfer = make_transfer()
        transfer.transition_to(TransferStatus.CANCELLED)

        with mock.patch("transfers.services.submit_to_provider") as provider:
            response = self.client.post(submit_url(transfer.reference))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        provider.assert_not_called()
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.CANCELLED)
        self.assertIsNone(transfer.provider_transfer_id)

    def test_submit_unknown_reference_is_404(self):
        response = self.client.post(submit_url(UNKNOWN_REFERENCE))

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
        # Factory override rather than walking the machine: this is setup, not the
        # behaviour under test, and it shouldn't break when submission's mechanics change.
        transfer = make_transfer(
            status=TransferStatus.COMPLETED, provider_transfer_id="prov_" + "b" * 16
        )

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
        response = self.client.post(cancel_url(UNKNOWN_REFERENCE))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
