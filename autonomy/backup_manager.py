import hashlib
import os
import shutil
from pathlib import Path


class BackupManager:
    """Cria backups sequenciais e verifica sua integridade."""

    @staticmethod
    def _signature(stat_result):
        return (
            stat_result.st_dev,
            stat_result.st_ino,
            stat_result.st_size,
            stat_result.st_mtime_ns,
            stat_result.st_ctime_ns,
        )

    @staticmethod
    def create_backup(source_path):
        source = Path(source_path).resolve()

        if not source.is_file():
            raise FileNotFoundError(
                f"Arquivo para backup nao encontrado: {source}"
            )

        index = 1

        while True:
            backup = source.with_name(
                f"{source.name}.{index}_bak"
            )

            try:
                descriptor = os.open(
                    str(backup),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o666,
                )
                break
            except FileExistsError:
                index += 1

        try:
            source_hash = hashlib.sha256()
            copied_bytes = 0

            with source.open("rb") as original_file:
                before = os.fstat(original_file.fileno())

                with os.fdopen(descriptor, "wb") as output:
                    while True:
                        chunk = original_file.read(1024 * 1024)

                        if not chunk:
                            break

                        output.write(chunk)
                        source_hash.update(chunk)
                        copied_bytes += len(chunk)

                    output.flush()
                    os.fsync(output.fileno())

                after = os.fstat(original_file.fileno())

            path_stat = source.stat()

            if (
                BackupManager._signature(before)
                != BackupManager._signature(after)
            ):
                raise RuntimeError(
                    "Arquivo original mudou durante a copia."
                )

            if (
                BackupManager._signature(after)
                != BackupManager._signature(path_stat)
            ):
                raise RuntimeError(
                    "Arquivo original foi substituido durante a copia."
                )

            if copied_bytes != before.st_size:
                raise RuntimeError(
                    "Tamanho do backup diferente do original."
                )

            backup_hash = hashlib.sha256()

            with backup.open("rb") as backup_file:
                while True:
                    chunk = backup_file.read(1024 * 1024)

                    if not chunk:
                        break

                    backup_hash.update(chunk)

            if backup_hash.digest() != source_hash.digest():
                raise RuntimeError(
                    "Falha na verificacao SHA-256 do backup."
                )

            shutil.copystat(source, backup)

            return backup

        except Exception:
            backup.unlink(missing_ok=True)
            raise
