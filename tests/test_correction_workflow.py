import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import unittest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from autonomy.correction_workflow import (
    CorrectionWorkflow,
    CorrectionWorkflowState,
)


class FakeCorrectionEngine:

    def __init__(self, result=None, error=None):
        self.result = result or {
            "task_id": "test-task",
            "status": "completed",
            "analysis": {"files_analyzed": 1},
            "planning_input": {"inventory": []},
            "plan": {
                "summary": "Plano simulado",
                "findings": [],
                "actions": [],
                "risks": [],
            },
        }
        self.error = error
        self.calls = 0

    def analyze_and_plan(self, objective):
        self.calls += 1

        if self.error:
            raise self.error

        return self.result


class BlockingCorrectionEngine:

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def analyze_and_plan(self, objective):
        self.entered.set()

        if not self.release.wait(timeout=5):
            raise TimeoutError("Timeout no teste.")

        return {
            "task_id": "blocking-task",
            "status": "completed",
            "analysis": {},
            "planning_input": {"inventory": []},
            "plan": {
                "summary": "Plano simulado",
                "findings": [],
                "actions": [],
                "risks": [],
            },
        }


class CorrectionWorkflowTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

        if cls.app is None:
            cls.app = QApplication([])

    def wait_for_signal(self, signal, timeout=5000, trigger=None):
        loop = QEventLoop()
        received = []

        def on_signal(*args):
            received.append(args)
            loop.quit()

        signal.connect(on_signal)
        QTimer.singleShot(timeout, loop.quit)

        if trigger is not None:
            trigger()

        loop.exec()
        signal.disconnect(on_signal)

        self.assertTrue(
            received,
            "O sinal esperado não foi recebido dentro do prazo.",
        )

        return received[0]

    def test_initial_state_is_idle(self):
        workflow = CorrectionWorkflow(FakeCorrectionEngine())

        self.assertEqual(
            workflow.state,
            CorrectionWorkflowState.IDLE,
        )
        self.assertFalse(workflow.is_running)
        self.assertIsNone(workflow.last_result)

    def test_successful_analysis_waits_for_approval(self):
        engine = FakeCorrectionEngine()
        workflow = CorrectionWorkflow(engine)

        result_holder = []

        workflow.plan_ready.connect(
            lambda result: result_holder.append(result)
        )

        workflow.start_analysis("Analisar firmware")

        self.wait_for_signal(workflow.plan_ready)

        self.assertEqual(
            workflow.state,
            CorrectionWorkflowState.AWAITING_APPROVAL,
        )
        self.assertEqual(engine.calls, 1)
        self.assertIsNotNone(workflow.last_result)
        self.assertEqual(len(result_holder), 1)

    def test_analysis_failure_changes_state(self):
        engine = FakeCorrectionEngine(
            error=RuntimeError("Falha simulada")
        )
        workflow = CorrectionWorkflow(engine)

        self.wait_for_signal(
            workflow.failed,
            trigger=lambda: workflow.start_analysis("Corrigir falha simulada"),
        )

        self.assertEqual(
            workflow.state,
            CorrectionWorkflowState.FAILED,
        )
        self.assertIsNone(workflow.last_result)

    def test_empty_objective_is_rejected(self):
        engine = FakeCorrectionEngine()
        workflow = CorrectionWorkflow(engine)

        with self.assertRaises(ValueError):
            workflow.start_analysis("   ")

        self.assertEqual(engine.calls, 0)
        self.assertEqual(
            workflow.state,
            CorrectionWorkflowState.IDLE,
        )

    def test_concurrent_analysis_is_blocked(self):
        engine = BlockingCorrectionEngine()
        workflow = CorrectionWorkflow(engine)

        workflow.start_analysis("Primeira análise")

        try:
            self.assertTrue(engine.entered.wait(timeout=3))

            with self.assertRaises(RuntimeError):
                workflow.start_analysis("Segunda análise")

        finally:
            engine.release.set()

        self.wait_for_signal(workflow.plan_ready)

        self.assertEqual(
            workflow.state,
            CorrectionWorkflowState.AWAITING_APPROVAL,
        )

    def test_reset_cannot_discard_pending_plan(self):
        workflow = CorrectionWorkflow(FakeCorrectionEngine())

        workflow._state = CorrectionWorkflowState.AWAITING_APPROVAL

        with self.assertRaises(RuntimeError):
            workflow.reset()

        self.assertEqual(
            workflow.state,
            CorrectionWorkflowState.AWAITING_APPROVAL,
        )

    def test_patch_proposal_is_registered_for_approval(self):
        from types import SimpleNamespace

        class FakePatchProposalService:
            def __init__(self):
                self.calls = []

            def create_proposal(self, action, relative_path, inventory):
                self.calls.append((action, relative_path, inventory))
                return {
                    "relative_path": relative_path,
                    "expected_sha256": "a" * 64,
                    "original_snippet": "old_value",
                    "replacement_snippet": "new_value",
                    "explanation": "Corre??o simulada",
                }

        class FakeApprovalManager:
            def __init__(self):
                self.proposals = []

            def request_approval(self, proposal):
                self.proposals.append(proposal)
                return "approval-test-001"

        engine = FakeCorrectionEngine()
        patch_service = FakePatchProposalService()
        approval_manager = FakeApprovalManager()

        workflow = CorrectionWorkflow(
            engine,
            patch_proposal_service=patch_service,
            approval_manager=approval_manager,
        )

        action = {
            "id": "A001",
            "title": "Corrigir inicializa??o",
            "files": ["main/main.c"],
        }
        inventory = ["main/main.c"]

        workflow._last_result = {
            "plan": {"actions": [action]},
            "planning_input": {"inventory": inventory},
        }
        workflow._state = CorrectionWorkflowState.AWAITING_APPROVAL

        received = []
        workflow.proposal_ready.connect(received.append)

        proposal_id = workflow.request_patch_proposal(
            "A001",
            "main/main.c",
        )

        self.assertEqual(proposal_id, "approval-test-001")
        self.assertEqual(len(patch_service.calls), 1)
        self.assertEqual(len(approval_manager.proposals), 1)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["proposal_id"], proposal_id)
        self.assertEqual(
            workflow.state,
            CorrectionWorkflowState.AWAITING_APPROVAL,
        )

    def test_patch_proposal_rejects_file_outside_action(self):
        from types import SimpleNamespace

        class FakePatchProposalService:
            def create_proposal(self, **kwargs):
                raise AssertionError("N?o deveria gerar proposta.")

        class FakeApprovalManager:
            def request_approval(self, proposal):
                raise AssertionError("N?o deveria solicitar aprova??o.")

        workflow = CorrectionWorkflow(
            FakeCorrectionEngine(),
            patch_proposal_service=FakePatchProposalService(),
            approval_manager=FakeApprovalManager(),
        )

        workflow._last_result = {
            "plan": {
                "actions": [
                    {"id": "A001", "files": ["main/main.c"]}
                ]
            },
            "planning_input": {"inventory": ["main/main.c", "main/app.c"]},
        }
        workflow._state = CorrectionWorkflowState.AWAITING_APPROVAL

        with self.assertRaises(ValueError):
            workflow.request_patch_proposal("A001", "main/app.c")

    def test_patch_proposal_requires_configured_services(self):
        workflow = CorrectionWorkflow(FakeCorrectionEngine())
        workflow._last_result = {
            "plan": {"actions": [{"id": "A001", "files": ["main/main.c"]}]},
            "planning_input": {"inventory": ["main/main.c"]},
        }
        workflow._state = CorrectionWorkflowState.AWAITING_APPROVAL

        with self.assertRaises(RuntimeError):
            workflow.request_patch_proposal("A001", "main/main.c")

    def test_failed_workflow_can_be_reset(self):
        workflow = CorrectionWorkflow(
            FakeCorrectionEngine(error=RuntimeError("Erro"))
        )

        self.wait_for_signal(
            workflow.failed,
            trigger=lambda: workflow.start_analysis("Corrigir falha simulada"),
        )
        workflow.reset()

        self.assertEqual(
            workflow.state,
            CorrectionWorkflowState.IDLE,
        )
        self.assertIsNone(workflow.last_result)


if __name__ == "__main__":
    unittest.main()