
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from interface.main_window import MainWindow


class MainWindowCompositionTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_correction_services_are_composed_and_injected(self):
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            window = MainWindow()

            try:
                window.embedded.validate_project = Mock(
                    return_value=str(project_root)
                )

                fake_provider = object()
                fake_planning = SimpleNamespace(
                    provider=fake_provider,
                    model="gpt-4.1-mini",
                )

                fake_engine = object()
                fake_patch_service = object()
                fake_approval_manager = object()
                fake_backup_manager = object()
                fake_applier = object()
                fake_workflow = object()

                with patch(
                    "interface.main_window.PlanningService",
                    return_value=fake_planning,
                ) as planning_class, patch(
                    "interface.main_window.CorrectionEngine",
                    return_value=fake_engine,
                ) as engine_class, patch(
                    "interface.main_window.PatchProposalService",
                    return_value=fake_patch_service,
                ) as patch_class, patch(
                    "interface.main_window.ApprovalManager",
                    return_value=fake_approval_manager,
                ) as approval_class, patch(
                    "interface.main_window.BackupManager",
                    return_value=fake_backup_manager,
                ) as backup_class, patch(
                    "interface.main_window.CorrectionApplier",
                    return_value=fake_applier,
                ) as applier_class, patch(
                    "interface.main_window.CorrectionWorkflow",
                    return_value=fake_workflow,
                ) as workflow_class:

                    result = window.create_correction_workflow()

                self.assertIs(result, fake_workflow)

                planning_class.assert_called_once()
                engine_class.assert_called_once_with(
                    planning_service=fake_planning,
                    event_manager=window.event_manager,
                )

                patch_class.assert_called_once_with(
                    provider=fake_provider,
                    model="gpt-4.1-mini",
                    project_root=project_root.resolve(),
                )

                approval_class.assert_called_once_with(
                    event_manager=window.event_manager,
                )

                backup_class.assert_called_once_with()

                applier_class.assert_called_once_with(
                    approval_manager=fake_approval_manager,
                    event_manager=window.event_manager,
                    backup_manager=fake_backup_manager,
                )

                workflow_class.assert_called_once_with(
                    correction_engine=fake_engine,
                    parent=window,
                    patch_proposal_service=fake_patch_service,
                    approval_manager=fake_approval_manager,
                )

                self.assertIs(
                    window.patch_proposal_service,
                    fake_patch_service,
                )
                self.assertIs(
                    window.approval_manager,
                    fake_approval_manager,
                )
                self.assertIs(
                    window.backup_manager,
                    fake_backup_manager,
                )
                self.assertIs(
                    window.correction_applier,
                    fake_applier,
                )

            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
