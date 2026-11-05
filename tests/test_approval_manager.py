import threading
import unittest
from unittest.mock import patch

from autonomy.approval_manager import ApprovalManager


class FakeEventManager:

    def __init__(self):
        self.events = []

    def publish(self, **kwargs):
        self.events.append(kwargs)


class ApprovalManagerTests(unittest.TestCase):

    def setUp(self):
        self.events = FakeEventManager()
        self.manager = ApprovalManager(
            event_manager=self.events,
            default_ttl_seconds=900,
        )

    def test_new_proposal_starts_pending(self):
        proposal_id = self.manager.request_approval({
            "file": "main.c",
            "replacement": "return 0;",
        })

        self.assertEqual(
            self.manager.get_status(proposal_id),
            "pending",
        )

    def test_explicit_approval_can_be_consumed_once(self):
        proposal = {
            "file": "main.c",
            "replacement": "return 0;",
        }

        proposal_id = self.manager.request_approval(proposal)
        self.assertTrue(self.manager.approve(proposal_id))

        result = self.manager.consume_approval(proposal_id)

        self.assertEqual(result, proposal)
        self.assertEqual(
            self.manager.get_status(proposal_id),
            "consumed",
        )

        with self.assertRaises(PermissionError):
            self.manager.consume_approval(proposal_id)

    def test_rejected_proposal_cannot_be_consumed(self):
        proposal_id = self.manager.request_approval({
            "file": "main.c",
        })

        self.assertTrue(self.manager.reject(proposal_id))

        self.assertEqual(
            self.manager.get_status(proposal_id),
            "rejected",
        )

        with self.assertRaises(PermissionError):
            self.manager.consume_approval(proposal_id)

    def test_expired_proposal_cannot_be_approved_or_consumed(self):
        clock = [100.0]

        with patch(
            "autonomy.approval_manager.monotonic",
            side_effect=lambda: clock[0],
        ):
            proposal_id = self.manager.request_approval(
                {"file": "main.c"},
                ttl_seconds=10,
            )

            clock[0] = 111.0

            self.assertEqual(
                self.manager.get_status(proposal_id),
                "expired",
            )

            with self.assertRaises(ValueError):
                self.manager.approve(proposal_id)

            with self.assertRaises(PermissionError):
                self.manager.consume_approval(proposal_id)

    def test_unknown_proposal_is_rejected(self):
        with self.assertRaises(KeyError):
            self.manager.approve("proposal-inexistente")

        with self.assertRaises(KeyError):
            self.manager.reject("proposal-inexistente")

        with self.assertRaises(KeyError):
            self.manager.consume_approval("proposal-inexistente")

    def test_proposal_is_deep_copied(self):
        proposal = {
            "file": "main.c",
            "metadata": {"line": 10},
        }

        proposal_id = self.manager.request_approval(proposal)

        proposal["metadata"]["line"] = 999

        self.manager.approve(proposal_id)
        result = self.manager.consume_approval(proposal_id)

        self.assertEqual(result["metadata"]["line"], 10)

        result["metadata"]["line"] = 500

        self.assertEqual(
            self.manager._records[proposal_id].proposal["metadata"]["line"],
            10,
        )

    def test_invalid_ttl_is_rejected(self):
        for ttl in (0, -1, float("inf"), float("nan"), True):
            with self.subTest(ttl=ttl):
                with self.assertRaises(ValueError):
                    self.manager.request_approval(
                        {"file": "main.c"},
                        ttl_seconds=ttl,
                    )

    def test_events_are_published(self):
        proposal_id = self.manager.request_approval({
            "file": "main.c",
        })

        self.manager.approve(proposal_id)
        self.manager.consume_approval(proposal_id)

        event_types = [
            event["event_type"]
            for event in self.events.events
        ]

        self.assertIn("approval_requested", event_types)
        self.assertIn("approval_granted", event_types)
        self.assertIn("approval_consumed", event_types)

    def test_concurrent_consumption_allows_only_one_consumer(self):
        proposal_id = self.manager.request_approval({
            "file": "main.c",
        })
        self.manager.approve(proposal_id)

        results = []
        errors = []
        lock = threading.Lock()

        def consume():
            try:
                result = self.manager.consume_approval(proposal_id)
                with lock:
                    results.append(result)
            except Exception as error:
                with lock:
                    errors.append(error)

        workers = [
            threading.Thread(target=consume),
            threading.Thread(target=consume),
        ]

        for worker in workers:
            worker.start()

        for worker in workers:
            worker.join(timeout=5)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], PermissionError)


if __name__ == "__main__":
    unittest.main()
