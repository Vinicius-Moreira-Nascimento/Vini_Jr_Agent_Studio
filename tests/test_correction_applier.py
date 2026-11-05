import hashlib
import tempfile
import unittest
from pathlib import Path

from autonomy.approval_manager import ApprovalManager
from autonomy.correction_applier import CorrectionApplier
from autonomy.backup_manager import BackupManager


class CorrectionApplierTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.approvals = ApprovalManager()
        self.applier = CorrectionApplier(
            approval_manager=self.approvals
        )

        self.target = self.root / "main.c"
        self.original = "int main(void) {\n    return 0;\n}\n"
        self.replacement = "int main(void) {\n    return 1;\n}\n"

        self.target.write_bytes(
            self.original.encode("utf-8")
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_approved_proposal(
        self,
        target=None,
        original=None,
        replacement=None,
        expected_hash=None,
    ):
        target = target or self.target
        content = target.read_bytes()

        proposal = {
            "relative_path": (
                target.relative_to(self.root).as_posix()
                if target.is_relative_to(self.root)
                else "../outside.c"
            ),
            "expected_sha256": (
                expected_hash
                if expected_hash is not None
                else hashlib.sha256(content).hexdigest()
            ),
            "original_snippet": (
                self.original if original is None else original
            ),
            "replacement_snippet": (
                self.replacement if replacement is None else replacement
            ),
            "explanation": "Correcao simulada para teste.",
        }

        proposal_id = self.approvals.request_approval(proposal)
        self.approvals.approve(proposal_id)

        return proposal_id

    def test_approved_change_is_applied(self):
        proposal_id = self.create_approved_proposal()

        result = self.applier.apply_approved(
            proposal_id,
            self.root,
        )

        self.assertTrue(result["success"])
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            self.replacement,
        )

    def test_backup_preserves_original_content(self):
        proposal_id = self.create_approved_proposal()

        result = self.applier.apply_approved(
            proposal_id,
            self.root,
        )

        backup = Path(result["backup"])

        self.assertTrue(backup.is_file())
        self.assertEqual(
            backup.read_text(encoding="utf-8"),
            self.original,
        )

    def test_hash_mismatch_blocks_write(self):
        proposal_id = self.create_approved_proposal(
            expected_hash="0" * 64,
        )

        with self.assertRaises(RuntimeError):
            self.applier.apply_approved(proposal_id, self.root)

        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            self.original,
        )

        self.assertFalse(
            list(self.root.glob("*.1_bak"))
        )

    def test_path_outside_project_is_blocked(self):
        proposal_id = self.create_approved_proposal()

        proposal = self.approvals._records[proposal_id].proposal
        proposal["relative_path"] = "../outside.c"

        with self.assertRaises(ValueError):
            self.applier.apply_approved(proposal_id, self.root)

        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            self.original,
        )

    def test_ambiguous_original_snippet_is_blocked(self):
        duplicated = self.original + self.original
        self.target.write_text(duplicated, encoding="utf-8")

        proposal_id = self.create_approved_proposal(
            original=self.original,
        )

        with self.assertRaises(RuntimeError):
            self.applier.apply_approved(proposal_id, self.root)

        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            duplicated,
        )

    def test_binary_file_is_blocked(self):
        self.target.write_bytes(b"\x00\x01\x02\x03")

        proposal_id = self.create_approved_proposal(
            original=self.original,
        )

        with self.assertRaises(ValueError):
            self.applier.apply_approved(proposal_id, self.root)

        self.assertEqual(
            self.target.read_bytes(),
            b"\x00\x01\x02\x03",
        )

    def test_utf8_bom_is_preserved(self):
        content = b"\xef\xbb\xbf" + self.original.encode("utf-8")
        self.target.write_bytes(content)

        proposal_id = self.create_approved_proposal()

        self.applier.apply_approved(proposal_id, self.root)

        updated = self.target.read_bytes()

        self.assertTrue(updated.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(
            updated[3:].decode("utf-8"),
            self.replacement,
        )

    def test_missing_approval_blocks_write(self):
        proposal_id = "approval-inexistente"

        with self.assertRaises(KeyError):
            self.applier.apply_approved(proposal_id, self.root)

        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            self.original,
        )



    def test_oversized_file_is_blocked(self):
        self.target.write_bytes(
            b"A" * (CorrectionApplier.MAX_FILE_SIZE + 1)
        )

        proposal_id = self.create_approved_proposal()

        with self.assertRaises(ValueError):
            self.applier.apply_approved(proposal_id, self.root)

        self.assertEqual(
            self.target.stat().st_size,
            CorrectionApplier.MAX_FILE_SIZE + 1,
        )
        self.assertFalse(list(self.root.glob("*.1_bak")))

    def test_backup_collision_does_not_overwrite_existing_backup(self):
        first_backup = self.target.with_name(
            self.target.name + ".1_bak"
        )
        first_backup.write_bytes(b"BACKUP ANTERIOR")

        created = BackupManager.create_backup(self.target)

        self.assertEqual(
            first_backup.read_bytes(),
            b"BACKUP ANTERIOR",
        )
        self.assertTrue(created.is_file())
        self.assertNotEqual(created, first_backup)
        self.assertEqual(
            created.read_bytes(),
            self.original.encode("utf-8"),
        )

    def test_event_manager_failure_does_not_hide_applied_change(self):
        class FailingEventManager:
            def publish(self, **kwargs):
                raise RuntimeError("Falha simulada no EventManager")

        proposal_id = self.create_approved_proposal()

        applier = CorrectionApplier(
            approval_manager=self.approvals,
            event_manager=FailingEventManager(),
        )

        result = applier.apply_approved(proposal_id, self.root)

        self.assertTrue(result["success"])
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            self.replacement,
        )


if __name__ == "__main__":
    unittest.main()
