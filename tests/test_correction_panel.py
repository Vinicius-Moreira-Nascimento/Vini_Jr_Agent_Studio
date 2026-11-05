import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from autonomy.correction_workflow import CorrectionWorkflow
from interface.correction_panel import CorrectionPanel


class FakeCorrectionEngine:

    def __init__(self, error=None, include_files=False):
        self.error = error
        self.include_files = include_files
        self.calls = 0

    def analyze_and_plan(self, objective):
        self.calls += 1

        if self.error:
            raise self.error

        action = {
            "id": "A001",
            "priority": "high",
            "title": "Revisar inicialização",
            "description": "Verificar sequência de inicialização.",
        }
        if self.include_files:
            action["files"] = ["main.c", "startup.c"]

        return {
            "task_id": "panel-test-task",
            "status": "completed",
            "analysis": {},
            "planning_input": {"inventory": []},
            "plan": {
                "summary": "Resumo de teste do firmware.",
                "findings": [
                    {
                        "id": "F001",
                        "severity": "high",
                        "title": "Problema de teste",
                        "file": "main.c",
                        "line": 10,
                    }
                ],
                "actions": [action],
                "risks": [
                    "Possível impacto na inicialização do firmware."
                ],
            },
        }


class FakeApprovalManager:

    def __init__(self):
        self.statuses = {}
        self.approved = []
        self.rejected = []
        self.consume_calls = 0

    def register(self, proposal_id, status="pending"):
        self.statuses[proposal_id] = status

    def get_status(self, proposal_id):
        return self.statuses[proposal_id]

    def approve(self, proposal_id):
        if self.statuses[proposal_id] != "pending":
            raise RuntimeError("Proposta não está pendente.")
        self.statuses[proposal_id] = "approved"
        self.approved.append(proposal_id)
        return True

    def reject(self, proposal_id):
        if self.statuses[proposal_id] != "pending":
            raise RuntimeError("Proposta não está pendente.")
        self.statuses[proposal_id] = "rejected"
        self.rejected.append(proposal_id)
        return True

    def consume_approval(self, proposal_id):
        self.consume_calls += 1
        self.statuses[proposal_id] = "consumed"


class CorrectionPanelTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

        if cls.app is None:
            cls.app = QApplication([])

    def wait_for_signal(self, signal, timeout=5000):
        loop = QEventLoop()
        received = []

        def on_signal(*args):
            received.append(args)
            loop.quit()

        signal.connect(on_signal)
        QTimer.singleShot(timeout, loop.quit)

        loop.exec()
        signal.disconnect(on_signal)

        self.assertTrue(
            received,
            "O sinal esperado não foi recebido dentro do prazo.",
        )

        return received[0]

    def _run_analysis(self, engine):
        workflow = CorrectionWorkflow(engine)
        panel = CorrectionPanel(workflow)
        received = []
        loop = QEventLoop()

        def on_ready(result):
            received.append(result)
            loop.quit()

        workflow.plan_ready.connect(on_ready)
        panel.start_button.click()
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        workflow.plan_ready.disconnect(on_ready)

        worker = workflow._worker
        if worker is not None:
            self.assertTrue(
                worker.wait(5000),
                "A thread de análise não terminou dentro do prazo.",
            )

        self.assertEqual(len(received), 1)
        return workflow, panel

    @staticmethod
    def _notification(proposal_id, path, original, replacement):
        return {
            "proposal_id": proposal_id,
            "action_id": "A001",
            "relative_path": path,
            "proposal": {
                "relative_path": path,
                "expected_sha256": "test-hash",
                "original_snippet": original,
                "replacement_snippet": replacement,
                "explanation": f"Explicação de {proposal_id}.",
            },
        }

    def test_panel_displays_successful_plan(self):
        engine = FakeCorrectionEngine()
        workflow = CorrectionWorkflow(engine)
        panel = CorrectionPanel(workflow)

        self.wait_for_signal(
            workflow.plan_ready,
            trigger=None,
        ) if False else None

        received = []

        workflow.plan_ready.connect(
            lambda result: received.append(result)
        )

        panel.start_button.click()

        loop = QEventLoop()

        def finish():
            if received:
                loop.quit()

        workflow.plan_ready.connect(
            lambda _result: finish()
        )

        QTimer.singleShot(5000, loop.quit)
        loop.exec()

        # Aguarda o término real da QThread antes de encerrar o teste.
        worker = workflow._worker
        if worker is not None:
            self.assertTrue(
                worker.wait(5000),
                "A thread de análise não terminou dentro do prazo.",
            )

        self.assertEqual(engine.calls, 1)
        self.assertEqual(len(received), 1)

        self.assertIn(
            "Resumo de teste",
            panel.summary.toPlainText(),
        )

        self.assertEqual(
            panel._list_widget(panel.findings_list).count(),
            1,
        )

        self.assertEqual(
            panel._list_widget(panel.actions_list).count(),
            1,
        )

        self.assertEqual(
            panel._list_widget(panel.risks_list).count(),
            1,
        )

        self.assertFalse(panel.start_button.isEnabled())

    def test_empty_objective_does_not_start_analysis(self):
        engine = FakeCorrectionEngine()
        workflow = CorrectionWorkflow(engine)
        panel = CorrectionPanel(workflow)

        panel.objective_input.setText("")
        panel.start_analysis()

        self.assertEqual(engine.calls, 0)
        self.assertIn("objetivo", panel.status_label.text().lower())

    def test_analysis_error_is_displayed(self):
        engine = FakeCorrectionEngine(
            error=RuntimeError("Falha simulada")
        )

        workflow = CorrectionWorkflow(engine)
        panel = CorrectionPanel(workflow)

        received = []

        workflow.failed.connect(
            lambda message: received.append(message)
        )

        panel.start_button.click()

        loop = QEventLoop()

        def finish():
            if received:
                loop.quit()

        workflow.failed.connect(
            lambda _message: finish()
        )

        QTimer.singleShot(5000, loop.quit)
        loop.exec()

        self.assertEqual(engine.calls, 1)
        self.assertTrue(received)
        self.assertIn("Falha simulada", panel.status_label.text())
        self.assertTrue(panel.start_button.isEnabled())

    def test_workflow_factory_is_lazy_and_used(self):
        engine = FakeCorrectionEngine()
        workflow = CorrectionWorkflow(engine)
        factory_calls = []

        def factory():
            factory_calls.append(True)
            return workflow

        panel = CorrectionPanel(workflow_factory=factory)

        self.assertEqual(factory_calls, [])
        self.assertIsNone(panel.workflow)

        received = []
        loop = QEventLoop()

        def on_ready(result):
            received.append(result)
            loop.quit()

        workflow.plan_ready.connect(on_ready)

        panel.start_button.click()

        QTimer.singleShot(5000, loop.quit)
        loop.exec()

        self.assertEqual(factory_calls, [True])
        self.assertIs(panel.workflow, workflow)
        self.assertEqual(engine.calls, 1)
        self.assertEqual(len(received), 1)

    def test_workflow_factory_error_is_displayed(self):
        def failing_factory():
            raise RuntimeError("Projeto não selecionado")

        panel = CorrectionPanel(workflow_factory=failing_factory)

        panel.start_analysis()

        self.assertIsNone(panel.workflow)
        self.assertTrue(panel.start_button.isEnabled())
        self.assertIn(
            "Projeto não selecionado",
            panel.status_label.text(),
        )

    def test_action_file_selection_and_async_proposal_request(self):
        engine = FakeCorrectionEngine(include_files=True)
        workflow, panel = self._run_analysis(engine)

        self.assertEqual(panel.action_selector.count(), 1)
        self.assertEqual(panel.file_selector.count(), 2)
        self.assertEqual(panel.file_selector.currentData(), "main.c")

        workflow.patch_proposal_service = object()
        workflow.approval_manager = FakeApprovalManager()
        # A composição normal injeta os serviços antes da atualização dos
        # controles; o teste injeta os serviços depois da análise.
        panel._update_proposal_controls()
        requested = []

        notification = self._notification(
            "proposal-async-001",
            "main.c",
            "int old_value = 0;",
            "int new_value = 1;",
        )

        def fake_async_request(action_id, relative_path):
            requested.append((action_id, relative_path))
            workflow.proposal_ready.emit(notification)

        workflow.request_patch_proposal_async = fake_async_request
        panel.generate_button.click()

        self.assertEqual(requested, [("A001", "main.c")])
        self.assertEqual(panel.proposal_selector.count(), 1)
        self.assertEqual(
            panel.original_snippet.toPlainText(),
            "int old_value = 0;",
        )
        self.assertEqual(
            panel.replacement_snippet.toPlainText(),
            "int new_value = 1;",
        )
        self.assertEqual(
            panel.proposal_explanation.toPlainText(),
            "Explicação de proposal-async-001.",
        )

        panel._status_timer.stop()

    def test_proposals_are_approved_and_rejected_individually(self):
        engine = FakeCorrectionEngine(include_files=True)
        workflow, panel = self._run_analysis(engine)
        manager = FakeApprovalManager()
        workflow.approval_manager = manager

        first = self._notification(
            "proposal-001", "main.c", "original A", "replacement A"
        )
        second = self._notification(
            "proposal-002", "startup.c", "original B", "replacement B"
        )

        manager.register("proposal-001")
        manager.register("proposal-002")
        panel._on_proposal_ready(first)
        panel._on_proposal_ready(second)
        panel._status_timer.stop()

        panel.proposal_selector.setCurrentIndex(0)
        self.assertTrue(panel.approve_button.isEnabled())
        panel.approve_button.click()

        self.assertEqual(manager.approved, ["proposal-001"])
        self.assertEqual(manager.statuses["proposal-001"], "approved")
        self.assertEqual(manager.statuses["proposal-002"], "pending")

        panel.proposal_selector.setCurrentIndex(1)
        self.assertTrue(panel.reject_button.isEnabled())
        panel.reject_button.click()

        self.assertEqual(manager.rejected, ["proposal-002"])
        self.assertEqual(manager.statuses["proposal-002"], "rejected")

        # A interface registra a decisão, mas não consome a aprovação.
        self.assertEqual(manager.consume_calls, 0)
        self.assertEqual(
            panel.proposal_status_label.text(),
            "Rejeitada",
        )
        panel._status_timer.stop()

    def test_expired_proposal_disables_decision_buttons(self):
        engine = FakeCorrectionEngine(include_files=True)
        workflow, panel = self._run_analysis(engine)
        manager = FakeApprovalManager()
        manager.register("proposal-expired", status="expired")
        workflow.approval_manager = manager

        panel._on_proposal_ready(
            self._notification(
                "proposal-expired",
                "main.c",
                "old",
                "new",
            )
        )

        self.assertIn("Expirada", panel.proposal_status_label.text())
        self.assertFalse(panel.approve_button.isEnabled())
        self.assertFalse(panel.reject_button.isEnabled())
        panel._status_timer.stop()


if __name__ == "__main__":
    unittest.main()
