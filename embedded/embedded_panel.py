import json
import os
import re
import shutil
import threading
import time
from uuid import uuid4

import serial
import serial.tools.list_ports

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTextEdit, QFileDialog,
    QMessageBox, QGroupBox, QFormLayout
)
from PySide6.QtCore import QProcess, QThread, Signal, QProcessEnvironment


class SerialWorker(QThread):

    received = Signal(str)
    status = Signal(str)
    connection_changed = Signal(bool)

    def __init__(self, port, baud):
        super().__init__()
        self.port = port
        self.baud = baud
        self.stop_event = threading.Event()
        self.serial_port = None

    def run(self):

        try:
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=0.2,
                write_timeout=1
            )

            self.status.emit(
                f"[UART] Conectado em {self.port} - {self.baud} baud"
            )
            self.connection_changed.emit(True)

            while not self.stop_event.is_set():

                try:
                    data = self.serial_port.readline()

                    if data:
                        message = data.decode(
                            "utf-8",
                            errors="replace"
                        ).rstrip("\r\n")

                        if message:
                            self.received.emit(message)

                except serial.SerialException as error:
                    self.status.emit(
                        "[UART ERRO] " + str(error)
                    )
                    break

        except Exception as error:
            self.status.emit(
                "[UART FALHA] " + str(error)
            )

        finally:
            if self.serial_port:
                try:
                    self.serial_port.close()
                except Exception:
                    pass

            self.connection_changed.emit(False)
            self.status.emit("[UART] Desconectado.")

    def stop(self):
        self.stop_event.set()


class EmbeddedPanel(QWidget):
    build_completed = Signal(dict)

    def __init__(self):
        super().__init__()

        self.process = None
        self.serial_worker = None
        self.log_buffer = []

        self.event_manager = None
        self._task_id = None
        self._process_kind = None
        self._process_started_at = None
        self._process_command = []
        self._output_line_buffer = ""
        self._cancel_requested = False
        self._build_result_emitted = False

        self.config_path = os.path.join(
            "config",
            "embedded.json"
        )

        self.build_interface()
        self.load_config()
        self.check_environment()
        self.refresh_ports()


    def set_event_manager(self, event_manager):
        """Define o gerenciador central de eventos."""
        self.event_manager = event_manager

    def _publish_event(
        self, event_type, message, status="info", details=None
    ):
        if self.event_manager is None:
            return

        self.event_manager.publish(
            category="esp_idf",
            event_type=event_type,
            message=str(message),
            status=status,
            source="EmbeddedPanel",
            task_id=self._task_id,
            details=details or {},
        )

    def on_process_started(self):
        kind = self._process_kind or "comando"

        self._publish_event(
            event_type="process_started",
            message=f"ESP-IDF iniciou: {kind}",
            status="running",
            details={
                "command": self._process_command,
                "process_kind": kind,
            },
        )

    def _publish_process_output(self, output):
        if not output:
            return

        self._output_line_buffer += output
        lines = self._output_line_buffer.split("\n")
        self._output_line_buffer = lines.pop()

        for line in lines:
            self._publish_output_line(line.rstrip("\r"))

    def _publish_output_line(self, line):
        line = line.strip()

        if not line:
            return

        lower = line.lower()

        if (
            "warning:" in lower
            or lower.startswith("warning")
            or "[warning]" in lower
        ):
            event_type = "process_warning"
            status = "warning"

        elif (
            "error:" in lower
            or "fatal error" in lower
            or "undefined reference" in lower
            or "[error]" in lower
        ):
            event_type = "process_error_output"
            status = "error"

        else:
            event_type = "process_output"
            status = "info"

        self._publish_event(
            event_type=event_type,
            message=line[:1000],
            status=status,
            details={
                "process_kind": self._process_kind,
                "output": line[:4000],
            },
        )

    def _flush_process_output(self):
        if self._output_line_buffer:
            self._publish_output_line(self._output_line_buffer)
            self._output_line_buffer = ""

    def build_interface(self):

        layout = QVBoxLayout(self)

        title = QLabel("EMBEDDED DEVELOPMENT")
        title.setStyleSheet(
            "font-size: 20px; font-weight: bold;"
        )
        layout.addWidget(title)

        description = QLabel(
            "Ambiente de desenvolvimento embarcado - ESP-IDF"
        )
        description.setStyleSheet("color: #94A3B8;")
        layout.addWidget(description)

        project_group = QGroupBox("Projeto e ambiente")
        project_layout = QFormLayout(project_group)

        project_row = QHBoxLayout()

        self.project_path = QLineEdit()
        self.project_path.setPlaceholderText(
            "Diretório do projeto ESP-IDF"
        )

        browse_project = QPushButton("Selecionar projeto")
        browse_project.clicked.connect(self.select_project)

        project_row.addWidget(self.project_path, 1)
        project_row.addWidget(browse_project)

        project_layout.addRow("Diretório:", project_row)

        self.idf_path = QLineEdit()
        self.idf_path.setReadOnly(True)

        project_layout.addRow("ESP-IDF:", self.idf_path)

        layout.addWidget(project_group)

        actions_group = QGroupBox("Comandos ESP-IDF")
        actions_layout = QHBoxLayout(actions_group)

        self.build_button = QPushButton("Build")
        self.build_button.clicked.connect(
            lambda: self.run_idf(["build"])
        )

        self.clean_button = QPushButton("Full Clean")
        self.clean_button.clicked.connect(self.confirm_clean)

        self.flash_button = QPushButton("Flash")
        self.flash_button.clicked.connect(self.confirm_flash)

        self.stop_button = QPushButton("Interromper")
        self.stop_button.setStyleSheet(
            "background-color: #B91C1C;"
        )
        self.stop_button.clicked.connect(self.stop_process)
        self.stop_button.setEnabled(False)

        self.save_button = QPushButton("Salvar configuração")
        self.save_button.clicked.connect(self.save_config)

        actions_layout.addWidget(self.build_button)
        actions_layout.addWidget(self.clean_button)
        actions_layout.addWidget(self.flash_button)
        actions_layout.addWidget(self.stop_button)
        actions_layout.addWidget(self.save_button)

        layout.addWidget(actions_group)

        serial_group = QGroupBox("Monitor serial UART")
        serial_layout = QVBoxLayout(serial_group)

        serial_controls = QHBoxLayout()

        self.com_port = QLineEdit("COM8")
        self.com_port.setMaximumWidth(100)

        self.baud_rate = QLineEdit("115200")
        self.baud_rate.setMaximumWidth(110)

        self.refresh_button = QPushButton("Atualizar COM")
        self.refresh_button.clicked.connect(self.refresh_ports)

        self.connect_button = QPushButton("Conectar COM")
        self.connect_button.clicked.connect(self.connect_serial)

        self.disconnect_button = QPushButton("Desconectar")
        self.disconnect_button.setStyleSheet(
            "background-color: #B91C1C;"
        )
        self.disconnect_button.clicked.connect(
            self.disconnect_serial
        )
        self.disconnect_button.setEnabled(False)

        self.save_logs_button = QPushButton("Salvar logs")
        self.save_logs_button.clicked.connect(self.save_logs)

        serial_controls.addWidget(QLabel("Porta:"))
        serial_controls.addWidget(self.com_port)
        serial_controls.addWidget(QLabel("Baud:"))
        serial_controls.addWidget(self.baud_rate)
        serial_controls.addWidget(self.refresh_button)
        serial_controls.addWidget(self.connect_button)
        serial_controls.addWidget(self.disconnect_button)
        serial_controls.addWidget(self.save_logs_button)

        serial_layout.addLayout(serial_controls)

        self.serial_status = QLabel("UART desconectada.")
        self.serial_status.setStyleSheet(
            "color: #94A3B8;"
        )
        serial_layout.addWidget(self.serial_status)

        layout.addWidget(serial_group)

        terminal_header = QHBoxLayout()

        terminal_title = QLabel("TERMINAL / MONITOR DE EXECUÇÃO")
        terminal_title.setStyleSheet(
            "font-size: 15px; font-weight: bold;"
        )

        clear_button = QPushButton("Limpar")
        clear_button.clicked.connect(self.clear_terminal)

        terminal_header.addWidget(terminal_title)
        terminal_header.addStretch()
        terminal_header.addWidget(clear_button)

        layout.addLayout(terminal_header)

        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setStyleSheet("""
            QTextEdit {
                background-color: #0B1220;
                color: #D1D5DB;
                font-family: Consolas;
                font-size: 12px;
                border: 1px solid #40516B;
            }
        """)

        layout.addWidget(self.terminal, 1)

        self.status = QLabel("Aguardando configuração.")
        self.status.setStyleSheet("color: #94A3B8;")
        layout.addWidget(self.status)

    def log(self, message):

        self.terminal.append(str(message))

        scrollbar = self.terminal.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_terminal(self):
        self.terminal.clear()
        self.log_buffer.clear()

    def append_serial_log(self, message):

        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"

        self.log_buffer.append(formatted)
        self.terminal.append(formatted)

        scrollbar = self.terminal.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def refresh_ports(self):

        try:
            ports = serial.tools.list_ports.comports()

            available = [
                f"{port.device} - {port.description}"
                for port in ports
            ]

            self.log("[UART] Portas disponíveis:")

            if available:
                for port in available:
                    self.log("  " + port)
            else:
                self.log("[UART] Nenhuma porta detectada.")

        except Exception as error:
            self.log("[UART ERRO] " + str(error))

    def connect_serial(self):

        if self.process and (
            self.process.state() != QProcess.ProcessState.NotRunning
        ):
            QMessageBox.warning(
                self,
                "Terminal ESP-IDF",
                "Aguarde o comando atual terminar."
            )
            return

        if self.serial_worker and self.serial_worker.isRunning():
            return

        port = self.com_port.text().strip().upper()

        if not re.fullmatch(r"COM[1-9][0-9]*", port):
            QMessageBox.warning(
                self,
                "Porta COM",
                "Informe uma porta válida, como COM8."
            )
            return

        try:
            baud = int(self.baud_rate.text())
            if baud <= 0:
                raise ValueError()
        except ValueError:
            QMessageBox.warning(
                self,
                "Baud rate",
                "Informe um baud rate válido."
            )
            return

        self.serial_worker = SerialWorker(port, baud)

        self.serial_worker.received.connect(
            self.append_serial_log
        )
        self.serial_worker.status.connect(
            self.on_serial_status
        )
        self.serial_worker.connection_changed.connect(
            self.on_serial_connection_changed
        )

        self.log(f"[UART] Solicitando conexão com {port}...")
        self.connect_button.setEnabled(False)
        self.serial_worker.start()

    def on_serial_status(self, message):

        self.serial_status.setText(message)
        self.log(message)

    def on_serial_connection_changed(self, connected):

        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.refresh_button.setEnabled(not connected)

        if connected:
            self.serial_status.setStyleSheet(
                "color: #22C55E;"
            )
        else:
            self.serial_status.setStyleSheet(
                "color: #94A3B8;"
            )
            self.connect_button.setEnabled(True)

    def disconnect_serial(self):

        if self.serial_worker and self.serial_worker.isRunning():
            self.serial_worker.stop()
            self.disconnect_button.setEnabled(False)
            self.serial_status.setText(
                "Encerrando conexão UART..."
            )

    def save_logs(self):

        if not self.log_buffer:
            QMessageBox.information(
                self,
                "Logs",
                "Ainda não existem logs seriais para salvar."
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar logs UART",
            "esp32_uart.log",
            "Arquivos de log (*.log);;Texto (*.txt)"
        )

        if path:
            with open(path, "w", encoding="utf-8") as file:
                file.write("\n".join(self.log_buffer))

            self.log("[OK] Logs salvos em: " + path)

    def check_environment(self):

        idf = os.environ.get("IDF_PATH", "")
        self.idf_path.setText(idf)

        if idf and os.path.isfile(
            os.path.join(idf, "tools", "idf.py")
        ):
            self.log("[OK] ESP-IDF encontrado: " + idf)
        else:
            self.log("[AVISO] IDF_PATH não encontrado.")

        self.log(
            "[OK] PySerial: " + serial.__version__
        )

    def select_project(self):

        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar projeto ESP-IDF",
            self.project_path.text() or os.path.expanduser("~")
        )

        if folder:
            self.project_path.setText(folder)
            self.save_config()

    def load_config(self):

        if not os.path.exists(self.config_path):
            return

        try:
            with open(
                self.config_path,
                "r",
                encoding="utf-8-sig"
            ) as file:
                config = json.load(file)

            self.project_path.setText(
                config.get("project_path", "")
            )
            self.com_port.setText(
                config.get("com_port", "COM8")
            )
            self.baud_rate.setText(
                str(config.get("baud_rate", 115200))
            )

        except Exception as error:
            self.log("[ERRO] Configuração: " + str(error))

    def save_config(self):

        config = {
            "project_path": self.project_path.text().strip(),
            "com_port": self.com_port.text().strip().upper(),
            "baud_rate": self.baud_rate.text().strip()
        }

        os.makedirs("config", exist_ok=True)

        with open(
            self.config_path,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                config,
                file,
                indent=4,
                ensure_ascii=False
            )

        self.status.setText("Configuração salva.")

    def validate_project(self):

        project = self.project_path.text().strip()

        if not project or not os.path.isdir(project):
            QMessageBox.warning(
                self,
                "Projeto",
                "Selecione um diretório válido."
            )
            return None

        if not os.path.isfile(
            os.path.join(project, "CMakeLists.txt")
        ):
            QMessageBox.warning(
                self,
                "Projeto ESP-IDF",
                "Não encontrei CMakeLists.txt no diretório."
            )
            return None

        return project

    def get_idf_command(self):

        idf = os.environ.get("IDF_PATH", "")

        if idf:
            script = os.path.join(idf, "tools", "idf.py")
            python = shutil.which("python")

            if os.path.isfile(script) and python:
                return python, [script]

        executable = shutil.which("idf.py")

        if executable:
            return executable, []

        return None, []

    def run_idf(self, arguments):

        if self.serial_worker and self.serial_worker.isRunning():
            QMessageBox.warning(
                self,
                "Porta COM ocupada",
                "Desconecte o monitor UART antes de executar "
                "comandos que utilizem a porta serial."
            )
            return

        if self.process and (
            self.process.state() != QProcess.ProcessState.NotRunning
        ):
            QMessageBox.warning(
                self,
                "Terminal ESP-IDF",
                "Já existe um comando em execução."
            )
            return

        project = self.validate_project()

        if not project:
            return

        program, base_arguments = self.get_idf_command()

        if not program:
            QMessageBox.critical(
                self,
                "ESP-IDF não encontrado",
                "Não foi possível localizar idf.py."
            )
            return

        if arguments and arguments[0] == "flash":

            port = self.com_port.text().strip().upper()

            if not re.fullmatch(r"COM[1-9][0-9]*", port):
                QMessageBox.warning(
                    self,
                    "Porta COM",
                    "Informe uma porta válida."
                )
                return

            base_arguments += ["-p", port]

        self.save_config()

        self._task_id = uuid4().hex
        self._process_kind = (
            arguments[0] if arguments else "comando"
        )
        self._build_result_emitted = False
        self._process_started_at = time.monotonic()
        self._process_command = (
            [program] + base_arguments + arguments
        )
        self._output_line_buffer = ""
        self._cancel_requested = False

        self.process = QProcess(self)
        self.process.setWorkingDirectory(project)
        self.process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
        )

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(environment)

        self.process.readyReadStandardOutput.connect(
            self.read_output
        )
        self.process.started.connect(
            self.on_process_started
        )
        self.process.finished.connect(
            self.on_process_finished
        )
        self.process.errorOccurred.connect(
            self.on_process_error
        )

        command_arguments = base_arguments + arguments

        self.log("")
        self.log("========================================")
        self.log("[EXECUTANDO] " + program)
        self.log("[ARGUMENTOS] " + " ".join(command_arguments))
        self.log("[DIRETÓRIO] " + project)
        self.log("========================================")

        self.set_running(True)
        self.status.setText("Executando ESP-IDF...")

        self.process.start(program, command_arguments)


    def read_output(self):

        if not self.process:
            return

        data = bytes(self.process.readAllStandardOutput())

        if data:
            output = data.decode(
                "utf-8",
                errors="replace"
            )

            self.terminal.insertPlainText(output)
            self._publish_process_output(output)

            scrollbar = self.terminal.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())


    def _emit_build_completed(self, result):
        if self._process_kind != "build":
            return

        if self._build_result_emitted:
            return

        self._build_result_emitted = True
        self.build_completed.emit(dict(result))


    def on_process_finished(self, exit_code, exit_status):

        self.read_output()
        self._flush_process_output()
        self.set_running(False)

        duration = (
            time.monotonic() - self._process_started_at
            if self._process_started_at is not None
            else None
        )

        if self._cancel_requested:
            status = "cancelled"
            message = "Processo ESP-IDF cancelado."

        elif exit_code == 0:
            status = "success"
            message = "Processo ESP-IDF conclu?do com sucesso."

        else:
            status = "error"
            message = (
                "Processo ESP-IDF finalizado com erro. "
                f"C?digo de sa?da: {exit_code}"
            )

        if status == "success":
            self.log("\n[SUCESSO] Processo conclu?do.")
            self.status.setText("Processo conclu?do.")

        elif status == "cancelled":
            self.log("\n[CANCELADO] Processo interrompido.")
            self.status.setText("Processo cancelado.")

        else:
            self.log(
                "\n[ERRO] C?digo de sa?da: " + str(exit_code)
            )
            self.status.setText("Processo finalizado com erro.")

        self._publish_event(
            event_type="process_finished",
            message=message,
            status=status,
            details={
                "exit_code": exit_code,
                "exit_status": str(exit_status),
                "duration_seconds": duration,
                "process_kind": self._process_kind,
                "command": self._process_command,
            },
        )

        self._emit_build_completed({
            "task_id": self._task_id,
            "status": status,
            "exit_code": exit_code,
            "exit_status": str(exit_status),
            "duration_seconds": duration,
            "command": list(self._process_command),
        })

        self._cancel_requested = False
        self._process_started_at = None


    def on_process_error(self, error):

        self.log("\n[ERRO DE PROCESSO] " + str(error))
        self.set_running(False)

        self._publish_event(
            event_type="process_start_or_runtime_error",
            message="Falha no processo ESP-IDF: " + str(error),
            status="error",
            details={
                "process_kind": self._process_kind,
                "process_error": str(error),
                "command": self._process_command,
            },
        )

        if (
            self._process_kind == "build"
            and error == QProcess.ProcessError.FailedToStart
        ):
            duration = (
                time.monotonic() - self._process_started_at
                if self._process_started_at is not None
                else None
            )
            self._emit_build_completed({
                "task_id": self._task_id,
                "status": "error",
                "exit_code": None,
                "exit_status": None,
                "duration_seconds": duration,
                "command": list(self._process_command),
                "process_error": str(error),
            })
            self._process_started_at = None
            self._cancel_requested = False

    def set_running(self, running):

        self.build_button.setEnabled(not running)
        self.clean_button.setEnabled(not running)
        self.flash_button.setEnabled(not running)
        self.stop_button.setEnabled(running)


    def stop_process(self):

        if self.process and (
            self.process.state() != QProcess.ProcessState.NotRunning
        ):
            self._cancel_requested = True

            self._publish_event(
                event_type="process_cancel_requested",
                message="Solicita??o de cancelamento enviada.",
                status="warning",
                details={
                    "process_kind": self._process_kind,
                },
            )

            self.process.terminate()

    def confirm_clean(self):

        answer = QMessageBox.question(
            self,
            "Full Clean",
            "Deseja remover os arquivos de compilação?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No
        )

        if answer == QMessageBox.StandardButton.Yes:
            self.run_idf(["fullclean"])

    def confirm_flash(self):

        answer = QMessageBox.warning(
            self,
            "Gravar firmware",
            "O firmware será gravado no ESP32 conectado. Confirma?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No
        )

        if answer == QMessageBox.StandardButton.Yes:
            self.run_idf(["flash"])

    def closeEvent(self, event):

        if self.serial_worker and self.serial_worker.isRunning():
            self.serial_worker.stop()
            self.serial_worker.wait(1500)

        if self.process and (
            self.process.state() != QProcess.ProcessState.NotRunning
        ):
            self.process.terminate()
            self.process.waitForFinished(1000)

        event.accept()