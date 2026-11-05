import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    command: tuple
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False
    cancelled: bool = False

    @property
    def success(self):
        return (
            self.returncode == 0
            and not self.timed_out
            and not self.cancelled
        )


class CommandRunner:
    """Executa processos sem shell e controla timeout/cancelamento."""

    @staticmethod
    def run(command, cwd, timeout=1800, cancel_event=None, env=None):
        if isinstance(command, (str, bytes)):
            raise TypeError("command deve ser uma sequencia de argumentos.")

        command = tuple(str(item) for item in command)
        if not command or not command[0]:
            raise ValueError("Comando vazio.")

        working_dir = Path(cwd).resolve()
        if not working_dir.is_dir():
            raise NotADirectoryError(str(working_dir))

        if timeout is not None and timeout <= 0:
            raise ValueError("timeout deve ser positivo ou None.")

        start = time.monotonic()
        kwargs = {
            "cwd": str(working_dir),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": env,
        }

        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        process = subprocess.Popen(command, **kwargs)
        timed_out = False
        cancelled = False

        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break

                if timeout is not None and time.monotonic() - start >= timeout:
                    timed_out = True
                    break

                try:
                    stdout, stderr = process.communicate(timeout=0.20)
                    return ProcessResult(
                        command, str(working_dir), process.returncode,
                        stdout, stderr, time.monotonic() - start
                    )
                except subprocess.TimeoutExpired:
                    continue

            # Encerra tambem os processos filhos do compilador.
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                )
            else:
                import signal
                os.killpg(process.pid, signal.SIGKILL)

            stdout, stderr = process.communicate()

            return ProcessResult(
                command, str(working_dir), process.returncode,
                stdout, stderr, time.monotonic() - start,
                timed_out=timed_out,
                cancelled=cancelled,
            )

        except Exception:
            if process.poll() is None:
                process.kill()
                process.communicate()
            raise