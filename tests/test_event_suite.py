import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from copy import deepcopy

from PySide6.QtWidgets import QApplication

from core.event_models import AgentEvent, VALID_STATUSES
from core.event_manager import EventManager
from interface.live_monitor import LiveMonitor


class EventModelTests(unittest.TestCase):

    def test_create_valid_event(self):
        event = AgentEvent.create(
            category="chat",
            event_type="request_started",
            message="Solicita??o iniciada.",
            status="running",
            source="chat_panel",
            task_id="task-001",
        )

        self.assertEqual(event.category, "chat")
        self.assertEqual(event.status, "running")
        self.assertEqual(event.task_id, "task-001")
        self.assertTrue(event.event_id)
        self.assertTrue(event.timestamp)

    def test_all_valid_statuses_are_accepted(self):
        for status in VALID_STATUSES:
            with self.subTest(status=status):
                event = AgentEvent.create(
                    category="test",
                    event_type="status_test",
                    message="Teste",
                    status=status,
                )
                self.assertEqual(event.status, status)

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError):
            AgentEvent.create(
                category="test",
                event_type="invalid",
                message="Teste",
                status="unknown",
            )

    def test_required_text_fields_are_validated(self):
        for field in ("category", "event_type", "message", "source"):
            values = {
                "category": "test",
                "event_type": "test",
                "message": "test",
                "source": "test",
            }
            values[field] = "  "

            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    AgentEvent.create(**values)

    def test_details_are_deep_copied(self):
        original = {
            "file": "main.c",
            "nested": {"value": 10},
        }

        event = AgentEvent.create(
            category="test",
            event_type="copy_test",
            message="Teste",
            details=original,
        )

        original["nested"]["value"] = 99

        self.assertEqual(event.details["nested"]["value"], 10)

        exported = event.to_dict()
        exported["details"]["nested"]["value"] = 50

        self.assertEqual(event.details["nested"]["value"], 10)


class EventManagerTests(unittest.TestCase):

    def setUp(self):
        self.manager = EventManager(max_history=3)

    def test_publish_returns_event(self):
        event = self.manager.publish(
            category="test",
            event_type="published",
            message="Evento publicado.",
            status="success",
        )

        self.assertIsInstance(event, AgentEvent)
        self.assertEqual(self.manager.count(), 1)

    def test_publish_emits_signals(self):
        published = []
        history_changes = []

        self.manager.event_published.connect(
            lambda event: published.append(event)
        )

        self.manager.history_changed.connect(
            lambda: history_changes.append(True)
        )

        self.manager.publish(
            category="test",
            event_type="signal_test",
            message="Teste de sinal.",
        )

        self.assertEqual(len(published), 1)
        self.assertEqual(len(history_changes), 1)

    def test_history_preserves_order(self):
        for index in range(3):
            self.manager.publish(
                category="test",
                event_type="ordered",
                message=f"Evento {index}",
            )

        history = self.manager.history()

        self.assertEqual(len(history), 3)
        self.assertEqual(
            [event.message for event in history],
            ["Evento 0", "Evento 1", "Evento 2"],
        )

    def test_history_limit_is_respected(self):
        for index in range(5):
            self.manager.publish(
                category="test",
                event_type="limit",
                message=f"Evento {index}",
            )

        self.assertEqual(self.manager.count(), 3)

        history = self.manager.history()

        self.assertEqual(
            [event.message for event in history],
            ["Evento 2", "Evento 3", "Evento 4"],
        )

    def test_history_limit_argument(self):
        for index in range(3):
            self.manager.publish(
                category="test",
                event_type="limit",
                message=f"Evento {index}",
            )

        self.assertEqual(len(self.manager.history(limit=2)), 2)
        self.assertEqual(len(self.manager.history(limit=0)), 0)

        with self.assertRaises(ValueError):
            self.manager.history(limit=-1)

    def test_history_is_independent_copy(self):
        self.manager.publish(
            category="test",
            event_type="copy",
            message="Teste",
            details={"nested": {"value": 10}},
        )

        history = self.manager.history()
        history[0].details["nested"]["value"] = 99

        self.assertEqual(
            self.manager.history()[0].details["nested"]["value"],
            10,
        )

    def test_clear_history(self):
        self.manager.publish(
            category="test",
            event_type="clear",
            message="Teste",
        )

        changes = []
        self.manager.history_changed.connect(
            lambda: changes.append(True)
        )

        self.manager.clear_history()

        self.assertEqual(self.manager.count(), 0)
        self.assertEqual(len(self.manager.history()), 0)
        self.assertEqual(len(changes), 1)

    def test_invalid_max_history(self):
        with self.assertRaises(ValueError):
            EventManager(max_history=0)


class LiveMonitorTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager = EventManager(max_history=2)
        self.monitor = LiveMonitor(self.manager)

    def tearDown(self):
        self.monitor.close()
        self.monitor.deleteLater()
        self.app.processEvents()

    def test_monitor_receives_new_event(self):
        self.manager.publish(
            category="code_review",
            event_type="analysis_started",
            message="An?lise iniciada.",
            status="running",
        )

        self.app.processEvents()

        self.assertEqual(self.monitor.table.rowCount(), 1)
        self.assertIn(
            "1 evento",
            self.monitor.event_count_label.text(),
        )

    def test_monitor_respects_history_limit(self):
        for index in range(3):
            self.manager.publish(
                category="test",
                event_type="limit",
                message=f"Evento {index}",
            )

        self.app.processEvents()

        self.assertEqual(self.monitor.table.rowCount(), 2)
        self.assertEqual(len(self.monitor._events), 2)

        first_item = self.monitor.table.item(0, 4)
        self.assertEqual(first_item.text(), "Evento 1")

    def test_monitor_clears_history(self):
        self.manager.publish(
            category="test",
            event_type="clear",
            message="Teste",
        )

        self.app.processEvents()
        self.manager.clear_history()
        self.app.processEvents()

        self.assertEqual(self.monitor.table.rowCount(), 0)
        self.assertEqual(len(self.monitor._events), 0)
        self.assertIn("0 eventos", self.monitor.event_count_label.text())

    def test_monitor_displays_event_details(self):
        self.manager.publish(
            category="test",
            event_type="details",
            message="Detalhes de teste",
            task_id="task-123",
            details={"file": "main.c"},
        )

        self.app.processEvents()
        self.monitor.table.selectRow(0)
        self.app.processEvents()

        details = self.monitor.details.toPlainText()

        self.assertIn("task-123", details)
        self.assertIn("main.c", details)


if __name__ == "__main__":
    unittest.main(verbosity=2)
