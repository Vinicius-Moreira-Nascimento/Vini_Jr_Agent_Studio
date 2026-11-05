import json
import tempfile
import unittest

from pathlib import Path

from autonomy.patch_proposal_service import (
    PatchProposalError,
    PatchProposalService,
)


class FakeProvider:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def send_message(self, messages, model):
        self.calls.append((messages, model))

        if isinstance(self.response, Exception):
            raise self.response

        return self.response


class PatchProposalServiceTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)

        self.source = (
            "void app_main(void)\n"
            "{\n"
            "    int value = 10;\n"
            "}\n"
        )

        self.target = self.project / "main.c"
        self.target.write_text(self.source, encoding="utf-8")

        self.action = {
            "id": "A001",
            "title": "Corrigir variavel",
            "description": "Revisar a variavel value.",
            "files": ["main.c"],
        }

        self.inventory = [
            {
                "path": "main.c",
                "extension": ".c",
                "size": self.target.stat().st_size,
            }
        ]

        self.response = {
            "original_snippet": "int value = 10;",
            "replacement_snippet": "int value = 20;",
            "explanation": "Ajuste do valor conforme o requisito.",
        }

        self.provider = FakeProvider(
            json.dumps(self.response)
        )

        self.service = PatchProposalService(
            provider=self.provider,
            model="fake-model",
            project_root=self.project,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_proposal_returns_applier_contract(self):
        result = self.service.create_proposal(
            self.action,
            "main.c",
            self.inventory,
        )

        self.assertEqual(
            set(result.keys()),
            {
                "relative_path",
                "expected_sha256",
                "original_snippet",
                "replacement_snippet",
                "explanation",
            },
        )

        self.assertEqual(result["relative_path"], "main.c")
        self.assertEqual(result["original_snippet"], "int value = 10;")
        self.assertEqual(result["replacement_snippet"], "int value = 20;")
        self.assertEqual(
            result["expected_sha256"],
            __import__("hashlib").sha256(
                self.target.read_bytes()
            ).hexdigest(),
        )

    def test_service_does_not_modify_source_file(self):
        original = self.target.read_bytes()

        self.service.create_proposal(
            self.action,
            "main.c",
            self.inventory,
        )

        self.assertEqual(self.target.read_bytes(), original)

    def test_file_outside_action_is_blocked(self):
        with self.assertRaises(PatchProposalError):
            self.service.create_proposal(
                self.action,
                "other.c",
                self.inventory,
            )

        self.assertEqual(len(self.provider.calls), 0)

    def test_file_outside_inventory_is_blocked(self):
        with self.assertRaises(PatchProposalError):
            self.service.create_proposal(
                self.action,
                "main.c",
                [],
            )

        self.assertEqual(len(self.provider.calls), 0)

    def test_path_traversal_is_blocked(self):
        with self.assertRaises(PatchProposalError):
            self.service.create_proposal(
                self.action,
                "../main.c",
                self.inventory,
            )

        self.assertEqual(len(self.provider.calls), 0)

    def test_ambiguous_original_snippet_is_blocked(self):
        self.target.write_text(
            "int value = 10;\nint value = 10;\n",
            encoding="utf-8",
        )

        with self.assertRaises(PatchProposalError):
            self.service.create_proposal(
                self.action,
                "main.c",
                self.inventory,
            )

    def test_invalid_json_is_blocked(self):
        self.provider.response = "resposta invalida"

        with self.assertRaises(PatchProposalError):
            self.service.create_proposal(
                self.action,
                "main.c",
                self.inventory,
            )

    def test_response_with_extra_fields_is_blocked(self):
        invalid = dict(self.response)
        invalid["relative_path"] = "../other.c"
        self.provider.response = json.dumps(invalid)

        with self.assertRaises(PatchProposalError):
            self.service.create_proposal(
                self.action,
                "main.c",
                self.inventory,
            )

    def test_binary_file_is_blocked(self):
        self.target.write_bytes(b"\x00\x01\x02")

        with self.assertRaises(PatchProposalError):
            self.service.create_proposal(
                self.action,
                "main.c",
                self.inventory,
            )

    def test_oversized_file_is_blocked(self):
        self.target.write_bytes(b"A" * 100)

        service = PatchProposalService(
            provider=self.provider,
            model="fake-model",
            project_root=self.project,
            max_file_size=50,
        )

        with self.assertRaises(PatchProposalError):
            service.create_proposal(
                self.action,
                "main.c",
                self.inventory,
            )

        self.assertEqual(len(self.provider.calls), 0)

    def test_symbolic_link_is_blocked(self):
        link = self.project / "linked.c"

        try:
            link.symlink_to(self.target)
        except (OSError, NotImplementedError):
            self.skipTest(
                "Criacao de link simbolico indisponivel neste ambiente."
            )

        action = dict(self.action)
        action["files"] = ["linked.c"]

        inventory = [
            {"path": "linked.c", "extension": ".c", "size": 10}
        ]

        with self.assertRaises(PatchProposalError):
            self.service.create_proposal(
                action,
                "linked.c",
                inventory,
            )

    def test_provider_failure_is_propagated(self):
        self.provider.response = RuntimeError("Falha simulada")

        with self.assertRaises(RuntimeError):
            self.service.create_proposal(
                self.action,
                "main.c",
                self.inventory,
            )

    def test_windows_absolute_path_is_blocked(self):
        with self.assertRaises(PatchProposalError):
            self.service.create_proposal(
                self.action,
                "C:\\Windows\\system.ini",
                self.inventory,
            )


if __name__ == "__main__":
    unittest.main()