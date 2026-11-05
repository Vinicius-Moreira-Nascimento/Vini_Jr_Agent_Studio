from pathlib import Path
import hashlib
import json
import re
import shutil
from datetime import datetime

root = Path(r"C:\Users\pasta\Desktop\Vini_Jr_Agent_Studio")
path = root / "interface" / "code_review_panel.py"

raw = path.read_bytes()
has_bom = raw.startswith(b"\xef\xbb\xbf")
encoding = "utf-8-sig" if has_bom else "utf-8"
source = raw.decode(encoding)
newline = "\r\n" if b"\r\n" in raw else "\n"
source = source.replace("\r\n", "\n")

if "class FixProposalWorker" in source:
    raise SystemExit("A integracao de correcao por IA ja parece existir. Nenhuma alteracao foi feita.")

backup = path.with_name("code_review_panel.py.backup_ai_fix")
if not backup.exists():
    shutil.copy2(path, backup)

def replace_once(old, new, label):
    global source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"Trecho '{label}' encontrado {count} vezes. "
            "Arquivo principal nao foi gravado."
        )
    source = source.replace(old, new, 1)

replace_once(
    "from pathlib import Path",
    "from pathlib import Path\nimport hashlib\nimport json\nimport re\nimport shutil\nfrom datetime import datetime",
    "imports padrao"
)
replace_once(
    "    QSplitter, QPlainTextEdit, QTextEdit, QMessageBox",
    "    QSplitter, QPlainTextEdit, QTextEdit, QMessageBox,\n"
    "    QDialog, QDialogButtonBox",
    "imports QtWidgets"
)
replace_once(
    "from PySide6.QtCore import Qt, QRect, QSize",
    "from PySide6.QtCore import Qt, QRect, QSize, QThread, Signal",
    "imports QtCore"
)
replace_once(
    "from project_engine.project_context import build_project_context",
    '''from project_engine.project_context import build_project_context
from providers.openai_provider import OpenAIProvider


class FixProposalWorker(QThread):
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, api_key, model, finding, source_text):
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.finding = finding
        self.source_text = source_text

    def run(self):
        try:
            provider = OpenAIProvider(self.api_key)
            prompt = {
                "diagnostico": self.finding,
                "arquivo_completo": self.source_text,
                "instrucoes": [
                    "Analise o diagnostico e o arquivo.",
                    "Proponha uma unica correcao localizada.",
                    "Nao reescreva o arquivo inteiro.",
                    "original_snippet deve ser copiado literalmente do codigo.",
                    "replacement_snippet deve conter a substituicao completa.",
                    "Nao use reticencias nem omita linhas.",
                    "Se nao houver correcao segura, applicable=false.",
                    "Responda somente JSON valido, sem Markdown.",
                    "Campos: applicable (boolean), original_snippet (string), "
                    "replacement_snippet (string), explanation (string)."
                ]
            }
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Voce e um engenheiro de firmware C/C++. "
                        "Proponha alteracoes minimas e justificadas. "
                        "Nunca invente trechos do arquivo."
                    )
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False)
                }
            ]
            response = provider.send_message(messages, self.model).strip()
            response = re.sub(
                r"^```(?:json)?\s*|\s*```$",
                "",
                response,
                flags=re.IGNORECASE
            ).strip()
            result = json.loads(response)
            if not isinstance(result, dict):
                raise ValueError("A resposta da IA nao e um objeto JSON.")
            if not isinstance(result.get("applicable"), bool):
                raise ValueError("Campo applicable ausente ou invalido.")
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class CodeReviewPanel(QWidget):''',
    "worker IA"
)

replace_once(
    "        self.findings = []",
    "        self.findings = []\n"
    "        self.current_finding = None\n"
    "        self.current_file_path = None\n"
    "        self.original_file_text = None\n"
    "        self.original_file_hash = None\n"
    "        self.pending_proposal = None\n"
    "        self.fix_worker = None",
    "estado inicial"
)
replace_once(
    "        self.detail_label.setWordWrap(True)",
    "        self.detail_label.setWordWrap(True)\n\n"
    "        self.propose_button = QPushButton(\"Propor correcao com IA\")\n"
    "        self.propose_button.setEnabled(False)\n"
    "        self.propose_button.clicked.connect(self.propose_fix)",
    "botao IA"
)
replace_once(
    "        right_layout.addWidget(self.detail_label)",
    "        right_layout.addWidget(self.detail_label)\n"
    "        right_layout.addWidget(self.propose_button)",
    "posicao do botao"
)

methods = r'''
    def propose_fix(self):
        if not self.current_finding or not self.current_file_path:
            QMessageBox.warning(self, "Correcao", "Selecione um diagnostico primeiro.")
            return
        if self.fix_worker and self.fix_worker.isRunning():
            return

        answer = QMessageBox.question(
            self,
            "Enviar codigo para OpenAI",
            "O diagnostico e o conteudo do arquivo selecionado serao enviados "
            "a OpenAI para gerar uma proposta.\n\n"
            "Verifique se o codigo nao contem senhas, tokens, chaves "
            "ou informacoes confidenciais. Deseja continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            project_root = Path(self.current_project).resolve()
            target = self.current_file_path.resolve()
            target.relative_to(project_root)

            current_bytes = target.read_bytes()
            current_hash = hashlib.sha256(current_bytes).hexdigest()
            if current_hash != self.original_file_hash:
                raise RuntimeError("O arquivo foi alterado desde a analise. Execute novamente a analise.")

            try:
                current_text = current_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                current_text = current_bytes.decode("latin-1")

            config = json.loads(Path("config/providers.json").read_text(encoding="utf-8-sig"))
            settings = json.loads(Path("config/settings.json").read_text(encoding="utf-8-sig"))
            api_key = config.get("openai", {}).get("api_key", "")
            model = settings.get("model", "gpt-4.1-mini")
            if not api_key:
                raise ValueError("Configure a API Key da OpenAI.")

            self.proposal_target = target
            self.proposal_root = project_root
            self.proposal_source = current_text
            self.proposal_hash = current_hash
            self.proposal_bytes = current_bytes

            self.propose_button.setEnabled(False)
            self.status.setText("Solicitando proposta a OpenAI...")
            self.fix_worker = FixProposalWorker(api_key, model, dict(self.current_finding), current_text)
            self.fix_worker.completed.connect(self.on_fix_proposed)
            self.fix_worker.failed.connect(self.on_fix_error)
            self.fix_worker.start()
        except Exception as exc:
            self.propose_button.setEnabled(True)
            QMessageBox.critical(self, "Erro", str(exc))

    def on_fix_error(self, error):
        self.propose_button.setEnabled(True)
        self.status.setText("Falha ao gerar proposta.")
        QMessageBox.critical(self, "Erro na proposta de correcao", error)

    def on_fix_proposed(self, proposal):
        self.propose_button.setEnabled(True)
        if not proposal.get("applicable", False):
            QMessageBox.information(
                self, "Sem correcao segura",
                str(proposal.get("explanation", "A IA nao encontrou uma substituicao segura."))
            )
            return

        original = proposal.get("original_snippet")
        replacement = proposal.get("replacement_snippet")
        explanation = proposal.get("explanation", "")
        if not isinstance(original, str) or not isinstance(replacement, str):
            QMessageBox.warning(self, "Proposta invalida", "A IA nao retornou os trechos como texto.")
            return
        if not original or not replacement or original == replacement:
            QMessageBox.warning(self, "Proposta invalida", "Os trechos estao vazios ou sao identicos.")
            return
        if self.proposal_source.count(original) != 1:
            QMessageBox.warning(
                self, "Proposta ambigua",
                "O trecho original nao aparece exatamente uma vez. A aplicacao foi bloqueada."
            )
            return

        self.pending_proposal = {
            "original": original, "replacement": replacement,
            "explanation": str(explanation), "file_hash": self.proposal_hash,
            "target": self.proposal_target, "root": self.proposal_root
        }

        dialog = QDialog(self)
        dialog.setWindowTitle("Comparacao da proposta de correcao")
        dialog.resize(1100, 650)
        layout = QVBoxLayout(dialog)
        explanation_label = QLabel(str(explanation))
        explanation_label.setWordWrap(True)
        layout.addWidget(explanation_label)

        comparison = QSplitter(Qt.Orientation.Horizontal)
        original_panel = QWidget()
        original_layout = QVBoxLayout(original_panel)
        original_layout.addWidget(QLabel("TRECHO ORIGINAL"))
        original_editor = QPlainTextEdit()
        original_editor.setReadOnly(True)
        original_editor.setPlainText(original)
        original_layout.addWidget(original_editor)

        replacement_panel = QWidget()
        replacement_layout = QVBoxLayout(replacement_panel)
        replacement_layout.addWidget(QLabel("TRECHO SUGERIDO"))
        replacement_editor = QPlainTextEdit()
        replacement_editor.setReadOnly(True)
        replacement_editor.setPlainText(replacement)
        replacement_layout.addWidget(replacement_editor)

        comparison.addWidget(original_panel)
        comparison.addWidget(replacement_panel)
        layout.addWidget(comparison, 1)

        buttons = QDialogButtonBox()
        apply_button = buttons.addButton("Aprovar e aplicar", QDialogButtonBox.ButtonRole.AcceptRole)
        reject_button = buttons.addButton("Rejeitar", QDialogButtonBox.ButtonRole.RejectRole)
        apply_button.clicked.connect(dialog.accept)
        reject_button.clicked.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_fix()
        else:
            self.pending_proposal = None
            self.status.setText("Proposta rejeitada.")

    def apply_fix(self):
        proposal = self.pending_proposal
        if not proposal:
            return
        try:
            target = Path(proposal["target"]).resolve()
            root = Path(proposal["root"]).resolve()
            target.relative_to(root)

            current_bytes = target.read_bytes()
            if hashlib.sha256(current_bytes).hexdigest() != proposal["file_hash"]:
                raise RuntimeError("O arquivo mudou desde a proposta. A aplicacao foi bloqueada.")

            try:
                current_text = current_bytes.decode("utf-8-sig")
                has_bom = current_bytes.startswith(b"\xef\xbb\xbf")
                output_encoding = "utf-8"
            except UnicodeDecodeError:
                current_text = current_bytes.decode("latin-1")
                has_bom = False
                output_encoding = "latin-1"

            original = proposal["original"]
            replacement = proposal["replacement"]
            if current_text.count(original) != 1:
                raise RuntimeError("O trecho original nao esta presente exatamente uma vez.")

            updated_text = current_text.replace(original, replacement, 1)
            backup = target.with_name(target.name + ".vini_jr.bak")
            if backup.exists():
                backup = target.with_name(
                    target.name + ".vini_jr." + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".bak"
                )
            shutil.copy2(target, backup)

            output_bytes = updated_text.encode(output_encoding)
            if has_bom:
                output_bytes = b"\xef\xbb\xbf" + output_bytes

            temp = target.with_name(target.name + ".vini_jr.tmp")
            try:
                temp.write_bytes(output_bytes)
                temp.replace(target)
            finally:
                if temp.exists():
                    temp.unlink()

            self.pending_proposal = None
            QMessageBox.information(
                self, "Correcao aplicada",
                "A alteracao foi aplicada.\n"
                f"Backup criado em:\n{backup}\n\n"
                "Execute novamente a analise e a compilacao para validar."
            )
            self.analyze_project()
        except Exception as exc:
            QMessageBox.critical(self, "Alteracao bloqueada", str(exc))

    def open_finding(self, current, previous=None):
'''
replace_once(
    "    def open_finding(self, current, previous=None):",
    methods,
    "metodos de correcao"
)

replace_once(
    "        finding = self.findings[index]",
    "        finding = self.findings[index]\n"
    "        self.current_finding = finding\n"
    "        self.pending_proposal = None",
    "diagnostico selecionado"
)
replace_once(
    "            self.editor.setPlainText(source)",
    "            self.current_file_path = target\n"
    "            self.original_file_text = source\n"
    "            self.original_file_hash = hashlib.sha256(target.read_bytes()).hexdigest()\n"
    "            self.propose_button.setEnabled(True)\n"
    "            self.editor.setPlainText(source)",
    "guardar arquivo"
)

if newline == "\r\n":
    source = source.replace("\n", "\r\n")
output = source.encode("utf-8")
if has_bom:
    output = b"\xef\xbb\xbf" + output

compile(source, str(path), "exec")
temp_path = path.with_name(path.name + ".install_tmp")
temp_path.write_bytes(output)
temp_path.replace(path)

print("Correcao assistida integrada e validada.")
print("Backup:", backup)
