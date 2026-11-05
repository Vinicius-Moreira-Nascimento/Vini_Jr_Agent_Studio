import threading
import unittest

from autonomy.correction_engine import (
    CorrectionEngine,
    CorrectionEngineState,
)


VALID_PLAN = {
    "summary": "Plano de teste",
    "findings": [],
    "actions": [],
    "risks": [],
}


class FakePlanningService:

    def __init__(self, result=None, error=None):
        self.result = result or {
            "analysis": {"files_analyzed": 1},
            "planning_input": {"inventory": []},
            "plan": VALID_PLAN,
        }
        self.error = error
        self.calls = 0

    def analyze_and_plan(self, objective):
        self.calls += 1

        if self.error:
            raise self.error

        return self.result


class FakeEventManager:

    def __init__(self):
        self.events = []

    def publish(self, **kwargs):
        self.events.append(kwargs)


class CorrectionEngineTests(unittest.TestCase):

    def setUp(self):
        self.service = FakePlanningService()
        self.events = FakeEventManager()

        self.engine = CorrectionEngine(
            planning_service=self.service,
            event_manager=self.events,
        )

    def test_valid_plan_completes_successfully(self):
        result = self.engine.analyze_and_plan("Analisar firmware")

        self.assertEqual(result.status, "completed")
        self.assertTrue(result.task_id)
        self.assertEqual(result.plan["summary"], "Plano de teste")
        self.assertEqual(
            self.engine.state,
            CorrectionEngineState.COMPLETED,
        )

    def test_invalid_plan_is_rejected(self):
        self.service.result["plan"] = {
            "summary": "Plano incompleto",
            "findings": [],
            "actions": [],
        }

        with self.assertRaises(ValueError):
            self.engine.analyze_and_plan("Analisar firmware")

        self.assertEqual(
            self.engine.state,
            CorrectionEngineState.FAILED,
        )

    def test_planning_service_error_is_propagated(self):
        self.service.error = RuntimeError("Falha simulada")

        with self.assertRaisesRegex(RuntimeError, "Falha simulada"):
            self.engine.analyze_and_plan("Analisar firmware")

        self.assertEqual(
            self.engine.state,
            CorrectionEngineState.FAILED,
        )

    def test_events_are_published(self):
        self.engine.analyze_and_plan("Analisar firmware")

        event_types = [
            event["event_type"]
            for event in self.events.events
        ]

        self.assertIn("correction_analysis_started", event_types)
        self.assertIn("correction_plan_ready", event_types)

    def test_empty_objective_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.analyze_and_plan("   ")

        self.assertEqual(self.service.calls, 0)
        self.assertEqual(len(self.events.events), 0)

    def test_concurrent_execution_is_blocked(self):
        entered = threading.Event()
        release = threading.Event()
        errors = []

        class BlockingService:

            def analyze_and_plan(self, objective):
                entered.set()

                if not release.wait(timeout=10):
                    raise TimeoutError("Timeout no teste.")

                return {
                    "analysis": {"files_analyzed": 1},
                    "planning_input": {"inventory": []},
                    "plan": VALID_PLAN,
                }

        engine = CorrectionEngine(
            planning_service=BlockingService()
        )

        def first_execution():
            try:
                engine.analyze_and_plan("Primeira execucao")
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=first_execution)
        worker.start()

        try:
            self.assertTrue(
                entered.wait(timeout=5),
                "Primeira execucao nao iniciou.",
            )

            with self.assertRaises(RuntimeError):
                engine.analyze_and_plan("Segunda execucao")

        finally:
            release.set()
            worker.join(timeout=10)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(
            engine.state,
            CorrectionEngineState.COMPLETED,
        )


if __name__ == "__main__":
    unittest.main()
