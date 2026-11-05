from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QHBoxLayout,
    QMessageBox
)
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QTextCursor
from uuid import uuid4

from providers.openai_provider import OpenAIProvider
from project_engine.project_context import (
    build_project_context,
    format_project_context
)

import json
import os


class AIWorker(QThread):

    finished_response = Signal(str)
    error_response = Signal(str)
    stream_received = Signal(str)

    def __init__(
        self,
        api_key,
        model,
        messages,
        event_manager=None,
        task_id=None
    ):
        super().__init__()

        self.api_key = api_key
        self.model = model
        self.messages = messages
        self.event_manager = event_manager
        self.task_id = task_id or uuid4().hex

    def _publish(self, event_type, message, status, details=None):

        if self.event_manager is None:
            return

        self.event_manager.publish(
            category="ai",
            event_type=event_type,
            message=message,
            status=status,
            source="OpenAIProvider",
            task_id=self.task_id,
            details=details or {}
        )

    def run(self):

        try:
            provider = OpenAIProvider(self.api_key)

            self._publish(
                "request_started",
                "Solicitação enviada à OpenAI.",
                "running",
                {"model": self.model}
            )

            parts = []
            first_delta = False

            for delta in provider.stream_message(
                self.messages,
                self.model
            ):

                if not delta:
                    continue

                parts.append(delta)
                self.stream_received.emit(delta)

                if not first_delta:
                    first_delta = True

                    self._publish(
                        "first_content_received",
                        "A OpenAI começou a transmitir a resposta.",
                        "running"
                    )

            result = "".join(parts)

            self._publish(
                "request_completed",
                "Resposta da OpenAI recebida integralmente.",
                "success",
                {"characters": len(result)}
            )

            self.finished_response.emit(result)

        except Exception as error:

            self._publish(
                "request_failed",
                "A solicitação à OpenAI falhou.",
                "error",
                {"error": str(error)}
            )

            self.error_response.emit(str(error))


class ChatPanel(QWidget):

    def __init__(self):
        super().__init__()

        self.messages = [
            {
                "role": "system",
                "content": (
                    "Voce e VINI_JR, um agente de "
                    "programacao. Responda em portugues, "
                    "com clareza e foco tecnico. "
                    "Quando receber contexto de projeto, "
                    "baseie suas respostas nos arquivos "
                    "fornecidos. Diferencie fatos do codigo "
                    "de inferencias. Nunca invente trechos "
                    "ou comportamentos que nao estejam "
                    "demonstrados no contexto."
                )
            }
        ]

        self.project_path_provider = None
        self.project_context_text = ""
        self.event_manager = None
        self.current_response_text = ""

        layout = QVBoxLayout(self)

        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("Conversacao com VINI_JR")
        layout.addWidget(self.chat)

        project_controls = QHBoxLayout()

        self.analyze_button = QPushButton("Analisar projeto")
        self.analyze_button.clicked.connect(
            self.load_project_context
        )

        self.clear_context_button = QPushButton(
            "Remover contexto"
        )
        self.clear_context_button.clicked.connect(
            self.clear_project_context
        )

        project_controls.addWidget(self.analyze_button)
        project_controls.addWidget(self.clear_context_button)
        project_controls.addStretch()

        layout.addLayout(project_controls)

        bottom = QHBoxLayout()

        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "Digite sua solicitacao..."
        )
        self.input.returnPressed.connect(self.send_message)

        self.send = QPushButton("Enviar")
        self.send.clicked.connect(self.send_message)

        bottom.addWidget(self.input)
        bottom.addWidget(self.send)

        layout.addLayout(bottom)

        self.worker = None

    def set_project_path_provider(self, provider):
        self.project_path_provider = provider

    def set_event_manager(self, event_manager):
        self.event_manager = event_manager

    def load_project_context(self):

        import html

        if not self.project_path_provider:
            QMessageBox.warning(
                self,
                "Projeto",
                "O caminho do projeto ainda nao foi configurado."
            )
            return

        project = self.project_path_provider()

        if not project:
            QMessageBox.warning(
                self,
                "Projeto",
                "Selecione primeiro um projeto na aba Embedded Development."
            )
            return

        self.analyze_button.setEnabled(False)

        try:
            context = build_project_context(project)
            context_text = format_project_context(context)

            analysis = context["analysis"]
            static = context["static_analysis"]
            findings = static["findings"]

            report = [
                f"Projeto: {project}",
                f"Arquivos encontrados: {context['total_files_found']}",
                f"Arquivos lidos: {context['files_read']}",
                f"Funcoes identificadas: {len(analysis['functions'])}",
                f"APIs de tarefas: {analysis['task_apis']}",
                f"Perifericos: {list(analysis['peripherals'].keys())}",
                "",
                "DIAGNOSTICO ESTATICO",
                f"Arquivos C/C++ analisados: {static['files_analyzed']}",
                f"Achados: {static['total_findings']}",
                f"Erros: {static['counts']['error']}",
                f"Warnings: {static['counts']['warning']}",
                f"Informativos: {static['counts']['info']}"
            ]

            self.chat.append(
                "<br><b>VINI_JR - Analise local do projeto:</b>"
            )

            self.chat.append(
                "<pre>" + html.escape("\n".join(report)) + "</pre>"
            )

            if findings:
                self.chat.append(
                    "<b>Diagnosticos encontrados:</b>"
                )

                for index, finding in enumerate(findings, 1):
                    details = [
                        f"#{index} - {finding['title']}",
                        f"Regra: {finding['rule']}",
                        f"Severidade: {finding['severity']}",
                        f"Arquivo: {finding['file']}",
                        f"Linha: {finding['line']}",
                        f"Evidencia: {finding['evidence']}",
                        f"Declaracao: {finding.get('declaration', 'N/A')}",
                        f"Recomendacao: {finding['recommendation']}",
                        f"Confianca heuristica: {finding['confidence']}"
                    ]

                    self.chat.append(
                        "<pre>" + html.escape(
                            "\n".join(details)
                        ) + "</pre>"
                    )
            else:
                self.chat.append(
                    "Nenhum achado foi identificado pelas regras atuais."
                )

            self.chat.append(
                "<i>Os diagnosticos sao heuristicas e precisam "
                "de revisao tecnica.</i>"
            )

            answer = QMessageBox.question(
                self,
                "Compartilhar contexto com a OpenAI?",
                "\n".join(report)
                + "\n\nOs arquivos de codigo e os diagnosticos "
                "serao enviados a API OpenAI se voce aceitar."
                + "\nVerifique se nao existem senhas, tokens "
                "ou informacoes confidenciais."
                + "\n\nDeseja carregar esse contexto no chat?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No
            )

            if answer == QMessageBox.StandardButton.Yes:
                self.project_context_text = context_text

                self.chat.append(
                    "<b>VINI_JR:</b> Contexto carregado. "
                    "Os diagnosticos locais estao disponiveis "
                    "para consulta pela IA."
                )
            else:
                self.project_context_text = ""

                self.chat.append(
                    "<b>VINI_JR:</b> Contexto nao enviado "
                    "a OpenAI. A analise local foi concluida."
                )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Erro na analise",
                str(error)
            )

        finally:
            self.analyze_button.setEnabled(True)

    def clear_project_context(self):
        self.project_context_text = ""

        self.chat.append(
            "<b>VINI_JR:</b> Contexto do projeto removido."
        )

    def send_message(self):

        text = self.input.text().strip()

        if not text:
            return

        if self.worker and self.worker.isRunning():
            return

        api_path = os.path.join("config", "providers.json")
        settings_path = os.path.join("config", "settings.json")

        with open(api_path, "r", encoding="utf-8-sig") as file:
            config = json.load(file)

        with open(settings_path, "r", encoding="utf-8-sig") as file:
            settings = json.load(file)

        api_key = config["openai"].get("api_key", "")
        model = settings.get("model", "gpt-4.1-mini")

        if not api_key:
            self.chat.append(
                "<b>VINI_JR:</b> Configure sua API Key primeiro."
            )
            return

        self.chat.append(f"<b>Voce:</b> {text}")
        self.input.clear()
        self.send.setEnabled(False)

        self.messages.append({
            "role": "user",
            "content": text
        })

        request_messages = self.messages.copy()

        if self.project_context_text:
            request_messages.insert(
                1,
                {
                    "role": "system",
                    "content": self.project_context_text
                }
            )

        self.current_response_text = ""
        self.current_task_id = uuid4().hex

        self.chat.append("<b>VINI_JR:</b>")

        self.chat.moveCursor(QTextCursor.MoveOperation.End)
        self.chat.insertPlainText(" ")

        self.worker = AIWorker(
            api_key,
            model,
            request_messages,
            self.event_manager,
            self.current_task_id
        )

        self.worker.stream_received.connect(
            self.on_stream_chunk
        )

        self.worker.finished_response.connect(self.on_response)
        self.worker.error_response.connect(self.on_error)
        self.worker.start()

    def on_stream_chunk(self, chunk):

        self.current_response_text += chunk

        cursor = self.chat.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        self.chat.setTextCursor(cursor)
        self.chat.insertPlainText(chunk)
        self.chat.ensureCursorVisible()

    def on_response(self, response):

        # Evita duplicar o texto que já chegou pelo streaming.
        if not self.current_response_text:
            self.chat.moveCursor(QTextCursor.MoveOperation.End)
            self.chat.insertPlainText(response)

        self.chat.append("")

        self.messages.append({
            "role": "assistant",
            "content": response
        })

        self.send.setEnabled(True)

    def on_error(self, error):

        self.chat.append(
            f"<b>Erro na API:</b> {error}"
        )

        if self.messages and self.messages[-1]["role"] == "user":
            self.messages.pop()

        self.send.setEnabled(True)