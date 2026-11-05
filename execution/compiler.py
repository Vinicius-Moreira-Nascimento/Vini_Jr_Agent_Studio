import base64
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .command_runner import CommandRunner


@dataclass(frozen=True)
class BuildResult:
    project_dir: str
    success: bool
    returncode: int
    output: str
    errors: tuple
    warnings: tuple
    duration: float
    timed_out: bool = False
    cancelled: bool = False
    command: tuple = ()

    def to_dict(self):
        return {
            "project_dir": self.project_dir,
            "success": self.success,
            "returncode": self.returncode,
            "output": self.output,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "duration": self.duration,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "command": list(self.command),
        }


class ESPIDFCompiler:
    """Compilador ESP-IDF. Esta classe disponibiliza somente BUILD."""

    def __init__(
        self,
        idf_path=None,
        python_env=None,
        config_path=None,
        timeout=1800,
    ):
        self.idf_path = Path(
            idf_path or os.environ.get("IDF_PATH", r"C:\esp\v6.1\esp-idf")
        ).expanduser().resolve()

        self.python_env = Path(
            python_env or os.environ.get(
                "IDF_PYTHON_ENV_PATH",
                r"C:\Espressif\tools\python\v6.1\venv"
            )
        ).expanduser().resolve()

        self.config_path = Path(
            config_path or "config/embedded.json"
        ).resolve()

        self.timeout = timeout
        self.export_script = self.idf_path / "export.ps1"
        self.idf_script = self.idf_path / "tools" / "idf.py"
        self.python_exe = self.python_env / "Scripts" / "python.exe"

    def validate_environment(self):
        required = (
            self.idf_path,
            self.python_env,
            self.export_script,
            self.idf_script,
            self.python_exe,
        )

        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError(
                "Componentes ESP-IDF ausentes: " + "; ".join(missing)
            )

        if not self.export_script.is_file():
            raise FileNotFoundError(str(self.export_script))

        if not self.idf_script.is_file():
            raise FileNotFoundError(str(self.idf_script))

        return True

    def resolve_project(self, project_dir=None):
        if project_dir is None:
            if not self.config_path.is_file():
                raise FileNotFoundError(
                    "Configuração embedded.json não encontrada."
                )

            with self.config_path.open(
                "r", encoding="utf-8-sig"
            ) as file:
                config = json.load(file)

            project_dir = config.get("project_path")

        if not project_dir:
            raise ValueError("Diretório do firmware não configurado.")

        project = Path(project_dir).expanduser().resolve(strict=True)

        if not project.is_dir():
            raise NotADirectoryError(str(project))

        cmake = project / "CMakeLists.txt"
        if not cmake.is_file():
            raise ValueError(
                "O diretório selecionado não possui CMakeLists.txt."
            )

        # A raiz autorizada de escrita do build é o próprio
        # projeto ESP-IDF configurado, nunca um caminho arbitrário.
        return project

    @staticmethod
    def _powershell():
        executable = shutil.which("powershell.exe")
        if executable:
            return executable

        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        fallback = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"

        if fallback.is_file():
            return str(fallback)

        raise FileNotFoundError("Windows PowerShell nao encontrado.")

    def build(self, project_dir=None, cancel_event=None, timeout=None):
        self.validate_environment()
        project = self.resolve_project(project_dir)

        # O ambiente e carregado dentro de um processo PowerShell filho.
        # Nenhum comando recebido da IA e interpretado pelo shell.
        script = (
            "$ErrorActionPreference = 'Stop'; "
            f". '{str(self.export_script).replace(chr(39), chr(39)*2)}' | Out-Null; "
            f"& '{str(self.python_exe).replace(chr(39), chr(39)*2)}' "
            f"'{str(self.idf_script).replace(chr(39), chr(39)*2)}' build; "
            "exit $LASTEXITCODE"
        )

        encoded = base64.b64encode(
            script.encode("utf-16le")
        ).decode("ascii")

        command = (
            self._powershell(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", encoded,
        )

        result = CommandRunner.run(
            command=command,
            cwd=project,
            timeout=self.timeout if timeout is None else timeout,
            cancel_event=cancel_event,
        )

        output = "\n".join(
            part for part in (result.stdout, result.stderr) if part
        )

        errors = tuple(
            line.strip() for line in output.splitlines()
            if re.search(r"\berror\s*:", line, re.IGNORECASE)
            or re.search(r"\bfatal error\b", line, re.IGNORECASE)
        )

        warnings = tuple(
            line.strip() for line in output.splitlines()
            if re.search(r"\bwarning\s*:", line, re.IGNORECASE)
        )

        return BuildResult(
            project_dir=str(project),
            success=result.success,
            returncode=result.returncode,
            output=output,
            errors=errors,
            warnings=warnings,
            duration=result.duration,
            timed_out=result.timed_out,
            cancelled=result.cancelled,
            command=result.command,
        )