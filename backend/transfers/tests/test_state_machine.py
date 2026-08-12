from django.test import SimpleTestCase, TestCase

from transfers.exceptions import ConcurrentTransition, IllegalTransition
from transfers.models import Transfer
from transfers.states import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    TransferStatus,
    can_transition,
    is_terminal,
)
from transfers.tests.factories import make_transfer


class TransitionTableTests(SimpleTestCase):
    """The rules themselves, asserted against the table with no database involved."""

    def test_pending_may_move_to_processing_or_cancelled(self):
        self.assertEqual(
            ALLOWED_TRANSITIONS[TransferStatus.PENDING],
            frozenset({TransferStatus.PROCESSING, TransferStatus.CANCELLED}),
        )
        self.assertTrue(
            can_transition(TransferStatus.PENDING, TransferStatus.PROCESSING)
        )
        self.assertTrue(
            can_transition(TransferStatus.PENDING, TransferStatus.CANCELLED)
        )
        self.assertFalse(
            can_transition(TransferStatus.PENDING, TransferStatus.COMPLETED)
        )
        self.assertFalse(can_transition(TransferStatus.PENDING, TransferStatus.FAILED))

    def test_processing_may_move_to_completed_or_failed(self):
        self.assertEqual(
            ALLOWED_TRANSITIONS[TransferStatus.PROCESSING],
            frozenset({TransferStatus.COMPLETED, TransferStatus.FAILED}),
        )
        # Cancellation is only available before submission, which is the whole point of
        # scenario E in the brief: once the provider has it, we cannot unilaterally
        # withdraw it.
        self.assertFalse(
            can_transition(TransferStatus.PROCESSING, TransferStatus.CANCELLED)
        )

    def test_terminal_states_have_no_outgoing_transitions(self):
        # TERMINAL_STATUSES is derived from the table rather than written down, so this
        # pins the derivation to the three statuses the brief calls terminal. If someone
        # gives `completed` an outgoing edge, this fails rather than silently permitting
        # a completed transfer to change.
        self.assertEqual(
            TERMINAL_STATUSES,
            frozenset(
                {
                    TransferStatus.COMPLETED,
                    TransferStatus.FAILED,
                    TransferStatus.CANCELLED,
                }
            ),
        )
        for status in TERMINAL_STATUSES:
            with self.subTest(status=status):
                self.assertTrue(is_terminal(status))
                self.assertEqual(ALLOWED_TRANSITIONS[status], frozenset())

    def test_every_status_appears_in_the_transition_table(self):
        # Adding a status to the enum without adding a row here would otherwise be a
        # KeyError discovered at runtime, on whichever request happened to hit it first.
        self.assertEqual(set(ALLOWED_TRANSITIONS), set(TransferStatus))

    def test_unknown_target_status_is_an_illegal_transition_not_a_crash(self):
        # A provider inventing a status we have no mapping for ("reversed") must surface
        # as the same refusal as any other forbidden move, so the webhook layer can turn
        # it into a 4xx. An unhandled ValueError would become a 500, and a 500 is what
        # providers retry forever.
        with self.assertRaises(IllegalTransition):
            can_transition(TransferStatus.PENDING, "refunded")

    def test_unknown_current_status_is_rejected_rather_than_treated_as_terminal(self):
        # A corrupt stored status is different: nothing legitimate can produce it, so it
        # should be loud. The dangerous failure mode is a typo behaving like a terminal
        # state — every transition out of it refused, the transfer stuck, and no error
        # pointing at the cause.
        with self.assertRaises(ValueError):
            is_terminal("refunded")
        with self.assertRaises(ValueError):
            can_transition("refunded", TransferStatus.PROCESSING)


class TransferTransitionTests(TestCase):
    """The model method that is the only sanctioned way to change a status."""

    def test_new_transfer_is_pending_with_a_public_reference(self):
        transfer = make_transfer()

        self.assertEqual(transfer.status, TransferStatus.PENDING)
        # TRF- followed by 12 hex chars, i.e. random — not derived from the primary key,
        # which would leak row counts and make references guessable by counting.
        self.assertRegex(transfer.reference, r"^TRF-[0-9a-f]{12}$")
        self.assertIsNone(transfer.provider_transfer_id)
        self.assertFalse(transfer.is_terminal)

    def test_transition_to_persists_the_new_status(self):
        transfer = make_transfer()

        transfer.transition_to(TransferStatus.PROCESSING)

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.PROCESSING)

    def test_transition_to_sets_related_fields_in_the_same_write(self):
        # Submitting has to record the provider id at the same moment the status becomes
        # `processing`. Two separate writes would leave a window where the transfer is
        # processing with no provider id, and a webhook arriving in that window would find
        # nothing to match on.
        transfer = make_transfer()

        transfer.transition_to(
            TransferStatus.PROCESSING, provider_transfer_id="prov_abc123"
        )

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.PROCESSING)
        self.assertEqual(transfer.provider_transfer_id, "prov_abc123")

    def test_illegal_transition_raises_and_leaves_the_stored_status_unchanged(self):
        transfer = make_transfer()

        with self.assertRaises(IllegalTransition) as ctx:
            transfer.transition_to(TransferStatus.COMPLETED)

        # The exception names both ends of the refused move, because the HTTP layer turns
        # it into a 409 and a caller can only act on an error that says what it rejected.
        self.assertEqual(ctx.exception.current, TransferStatus.PENDING)
        self.assertEqual(ctx.exception.attempted, TransferStatus.COMPLETED)
        # Unchanged in memory as well as in the database: the check runs before any
        # assignment, so a caught exception does not leave a half-mutated object behind.
        self.assertEqual(transfer.status, TransferStatus.PENDING)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.PENDING)

    def test_terminal_transfer_cannot_be_moved_again(self):
        transfer = make_transfer()
        transfer.transition_to(TransferStatus.PROCESSING)
        transfer.transition_to(TransferStatus.COMPLETED)

        self.assertTrue(transfer.is_terminal)
        for attempted in TransferStatus:
            with self.subTest(attempted=attempted):
                with self.assertRaises(IllegalTransition):
                    transfer.transition_to(attempted)

    def test_cancelled_transfer_cannot_be_submitted(self):
        transfer = make_transfer()
        transfer.transition_to(TransferStatus.CANCELLED)

        with self.assertRaises(IllegalTransition):
            transfer.transition_to(TransferStatus.PROCESSING)

    def test_stale_instance_cannot_overwrite_a_concurrent_transition(self):
        # Two copies of the same pending transfer, as two racing requests would hold.
        # The first submits it; the second still believes it is pending and tries to
        # cancel — legal for the status it read, but stale. The write must fail, because
        # letting it through would leave a cancelled transfer holding a live provider id,
        # and cancelled is terminal so no webhook could ever correct it.
        ours = make_transfer()
        theirs = Transfer.objects.get(pk=ours.pk)

        theirs.transition_to(
            TransferStatus.PROCESSING, provider_transfer_id="prov_first"
        )

        with self.assertRaises(ConcurrentTransition) as ctx:
            ours.transition_to(TransferStatus.CANCELLED)

        self.assertEqual(ctx.exception.expected, TransferStatus.PENDING)
        self.assertEqual(ctx.exception.actual, TransferStatus.PROCESSING)
        # The stored row kept the first writer's result.
        ours.refresh_from_db()
        self.assertEqual(ours.status, TransferStatus.PROCESSING)
        self.assertEqual(ours.provider_transfer_id, "prov_first")
