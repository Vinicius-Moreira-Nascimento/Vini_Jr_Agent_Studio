from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QTabWidget
)
from PySide6.QtCore import QThread, Signal
from interface.chat_panel import ChatPanel
from interface.code_review_panel import CodeReviewPanel
from interface.autonomy_control import AutonomyControl
from interface.api_settings import APISettingsDialog
from embedded.embedded_panel import EmbeddedPanel
from providers.openai_provider import OpenAIProvider
from core.event_manager import EventManager
from interface.live_monitor import LiveMonitor
import json
from pathlib import Path

from autonomy.planning_service import PlanningService
from autonomy.correction_engine import CorrectionEngine
from autonomy.correction_workflow import CorrectionWorkflow
from interface.correction_panel import CorrectionPanel
from autonomy.patch_proposal_service import PatchProposalService
from autonomy.approval_manager import ApprovalManager
from autonomy.correction_applier import CorrectionApplier
from autonomy.backup_manager import BackupManager
from autonomy.autonomous_correction_controller import AutonomousCorrectionController
from execution.compiler import ESPIDFCompiler


class ConnectionWorker(QThread):

    result = Signal(str, bool)

    def __init__(self, api_key, model):
        super().__init__()
        self.api_key = api_key
        self.model = model

    def run(self):
        try:
            provider = OpenAIProvider(self.api_key)
            response = provider.test_connection(self.model)
            self.result.emit(response, True)

        except Exception as error:
            self.result.emit(str(error), False)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("VINI_JR Agent Studio")
        self.resize(1350, 850)

        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #18212F;
                color: #E8EDF5;
                font-size: 13px;
            }

            QPushButton {
                background-color: #2563EB;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 9px 14px;
            }

            QPushButton:hover {
                background-color: #1D4ED8;
            }

            QLineEdit, QTextEdit, QComboBox {
                background-color: #263449;
                color: white;
                border: 1px solid #40516B;
                border-radius: 5px;
                padding: 7px;
            }

            QLabel {
                color: #E8EDF5;
            }

            QTabWidget::pane {
                border: 1px solid #40516B;
                border-radius: 5px;
            }

            QTabBar::tab {
                background-color: #263449;
                color: #E8EDF5;
                padding: 10px 20px;
                margin-right: 3px;
            }

            QTabBar::tab:selected {
                background-color: #2563EB;
            }
        """)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)

        header = QHBoxLayout()

        title = QLabel("VINI_JR AGENT STUDIO")
        title.setStyleSheet(
            "font-size: 22px; font-weight: bold;"
        )

        self.connection = QLabel("● Não conectado")
        self.connection.setStyleSheet("color: #F59E0B;")

        self.config_button = QPushButton("Configurar API")
        self.config_button.clicked.connect(self.open_settings)

        self.test_button = QPushButton("Testar conexão")
        self.test_button.clicked.connect(self.test_connection)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.connection)
        header.addWidget(self.test_button)
        header.addWidget(self.config_button)

        main_layout.addLayout(header)

        self.event_manager = EventManager(parent=self)

        # Serviços de correção são inicializados somente
        # quando o usuário solicitar uma análise.
        self.planning_service = None
        self.correction_engine = None
        self.correction_workflow = None

        self.patch_proposal_service = None
        self.approval_manager = None
        self.backup_manager = None
        self.correction_applier = None
        self.compiler = None
        self.autonomous_correction_controller = None

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)

        chat_page = QWidget()
        chat_layout = QVBoxLayout(chat_page)

        self.chat = ChatPanel()
        self.chat.set_event_manager(self.event_manager)
        chat_layout.addWidget(self.chat, 1)

        self.autonomy = AutonomyControl()
        chat_layout.addWidget(self.autonomy)

        self.autonomy.mode_changed.connect(
            self.save_autonomy_mode
        )

        self.tabs.addTab(chat_page, "VINI_JR Agent")

        self.embedded = EmbeddedPanel()
        self.embedded.set_event_manager(self.event_manager)

        self.chat.set_project_path_provider(
            lambda: self.embedded.project_path.text().strip()
        )

        self.tabs.addTab(
            self.embedded,
            "Embedded Development"
        )

        self.code_review = CodeReviewPanel()
        self.code_review.set_event_manager(self.event_manager)

        self.code_review.set_project_path_provider(
            lambda: self.embedded.project_path.text().strip()
        )

        self.tabs.addTab(
            self.code_review,
            "Code Review"
        )

        self.correction_panel = CorrectionPanel(
            workflow_factory=self.create_correction_workflow
        )

        self.tabs.addTab(
            self.correction_panel,
            "Correction Center"
        )
        self.live_monitor = LiveMonitor(self.event_manager)
        self.tabs.addTab(self.live_monitor, "Live Monitor")

        self.load_autonomy_mode()

        self.worker = None

    def create_correction_workflow(self):
        """
        Comp?e os servi?os de corre??o sob demanda.

        O firmware ? obtido exclusivamente do EmbeddedPanel.
        Esta etapa prepara propostas e aprova??es, mas n?o aplica
        altera??es automaticamente.
        """

        project_path = self.embedded.validate_project()

        if not project_path:
            raise ValueError(
                "Selecione um projeto ESP-IDF v?lido na aba "
                "Embedded Development."
            )

        project_root = Path(project_path).expanduser().resolve(strict=True)
        app_root = Path(__file__).resolve().parent.parent

        planning_service = PlanningService(
            app_root=app_root,
            project_root=project_root,
        )

        correction_engine = CorrectionEngine(
            planning_service=planning_service,
            event_manager=self.event_manager,
        )

        patch_proposal_service = PatchProposalService(
            provider=planning_service.provider,
            model=planning_service.model,
            project_root=project_root,
        )

        approval_manager = ApprovalManager(
            event_manager=self.event_manager,
        )

        backup_manager = BackupManager()

        correction_applier = CorrectionApplier(
            approval_manager=approval_manager,
            event_manager=self.event_manager,
            backup_manager=backup_manager,
        )

        workflow = CorrectionWorkflow(
            correction_engine=correction_engine,
            parent=self,
            patch_proposal_service=patch_proposal_service,
            approval_manager=approval_manager,
        )

        self.planning_service = planning_service
        self.correction_engine = correction_engine
        self.patch_proposal_service = patch_proposal_service
        self.approval_manager = approval_manager
        self.backup_manager = backup_manager
        self.correction_applier = correction_applier
        self.correction_workflow = workflow

        return workflow

    def create_autonomous_correction_controller(self):
        """
        Cria sob demanda o controlador de autonomia para o workflow atual.

        A criação não inicia correções nem executa Build. A sessão só começa
        quando a interface solicitar start_session() após autorização explícita.
        """

        workflow = self.correction_workflow
        correction_applier = self.correction_applier

        if workflow is None or correction_applier is None:
            raise RuntimeError(
                "Inicialize primeiro o Centro de Correções e seus serviços."
            )

        project_path = self.embedded.validate_project()
        if not project_path:
            raise ValueError(
                "Selecione um projeto ESP-IDF válido na aba Embedded Development."
            )

        project_root = Path(project_path).expanduser().resolve(strict=True)
        current = self.autonomous_correction_controller

        if current is not None:
            if current.is_active:
                if current.workflow is workflow and current.root == project_root:
                    return current
                raise RuntimeError(
                    "Já existe uma sessão de autonomia ativa. "
                    "Finalize ou cancele antes de trocar o projeto/workflow."
                )

            if current.workflow is workflow and current.root == project_root:
                return current

            current.deleteLater()

        app_root = Path(__file__).resolve().parent.parent
        compiler = ESPIDFCompiler(
            config_path=app_root / "config" / "embedded.json"
        )

        controller = AutonomousCorrectionController(
            workflow=workflow,
            correction_applier=correction_applier,
            compiler=compiler,
            project_root=project_root,
            parent=self,
        )

        self.compiler = compiler
        self.autonomous_correction_controller = controller
        return controller

    def open_settings(self):

        dialog = APISettingsDialog(self)
        dialog.exec()

    def test_connection(self):

        with open(
            "config/providers.json",
            "r",
            encoding="utf-8-sig"
        ) as file:
            config = json.load(file)

        with open(
            "config/settings.json",
            "r",
            encoding="utf-8-sig"
        ) as file:
            settings = json.load(file)

        api_key = config["openai"].get("api_key", "")

        if not api_key:
            QMessageBox.warning(
                self,
                "VINI_JR",
                "Configure sua API Key primeiro."
            )
            return

        self.connection.setText("● Testando...")
        self.test_button.setEnabled(False)

        self.worker = ConnectionWorker(
            api_key,
            settings.get("model", "gpt-4.1-mini")
        )

        self.worker.result.connect(self.on_connection_result)
        self.worker.start()

    def on_connection_result(self, result, success):

        self.test_button.setEnabled(True)

        if success:
            self.connection.setText("● Conectado")
            self.connection.setStyleSheet("color: #22C55E;")

            QMessageBox.information(
                self,
                "VINI_JR",
                result
            )
        else:
            self.connection.setText("● Falha na conexão")
            self.connection.setStyleSheet("color: #EF4444;")

            QMessageBox.critical(
                self,
                "Erro de conexão",
                result
            )

    def load_autonomy_mode(self):

        with open(
            "config/settings.json",
            "r",
            encoding="utf-8-sig"
        ) as file:
            settings = json.load(file)

        mode = settings.get("autonomy_mode", "manual")
        index = self.autonomy.mode.findData(mode)

        if index >= 0:
            self.autonomy.mode.setCurrentIndex(index)

    def save_autonomy_mode(self, mode):

        path = "config/settings.json"

        with open(
            path,
            "r",
            encoding="utf-8-sig"
        ) as file:
            settings = json.load(file)

        settings["autonomy_mode"] = mode

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(settings, file, indent=4)

        self.statusBar().showMessage(
            f"Modo de autonomia: {mode}"
        )