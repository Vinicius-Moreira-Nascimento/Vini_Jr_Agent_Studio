import hashlib
import os
import re
import shutil
import tempfile

from pathlib import Path, PurePosixPath, PureWindowsPath

from autonomy.backup_manager import BackupManager
from project_engine.file_manager import safe_resolve, validate_project


class CorrectionApplier:
    """
    Aplica uma unica alteracao textual previamente aprovada.

    Nao executa comandos, compilacao, Full Clean ou Flash.
    """

    MAX_FILE_SIZE = 2 * 1024 * 1024

    REQUIRED_FIELDS = (
        "relative_path",
        "expected_sha256",
        "original_snippet",
        "replacement_snippet",
        "explanation",
    )

    def __init__(
        self,
        approval_manager,
        event_manager=None,
        backup_manager=None,
    ):
        if not callable(
            getattr(approval_manager, "consume_approval", None)
        ):
            raise TypeError(
                "approval_manager precisa implementar consume_approval()."
            )

        if event_manager is not None and not callable(
            getattr(event_manager, "publish", None)
        ):
            raise TypeError("event_manager precisa implementar publish().")

        manager = backup_manager or BackupManager

        if not callable(getattr(manager, "create_backup", None)):
            raise TypeError(
                "backup_manager precisa implementar create_backup()."
            )

        self.approval_manager = approval_manager
        self.event_manager = event_manager
        self.backup_manager = manager

    def _publish_event(
        self,
        event_type,
        message,
        status,
        proposal_id,
        details=None,
    ):
        if self.event_manager is None:
            return False

        try:
            self.event_manager.publish(
                category="correction",
                event_type=event_type,
                message=message,
                status=status,
                source="CorrectionApplier",
                task_id=proposal_id,
                details=details or {},
            )
            return True
        except Exception:
            # Falhas de notificacao nao podem mascarar o resultado da escrita.
            return False

    @staticmethod
    def _sha256(content):
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _file_signature(path):
        stat_result = Path(path).stat()
        return (
            stat_result.st_dev,
            stat_result.st_ino,
            stat_result.st_size,
            stat_result.st_mtime_ns,
            stat_result.st_ctime_ns,
        )

    @classmethod
    def _read_limited(cls, path):
        path = Path(path)

        with path.open("rb") as source:
            before = os.fstat(source.fileno())

            if before.st_size > cls.MAX_FILE_SIZE:
                raise ValueError(
                    "Arquivo excede o limite de tamanho de 2 MiB."
                )

            content = source.read(cls.MAX_FILE_SIZE + 1)
            after = os.fstat(source.fileno())

        def signature(item):
            return (
                item.st_dev,
                item.st_ino,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns,
            )

        if len(content) > cls.MAX_FILE_SIZE:
            raise ValueError(
                "Arquivo excede o limite de tamanho de 2 MiB."
            )

        if (
            signature(before) != signature(after)
            or len(content) != after.st_size
            or signature(after) != signature(path.stat())
        ):
            raise RuntimeError(
                "Arquivo mudou durante a leitura. Operacao bloqueada."
            )

        return content

    @staticmethod
    def _validate_proposal(proposal):
        if not isinstance(proposal, dict):
            raise ValueError("Proposta invalida.")

        for field in CorrectionApplier.REQUIRED_FIELDS:
            if field not in proposal:
                raise ValueError(
                    f"Campo obrigatorio ausente: {field}"
                )

        relative_path = proposal["relative_path"]

        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("relative_path invalido.")

        normalized = relative_path.replace("\\", "/")
        posix_path = PurePosixPath(normalized)
        windows_path = PureWindowsPath(relative_path)

        if (
            posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in posix_path.parts
            or not posix_path.parts
        ):
            raise ValueError("Caminho absoluto ou traversal bloqueado.")

        expected_hash = proposal["expected_sha256"]

        if (
            not isinstance(expected_hash, str)
            or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_hash)
        ):
            raise ValueError("SHA-256 esperado invalido.")

        original = proposal["original_snippet"]
        replacement = proposal["replacement_snippet"]
        explanation = proposal["explanation"]

        if not isinstance(original, str) or not original:
            raise ValueError("Trecho original invalido.")

        if not isinstance(replacement, str) or not replacement:
            raise ValueError("Trecho substituto invalido.")

        if original == replacement:
            raise ValueError("Os trechos original e substituto sao identicos.")

        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError("Justificativa da alteracao invalida.")

        return posix_path

    @staticmethod
    def _resolve_target(project_root, relative_path):
        root = validate_project(project_root)

        current = root

        for part in relative_path.parts:
            current = current / part

            if current.is_symlink():
                raise ValueError(
                    "Caminho simbolico bloqueado pelo CorrectionApplier."
                )

        target = safe_resolve(root, relative_path.as_posix())

        if not target.is_relative_to(root):
            raise ValueError("Arquivo fora do projeto autorizado.")

        return root, target

    @staticmethod
    def _decode_source(content):
        if b"\x00" in content:
            raise ValueError("Arquivo binario bloqueado.")

        has_bom = content.startswith(b"\xef\xbb\xbf")

        try:
            text = content.decode("utf-8-sig")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = content.decode("latin-1")
            encoding = "latin-1"

        return text, encoding, has_bom

    def apply_approved(self, proposal_id, project_root):
        temp_path = None
        relative_path_text = None

        try:
            # A autorizacao e consumida uma unica vez.
            proposal = self.approval_manager.consume_approval(
                proposal_id
            )

            relative_path = self._validate_proposal(proposal)
            relative_path_text = relative_path.as_posix()

            root, target = self._resolve_target(
                project_root,
                relative_path,
            )

            current_bytes = self._read_limited(target)

            expected_hash = proposal["expected_sha256"].lower()

            if self._sha256(current_bytes) != expected_hash:
                raise RuntimeError(
                    "O arquivo mudou desde a analise. Aplicacao bloqueada."
                )

            current_text, encoding, has_bom = self._decode_source(
                current_bytes
            )

            original = proposal["original_snippet"]

            if current_text.count(original) != 1:
                raise RuntimeError(
                    "O trecho original precisa aparecer exatamente uma vez."
                )

            updated_text = current_text.replace(
                original,
                proposal["replacement_snippet"],
                1,
            )

            output_bytes = updated_text.encode(encoding)

            if has_bom:
                output_bytes = b"\xef\xbb\xbf" + output_bytes

            if len(output_bytes) > self.MAX_FILE_SIZE:
                raise ValueError(
                    "Arquivo resultante excede o limite de 2 MiB."
                )

            # Prepara o arquivo temporario no mesmo diretorio.
            descriptor, temp_name = tempfile.mkstemp(
                prefix=target.name + ".vini_jr_",
                suffix=".tmp",
                dir=str(target.parent),
            )

            temp_path = Path(temp_name)

            with os.fdopen(descriptor, "wb") as temp_file:
                temp_file.write(output_bytes)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            shutil.copystat(target, temp_path)

            # Backup obrigatorio antes de substituir o original.
            backup = self.backup_manager.create_backup(target)

            if self._sha256(self._read_limited(backup)) != expected_hash:
                raise RuntimeError(
                    "Backup nao corresponde ao arquivo aprovado."
                )

            # Segunda verificacao e deteccao de alteracoes concorrentes.
            signature_before = self._file_signature(target)
            latest_bytes = self._read_limited(target)
            signature_after = self._file_signature(target)

            if (
                signature_before != signature_after
                or self._sha256(latest_bytes) != expected_hash
            ):
                raise RuntimeError(
                    "Arquivo alterado durante a preparacao. Aplicacao bloqueada."
                )

            # Verificacao adicional imediatamente antes da substituicao.
            if self._file_signature(target) != signature_after:
                raise RuntimeError(
                    "Arquivo mudou antes da substituicao. Aplicacao bloqueada."
                )

            os.replace(temp_path, target)
            temp_path = None

            self._publish_event(
                "correction_applied",
                "Alteracao aplicada apos aprovacao explicita.",
                "success",
                proposal_id,
                {
                    "file": relative_path_text,
                    "backup": backup.name,
                },
            )

            return {
                "success": True,
                "proposal_id": proposal_id,
                "file": relative_path_text,
                "backup": str(backup),
                "sha256_before": expected_hash,
                "sha256_after": self._sha256(output_bytes),
            }

        except Exception as error:
            self._publish_event(
                "correction_application_failed",
                "Aplicacao da correcao bloqueada.",
                "error",
                proposal_id,
                {
                    "error_type": type(error).__name__,
                    "file": relative_path_text,
                },
            )
            raise

        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
