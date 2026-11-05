from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QListWidget,
    QGroupBox,
    QSplitter,
    QPlainTextEdit,
    QComboBox,
    QMessageBox,
    QScrollArea,
)


class CorrectionPanel(QWidget):
    """
    Interface de análise, propostas e correção autônoma supervisionada.

    A sessão autônoma exige autorização explícita, aprovação humana da
    primeira proposta e limita as tentativas ao arquivo selecionado.
    Somente Build é permitido; Full Clean e Flash permanecem bloqueados.
    """

    AVAILABLE_STATES = {
        "idle": "Aguardando análise",
        "analyzing": "Analisando projeto e elaborando plano...",
        "awaiting_approval": "Plano recebido. Selecione uma ação e um arquivo.",
        "applying": "Aplicação não habilitada nesta interface.",
        "building": "Build não habilitado nesta interface.",
        "completed": "Processo concluído.",
        "failed": "Falha durante o processo.",
        "cancelled": "Processo cancelado.",
    }

    STATUS_LABELS = {
        "pending": "Aguardando decisão",
        "approved": "Aprovada — ainda não aplicada",
        "rejected": "Rejeitada",
        "expired": "Expirada",
        "consumed": "Consumida",
    }

    def __init__(self, workflow=None, workflow_factory=None, parent=None):
        super().__init__(parent)

        if workflow is None and workflow_factory is None:
            raise ValueError("Informe um workflow ou uma factory.")

        if workflow_factory is not None and not callable(workflow_factory):
            raise TypeError("workflow_factory precisa ser callable.")

        self.workflow = None
        self.workflow_factory = workflow_factory
        self._proposals = {}
        self._autonomy_controller = None
        self._build_ui()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self.refresh_proposal_status)

        if workflow is not None:
            self.set_workflow(workflow)
        else:
            self._on_state_changed("idle")

    def set_workflow(self, workflow):
        if self.workflow is not None:
            if self.workflow is workflow:
                return
            raise RuntimeError("O painel já possui um workflow associado.")

        required_signals = (
            "state_changed",
            "analysis_started",
            "plan_ready",
            "failed",
            "proposal_ready",
            "proposal_started",
            "proposal_failed",
        )
        for signal_name in required_signals:
            if not hasattr(workflow, signal_name):
                raise TypeError(
                    f"Workflow não possui o sinal obrigatório: {signal_name}"
                )

        required_methods = (
            "start_analysis",
            "request_patch_proposal_async",
        )
        for method_name in required_methods:
            if not callable(getattr(workflow, method_name, None)):
                raise TypeError(
                    f"Workflow precisa implementar {method_name}()."
                )

        self.workflow = workflow

        workflow.state_changed.connect(self._on_state_changed)
        workflow.analysis_started.connect(self._on_analysis_started)
        workflow.plan_ready.connect(self._on_plan_ready)
        workflow.failed.connect(self._on_failed)
        workflow.proposal_started.connect(self._on_proposal_started)
        workflow.proposal_ready.connect(self._on_proposal_ready)
        workflow.proposal_failed.connect(self._on_proposal_failed)

        current_state = getattr(workflow, "state", "idle")
        self._on_state_changed(getattr(current_state, "value", current_state))
        self._update_proposal_controls()

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("correctionScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.content_widget = QWidget()
        self.content_widget.setObjectName("correctionContent")
        layout = QVBoxLayout(self.content_widget)

        header = QHBoxLayout()
        title = QLabel("VINI_JR - CORREÇÃO INTELIGENTE")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        objective_label = QLabel("Objetivo da análise")
        self.objective_input = QLineEdit()
        self.objective_input.setObjectName("correctionObjective")
        self.objective_input.setText(
            "Analisar o firmware, identificar problemas "
            "e elaborar um plano de correção."
        )

        self.start_button = QPushButton("Iniciar análise")
        self.start_button.setObjectName("startCorrectionAnalysis")
        self.start_button.clicked.connect(self.start_analysis)

        objective_layout = QHBoxLayout()
        objective_layout.addWidget(self.objective_input, 1)
        objective_layout.addWidget(self.start_button)
        layout.addWidget(objective_label)
        layout.addLayout(objective_layout)

        self.status_label = QLabel("Aguardando análise.")
        self.status_label.setObjectName("correctionStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Vertical)

        summary_group = QGroupBox("RESUMO DO PLANO")
        summary_layout = QVBoxLayout(summary_group)
        self.summary = QPlainTextEdit()
        self.summary.setObjectName("correctionSummary")
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText(
            "O resumo do planejamento aparecerá aqui."
        )
        summary_layout.addWidget(self.summary)
        splitter.addWidget(summary_group)

        details_widget = QWidget()
        details_layout = QHBoxLayout(details_widget)

        self.findings_list = self._create_list(
            "ACHADOS IDENTIFICADOS", "correctionFindings"
        )
        self.actions_list = self._create_list(
            "AÇÕES PLANEJADAS", "correctionActions"
        )
        self.risks_list = self._create_list(
            "RISCOS IDENTIFICADOS", "correctionRisks"
        )

        details_layout.addWidget(self.findings_list)
        details_layout.addWidget(self.actions_list)
        details_layout.addWidget(self.risks_list)

        splitter.addWidget(details_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        selection_group = QGroupBox("GERAÇÃO DE PROPOSTA")
        selection_layout = QVBoxLayout(selection_group)

        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("Ação:"))
        self.action_selector = QComboBox()
        self.action_selector.setObjectName("correctionActionSelector")
        self.action_selector.currentIndexChanged.connect(
            self._on_action_selected
        )
        action_row.addWidget(self.action_selector, 1)

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("Arquivo:"))
        self.file_selector = QComboBox()
        self.file_selector.setObjectName("correctionFileSelector")
        file_row.addWidget(self.file_selector, 1)

        self.generate_button = QPushButton("Gerar proposta")
        self.generate_button.setObjectName("generateCorrectionProposal")
        self.generate_button.clicked.connect(self.generate_proposal)

        selection_layout.addLayout(action_row)
        selection_layout.addLayout(file_row)
        selection_layout.addWidget(self.generate_button)
        layout.addWidget(selection_group)

        proposal_group = QGroupBox("PROPOSTAS E DECISÃO")
        proposal_layout = QVBoxLayout(proposal_group)

        proposal_row = QHBoxLayout()
        proposal_row.addWidget(QLabel("Proposta:"))
        self.proposal_selector = QComboBox()
        self.proposal_selector.setObjectName("correctionProposalSelector")
        self.proposal_selector.currentIndexChanged.connect(
            self._on_proposal_selected
        )
        proposal_row.addWidget(self.proposal_selector, 1)
        proposal_layout.addLayout(proposal_row)

        self.proposal_status_label = QLabel(
            "Nenhuma proposta gerada."
        )
        self.proposal_status_label.setObjectName("proposalStatus")
        self.proposal_status_label.setWordWrap(True)
        proposal_layout.addWidget(self.proposal_status_label)

        self.proposal_explanation = QPlainTextEdit()
        self.proposal_explanation.setObjectName("proposalExplanation")
        self.proposal_explanation.setReadOnly(True)
        self.proposal_explanation.setMaximumHeight(90)
        self.proposal_explanation.setPlaceholderText(
            "A explicação da proposta aparecerá aqui."
        )
        proposal_layout.addWidget(QLabel("Explicação"))
        proposal_layout.addWidget(self.proposal_explanation)

        snippets_layout = QHBoxLayout()

        original_group = QGroupBox("TRECHO ORIGINAL")
        original_layout = QVBoxLayout(original_group)
        self.original_snippet = QPlainTextEdit()
        self.original_snippet.setObjectName("proposalOriginalSnippet")
        self.original_snippet.setReadOnly(True)
        original_layout.addWidget(self.original_snippet)

        replacement_group = QGroupBox("SUBSTITUIÇÃO PROPOSTA")
        replacement_layout = QVBoxLayout(replacement_group)
        self.replacement_snippet = QPlainTextEdit()
        self.replacement_snippet.setObjectName("proposalReplacementSnippet")
        self.replacement_snippet.setReadOnly(True)
        replacement_layout.addWidget(self.replacement_snippet)

        snippets_layout.addWidget(original_group)
        snippets_layout.addWidget(replacement_group)
        proposal_layout.addLayout(snippets_layout)

        decision_row = QHBoxLayout()
        self.approve_button = QPushButton("Aprovar proposta")
        self.approve_button.setObjectName("approveCorrectionProposal")
        self.approve_button.clicked.connect(self.approve_selected_proposal)

        self.reject_button = QPushButton("Rejeitar proposta")
        self.reject_button.setObjectName("rejectCorrectionProposal")
        self.reject_button.clicked.connect(self.reject_selected_proposal)

        decision_row.addWidget(self.approve_button)
        decision_row.addWidget(self.reject_button)
        proposal_layout.addLayout(decision_row)

        autonomy_group = QGroupBox("CICLO DE CORREÇÃO AUTÔNOMA")
        autonomy_layout = QVBoxLayout(autonomy_group)

        self.autonomy_scope_label = QLabel(
            "Escopo autorizado: um único arquivo selecionado."
        )
        self.autonomy_scope_label.setWordWrap(True)
        autonomy_layout.addWidget(self.autonomy_scope_label)

        self.autonomy_status_label = QLabel(
            "Aguardando autorização explícita para iniciar."
        )
        self.autonomy_status_label.setObjectName("autonomyCorrectionStatus")
        self.autonomy_status_label.setWordWrap(True)
        autonomy_layout.addWidget(self.autonomy_status_label)

        autonomy_buttons = QHBoxLayout()
        self.start_autonomy_button = QPushButton(
            "Autorizar e iniciar até 3 tentativas"
        )
        self.start_autonomy_button.setObjectName("startAutonomousCorrection")
        self.start_autonomy_button.clicked.connect(
            self.start_autonomous_correction
        )

        self.cancel_autonomy_button = QPushButton("Cancelar sessão")
        self.cancel_autonomy_button.setObjectName("cancelAutonomousCorrection")
        self.cancel_autonomy_button.setEnabled(False)
        self.cancel_autonomy_button.clicked.connect(
            self.cancel_autonomous_correction
        )

        autonomy_buttons.addWidget(self.start_autonomy_button)
        autonomy_buttons.addWidget(self.cancel_autonomy_button)
        autonomy_layout.addLayout(autonomy_buttons)
        proposal_layout.addWidget(autonomy_group)

        layout.addWidget(proposal_group)

        self.notice_label = QLabel(
            "Segurança: sem autorização, nenhuma alteração ou Build. "
            "Na sessão autorizada, somente Build é permitido. "
            "Full Clean e Flash permanecem bloqueados."
        )
        self.notice_label.setWordWrap(True)
        self.notice_label.setStyleSheet(
            "color: #FBBF24; font-weight: bold;"
        )
        layout.addWidget(self.notice_label)

        self.scroll_area.setWidget(self.content_widget)
        outer_layout.addWidget(self.scroll_area)

        self._update_proposal_controls()

    @staticmethod
    def _create_list(title, object_name):
        group = QGroupBox(title)
        group.setObjectName(object_name + "Group")
        group_layout = QVBoxLayout(group)
        widget = QListWidget()
        widget.setObjectName(object_name)
        widget.setWordWrap(True)
        group_layout.addWidget(widget)
        group.setMinimumWidth(180)
        return group

    @staticmethod
    def _list_widget(group):
        return group.findChild(QListWidget)

    @staticmethod
    def _value(item, key, default=""):
        if isinstance(item, dict):
            return item.get(key, default)
        return default

    @staticmethod
    def _format_item(item):
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            parts = []
            for key in (
                "severity",
                "priority",
                "title",
                "description",
                "file",
                "line",
                "recommendation",
            ):
                value = item.get(key)
                if value not in (None, ""):
                    parts.append(f"{key}: {value}")
            if parts:
                return "\n".join(parts)
        return str(item)

    def start_analysis(self):
        objective = self.objective_input.text().strip()
        if not objective:
            self.status_label.setText(
                "Informe um objetivo antes de iniciar."
            )
            return

        try:
            self.start_button.setEnabled(False)
            self.status_label.setText("Preparando análise...")

            if self.workflow is None:
                workflow = self.workflow_factory()
                self.set_workflow(workflow)

            self.workflow.start_analysis(objective=objective)
        except Exception as error:
            self.start_button.setEnabled(True)
            self.status_label.setText(
                f"Não foi possível iniciar a análise: {error}"
            )

    def _on_analysis_started(self, objective):
        self.status_label.setText(f"Análise iniciada: {objective}")

    def _on_state_changed(self, state):
        state_value = str(getattr(state, "value", state))
        message = self.AVAILABLE_STATES.get(
            state_value, f"Estado atual: {state_value}"
        )
        self.status_label.setText(message)
        self.start_button.setEnabled(
            state_value in {"idle", "failed", "completed", "cancelled"}
        )

    def _on_failed(self, message):
        self.status_label.setText(f"Falha na análise: {message}")
        self.start_button.setEnabled(True)

    def _on_plan_ready(self, result):
        plan = getattr(result, "plan", None)
        if plan is None and isinstance(result, dict):
            plan = result.get("plan")

        if not isinstance(plan, dict):
            self.status_label.setText(
                "A análise terminou, mas o plano recebido é inválido."
            )
            return

        self.summary.setPlainText(
            str(plan.get("summary", "Resumo não informado."))
        )

        findings = plan.get("findings", [])
        actions = plan.get("actions", [])
        risks = plan.get("risks", [])

        self._populate_list(self.findings_list, findings)
        self._populate_list(self.actions_list, actions)
        self._populate_list(self.risks_list, risks)
        self._populate_action_selector(actions)

        task_id = getattr(result, "task_id", None)
        if task_id is None and isinstance(result, dict):
            task_id = result.get("task_id")

        self.status_label.setText(
            "Plano recebido com sucesso. "
            f"Achados: {len(findings) if isinstance(findings, list) else 0} | "
            f"Ações: {len(actions) if isinstance(actions, list) else 0} | "
            f"Riscos: {len(risks) if isinstance(risks, list) else 0} | "
            f"Tarefa: {task_id or 'não informado'}"
        )

    def _populate_action_selector(self, actions):
        self.action_selector.blockSignals(True)
        self.action_selector.clear()
        self.file_selector.clear()

        if isinstance(actions, list):
            for action in actions:
                if not isinstance(action, dict):
                    continue
                action_id = action.get("id")
                title = action.get("title") or action_id or "Ação sem título"
                if not isinstance(action_id, str) or not action_id.strip():
                    continue
                self.action_selector.addItem(
                    f"{action_id} — {title}", action_id
                )

        self.action_selector.blockSignals(False)
        self._on_action_selected(self.action_selector.currentIndex())

    def _get_selected_action(self):
        if self.workflow is None:
            return None
        result = getattr(self.workflow, "last_result", None)
        if result is None:
            return None
        plan = self._value(result, "plan", None)
        actions = self._value(plan, "actions", [])
        selected_id = self.action_selector.currentData()
        if not isinstance(actions, list):
            return None
        return next(
            (
                action for action in actions
                if isinstance(action, dict) and action.get("id") == selected_id
            ),
            None,
        )

    def _on_action_selected(self, _index):
        self.file_selector.clear()
        action = self._get_selected_action()
        files = action.get("files", []) if isinstance(action, dict) else []

        if isinstance(files, list):
            for path in files:
                if isinstance(path, str) and path.strip():
                    self.file_selector.addItem(path, path)

        self._update_proposal_controls()

    def generate_proposal(self):
        if self.workflow is None:
            self.proposal_status_label.setText(
                "Workflow ainda não está disponível."
            )
            return

        action_id = self.action_selector.currentData()
        relative_path = self.file_selector.currentData()
        if not action_id or not relative_path:
            self.proposal_status_label.setText(
                "Selecione uma ação e um arquivo válido."
            )
            return

        try:
            self.generate_button.setEnabled(False)
            self.proposal_status_label.setText(
                "Gerando proposta em segundo plano..."
            )
            self.workflow.request_patch_proposal_async(
                action_id, relative_path
            )
        except Exception as error:
            self.generate_button.setEnabled(True)
            self.proposal_status_label.setText(
                f"Não foi possível iniciar a proposta: {error}"
            )

    def _on_proposal_started(self, action_id, relative_path):
        self.generate_button.setEnabled(False)
        self.proposal_status_label.setText(
            f"Gerando proposta para {action_id} — {relative_path}..."
        )

    def _on_proposal_failed(self, message):
        self.proposal_status_label.setText(
            f"Falha ao gerar proposta: {message}"
        )
        self.generate_button.setEnabled(True)

    def _on_proposal_ready(self, notification):
        if not isinstance(notification, dict):
            self._on_proposal_failed("Notificação de proposta inválida.")
            return

        proposal_id = notification.get("proposal_id")
        proposal = notification.get("proposal")
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            self._on_proposal_failed("Identificador da proposta inválido.")
            return
        if not isinstance(proposal, dict):
            self._on_proposal_failed("Conteúdo da proposta inválido.")
            return

        is_new_proposal = proposal_id not in self._proposals
        self._proposals[proposal_id] = notification
        if is_new_proposal:
            label = (
                f"{notification.get('action_id', 'Ação')} — "
                f"{notification.get('relative_path', 'Arquivo')}"
            )
            self.proposal_selector.addItem(label, proposal_id)

        for index in range(self.proposal_selector.count()):
            if self.proposal_selector.itemData(index) == proposal_id:
                self.proposal_selector.setCurrentIndex(index)
                break
        self.proposal_status_label.setText(
            "Proposta gerada e registrada. Aguardando sua decisão."
        )
        self.generate_button.setEnabled(True)
        self.refresh_proposal_status()

    def _on_proposal_selected(self, _index):
        proposal_id = self.proposal_selector.currentData()
        notification = self._proposals.get(proposal_id)
        proposal = notification.get("proposal", {}) if notification else {}

        self.proposal_explanation.setPlainText(
            str(proposal.get("explanation", "Explicação não informada."))
        )
        self.original_snippet.setPlainText(
            str(proposal.get("original_snippet", ""))
        )
        self.replacement_snippet.setPlainText(
            str(proposal.get("replacement_snippet", ""))
        )
        self.refresh_proposal_status()

    def refresh_proposal_status(self):
        proposal_id = self.proposal_selector.currentData()
        manager = getattr(self.workflow, "approval_manager", None)

        if not proposal_id or manager is None:
            self.approve_button.setEnabled(False)
            self.reject_button.setEnabled(False)
            if not proposal_id:
                self.proposal_status_label.setText(
                    "Nenhuma proposta selecionada."
                )
            self._status_timer.stop()
            return

        try:
            status = manager.get_status(proposal_id)
        except Exception as error:
            self.proposal_status_label.setText(
                f"Não foi possível consultar o status: {error}"
            )
            self.approve_button.setEnabled(False)
            self.reject_button.setEnabled(False)
            self._status_timer.stop()
            return

        label = self.STATUS_LABELS.get(status, f"Estado: {status}")
        self.proposal_status_label.setText(label)
        is_pending = status == "pending"
        self.approve_button.setEnabled(is_pending)
        self.reject_button.setEnabled(is_pending)

        if is_pending:
            self._status_timer.start()
        else:
            self._status_timer.stop()

    def approve_selected_proposal(self):
        self._decide_selected_proposal("approve")

    def reject_selected_proposal(self):
        self._decide_selected_proposal("reject")

    def _decide_selected_proposal(self, decision):
        proposal_id = self.proposal_selector.currentData()
        manager = getattr(self.workflow, "approval_manager", None)

        if not proposal_id or manager is None:
            self.proposal_status_label.setText(
                "Não há proposta disponível para decisão."
            )
            return

        try:
            if decision == "approve":
                manager.approve(proposal_id)
                message = (
                    "Proposta aprovada. Nenhuma alteração foi aplicada."
                )
            else:
                manager.reject(proposal_id)
                message = "Proposta rejeitada. Nenhuma alteração foi aplicada."

            self.proposal_status_label.setText(message)
        except Exception as error:
            self.proposal_status_label.setText(
                f"Não foi possível registrar a decisão: {error}"
            )
        finally:
            self.refresh_proposal_status()

    def _get_autonomy_controller(self):
        host = self.window()
        factory = getattr(
            host, "create_autonomous_correction_controller", None
        )
        if not callable(factory):
            raise RuntimeError(
                "A janela principal não disponibiliza o controlador autônomo."
            )
        controller = factory()
        if self._autonomy_controller is not controller:
            self._autonomy_controller = controller
            controller.state_changed.connect(
                self._on_autonomy_state_changed
            )
            controller.proposal_ready.connect(
                self._on_autonomy_proposal_ready
            )
            controller.attempt_started.connect(
                self._on_autonomy_attempt_started
            )
            controller.attempt_finished.connect(
                self._on_autonomy_attempt_finished
            )
            controller.completed.connect(
                self._on_autonomy_completed
            )
            controller.failed.connect(
                self._on_autonomy_failed
            )
            controller.cancelled.connect(
                self._on_autonomy_cancelled
            )
        return controller

    def start_autonomous_correction(self):
        if self.workflow is None:
            self.autonomy_status_label.setText(
                "Execute primeiro a análise do firmware."
            )
            return

        action_id = self.action_selector.currentData()
        relative_path = self.file_selector.currentData()
        if not action_id or not relative_path:
            self.autonomy_status_label.setText(
                "Selecione uma ação e um arquivo antes de iniciar."
            )
            return

        workflow_state = getattr(
            self.workflow.state, "value", self.workflow.state
        )
        if workflow_state != "awaiting_approval":
            self.autonomy_status_label.setText(
                "A análise precisa estar concluída e aguardando aprovação."
            )
            return

        try:
            controller = self._get_autonomy_controller()
        except Exception as error:
            self.autonomy_status_label.setText(
                f"Não foi possível preparar a autonomia: {error}"
            )
            return

        if controller.is_active:
            self.autonomy_status_label.setText(
                "Já existe uma sessão autônoma ativa."
            )
            return

        confirmation = QMessageBox.question(
            self,
            "Autorizar correção autônoma",
            (
                "Você autoriza o VINI_JR a corrigir o firmware neste ciclo?\n\n"
                f"Projeto: {controller.root}\n"
                f"Arquivo autorizado: {relative_path}\n"
                "Limite: até 3 aplicações de patch e 3 Builds.\n\n"
                "A primeira proposta exigirá sua aprovação manual. "
                "As tentativas seguintes poderão ser aprovadas automaticamente, "
                "mas somente no mesmo arquivo.\n\n"
                "Full Clean e Flash não serão executados. "
                "Você poderá cancelar a sessão."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self.autonomy_status_label.setText(
                "Autorização não concedida. Nenhuma correção foi iniciada."
            )
            return

        try:
            controller.start_session(
                action_id=action_id,
                relative_path=relative_path,
                authorize_session=True,
                authorize_automatic_retries=True,
                max_attempts=3,
            )
            self.start_autonomy_button.setEnabled(False)
            self.cancel_autonomy_button.setEnabled(True)
            self.autonomy_status_label.setText(
                "Sessão autorizada. Gerando a primeira proposta; "
                "aguardando sua aprovação manual."
            )
        except Exception as error:
            self.autonomy_status_label.setText(
                f"Não foi possível iniciar a sessão: {error}"
            )
            self._update_proposal_controls()

    def cancel_autonomous_correction(self):
        controller = self._autonomy_controller
        if controller is None or not controller.is_active:
            self.autonomy_status_label.setText(
                "Não há sessão autônoma ativa para cancelar."
            )
            self.cancel_autonomy_button.setEnabled(False)
            return
        controller.cancel()
        self.autonomy_status_label.setText(
            "Cancelamento solicitado. Aguardando interrupção segura da operação."
        )
        self.cancel_autonomy_button.setEnabled(False)

    def _on_autonomy_state_changed(self, state):
        labels = {
            "idle": "Autonomia inativa.",
            "generating_proposal": "Gerando primeira proposta...",
            "awaiting_approval": "Aguardando sua aprovação da primeira proposta.",
            "applying_building": "Aplicando correção e executando Build...",
            "generating_retry": "Build falhou. Preparando nova proposta dentro do mesmo arquivo...",
            "cancelling": "Cancelamento em andamento...",
            "completed": "Correção concluída: Build aprovado.",
            "failed": "Sessão interrompida por falha ou limite de tentativas.",
            "cancelled": "Sessão cancelada.",
        }
        self.autonomy_status_label.setText(
            labels.get(str(state), f"Estado da autonomia: {state}")
        )
        active = bool(
            self._autonomy_controller
            and self._autonomy_controller.is_active
        )
        self.cancel_autonomy_button.setEnabled(active)
        self._update_proposal_controls()

    def _on_autonomy_proposal_ready(self, notification):
        self._on_proposal_ready(notification)
        if isinstance(notification, dict) and notification.get("automatic_retry"):
            attempt = notification.get("attempt", "?")
            self.autonomy_status_label.setText(
                f"Nova proposta automática preparada para a tentativa {attempt}; "
                "escopo mantido no arquivo autorizado."
            )

    def _on_autonomy_attempt_started(self, number, proposal_id):
        self.autonomy_status_label.setText(
            f"Tentativa {number}/3: patch autorizado. Executando Build..."
        )
        self.start_autonomy_button.setEnabled(False)
        self.cancel_autonomy_button.setEnabled(True)

    def _on_autonomy_attempt_finished(self, number, build_result):
        success = bool(getattr(build_result, "success", False))
        returncode = getattr(build_result, "returncode", "N/D")
        if success:
            message = f"Tentativa {number}/3: Build concluído com sucesso."
        else:
            message = (
                f"Tentativa {number}/3: Build falhou "
                f"(código {returncode}). Avaliando nova tentativa..."
            )
        self.autonomy_status_label.setText(message)

    def _on_autonomy_completed(self, summary):
        attempts = summary.get("attempts", "?") if isinstance(summary, dict) else "?"
        self.autonomy_status_label.setText(
            f"Sucesso: firmware compilado após {attempts} tentativa(s)."
        )
        self.cancel_autonomy_button.setEnabled(False)
        self._update_proposal_controls()

    def _on_autonomy_failed(self, message):
        self.autonomy_status_label.setText(
            f"Sessão interrompida: {message}"
        )
        self.cancel_autonomy_button.setEnabled(False)
        self._update_proposal_controls()

    def _on_autonomy_cancelled(self):
        self.autonomy_status_label.setText("Sessão cancelada pelo usuário.")
        self.cancel_autonomy_button.setEnabled(False)
        self._update_proposal_controls()

    def _update_proposal_controls(self):
        workflow_ready = self.workflow is not None
        has_services = (
            workflow_ready
            and getattr(self.workflow, "patch_proposal_service", None) is not None
            and getattr(self.workflow, "approval_manager", None) is not None
        )
        has_file = self.file_selector.count() > 0
        generating = bool(
            workflow_ready
            and getattr(self.workflow, "is_generating_proposal", False)
        )
        self.generate_button.setEnabled(
            bool(has_services and has_file and not generating)
        )
        has_selected_proposal = self.proposal_selector.currentData() is not None
        if not has_selected_proposal:
            self.approve_button.setEnabled(False)
            self.reject_button.setEnabled(False)

        action_selected = self.action_selector.currentData() is not None
        file_selected = self.file_selector.currentData() is not None
        workflow_state = (
            getattr(self.workflow.state, "value", self.workflow.state)
            if workflow_ready else "idle"
        )
        controller_active = bool(
            self._autonomy_controller
            and self._autonomy_controller.is_active
        )
        self.start_autonomy_button.setEnabled(
            bool(
                workflow_ready
                and action_selected
                and file_selected
                and workflow_state == "awaiting_approval"
                and not controller_active
            )
        )
        self.cancel_autonomy_button.setEnabled(controller_active)

    def _populate_list(self, group, items):
        widget = self._list_widget(group)
        widget.clear()

        if not isinstance(items, list):
            widget.addItem("Formato de dados inválido.")
            return
        if not items:
            widget.addItem("Nenhum item identificado.")
            return
        for item in items:
            widget.addItem(self._format_item(item))
