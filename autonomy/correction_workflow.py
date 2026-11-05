from copy import deepcopy
from enum import Enum
from threading import RLock

from PySide6.QtCore import QObject, QThread, Signal


class CorrectionWorkflowState(str, Enum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class _AnalysisWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, correction_engine, objective):
        super().__init__()
        self.correction_engine = correction_engine
        self.objective = objective

    def run(self):
        try:
            result = self.correction_engine.analyze_and_plan(
                objective=self.objective
            )
            self.succeeded.emit(result)
        except Exception as error:
            self.failed.emit(
                f"{type(error).__name__}: {error}"
            )


class _ProposalWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        patch_proposal_service,
        action,
        relative_path,
        inventory,
    ):
        super().__init__()
        self.patch_proposal_service = patch_proposal_service
        self.action = action
        self.relative_path = relative_path
        self.inventory = inventory

    def run(self):
        try:
            proposal = self.patch_proposal_service.create_proposal(
                action=self.action,
                relative_path=self.relative_path,
                inventory=self.inventory,
            )

            if not isinstance(proposal, dict):
                raise TypeError(
                    "PatchProposalService retornou uma proposta inválida."
                )

            self.succeeded.emit(proposal)
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")


class CorrectionWorkflow(QObject):
    """
    Coordenador assíncrono inicial do fluxo de correção.

    Nesta versão, executa somente análise e planejamento.
    Não aplica alterações, não executa Build, Full Clean ou Flash.
    """

    state_changed = Signal(str)
    analysis_started = Signal(str)
    plan_ready = Signal(object)
    failed = Signal(str)
    proposal_ready = Signal(object)
    proposal_started = Signal(str, str)
    proposal_failed = Signal(str)

    def __init__(
        self,
        correction_engine,
        parent=None,
        patch_proposal_service=None,
        approval_manager=None,
    ):
        super().__init__(parent)

        if not callable(
            getattr(correction_engine, "analyze_and_plan", None)
        ):
            raise TypeError(
                "correction_engine precisa implementar analyze_and_plan()."
            )

        self.correction_engine = correction_engine
        self.patch_proposal_service = patch_proposal_service
        self.approval_manager = approval_manager
        self._lock = RLock()
        self._state = CorrectionWorkflowState.IDLE
        self._worker = None
        self._proposal_worker = None
        self._proposal_context = None
        self._last_result = None

    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def last_result(self):
        with self._lock:
            return self._last_result

    @property
    def is_running(self):
        with self._lock:
            return self._state == CorrectionWorkflowState.ANALYZING

    @property
    def is_generating_proposal(self):
        with self._lock:
            return (
                self._proposal_worker is not None
                and self._proposal_worker.isRunning()
            )

    def _set_state(self, state):
        with self._lock:
            self._state = state

        self.state_changed.emit(state.value)

    def start_analysis(
        self,
        objective="Analisar e planejar melhorias no firmware",
    ):
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("O objetivo precisa ser um texto válido.")

        objective = objective.strip()

        with self._lock:
            if self._state not in (
                CorrectionWorkflowState.IDLE,
                CorrectionWorkflowState.FAILED,
                CorrectionWorkflowState.COMPLETED,
                CorrectionWorkflowState.CANCELLED,
            ):
                raise RuntimeError(
                    "O workflow já possui uma operação em andamento "
                    "ou aguarda aprovação."
                )

            if self._worker is not None and self._worker.isRunning():
                raise RuntimeError(
                    "A thread de análise anterior ainda está em execução."
                )

            self._state = CorrectionWorkflowState.ANALYZING
            self._last_result = None

        self.state_changed.emit(
            CorrectionWorkflowState.ANALYZING.value
        )

        worker = _AnalysisWorker(
            correction_engine=self.correction_engine,
            objective=objective,
        )

        self._worker = worker

        worker.succeeded.connect(self._on_analysis_succeeded)
        worker.failed.connect(self._on_analysis_failed)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(worker.deleteLater)

        self.analysis_started.emit(objective)
        worker.start()

    def _on_analysis_succeeded(self, result):
        with self._lock:
            if self._state != CorrectionWorkflowState.ANALYZING:
                return

            self._last_result = result
            self._state = CorrectionWorkflowState.AWAITING_APPROVAL

        self.state_changed.emit(
            CorrectionWorkflowState.AWAITING_APPROVAL.value
        )
        self.plan_ready.emit(result)

    def _on_analysis_failed(self, message):
        with self._lock:
            self._last_result = None
            self._state = CorrectionWorkflowState.FAILED

        self.state_changed.emit(
            CorrectionWorkflowState.FAILED.value
        )
        self.failed.emit(message)

    def _on_worker_finished(self):
        with self._lock:
            self._worker = None


    def _prepare_patch_request(self, action_id, relative_path):
        with self._lock:
            if self._state != CorrectionWorkflowState.AWAITING_APPROVAL:
                raise RuntimeError(
                    "O workflow precisa estar aguardando aprovação do plano."
                )

            if (
                self._proposal_worker is not None
                and self._proposal_worker.isRunning()
            ):
                raise RuntimeError(
                    "Já existe uma geração de proposta em andamento."
                )

            result = self._last_result

        if self.patch_proposal_service is None:
            raise RuntimeError("PatchProposalService não foi configurado.")

        if self.approval_manager is None:
            raise RuntimeError("ApprovalManager não foi configurado.")

        if not isinstance(action_id, str) or not action_id.strip():
            raise ValueError("O identificador da ação é inválido.")

        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("O caminho do arquivo é inválido.")

        def get_value(source, key, default=None):
            if isinstance(source, dict):
                return source.get(key, default)
            return getattr(source, key, default)

        plan = get_value(result, "plan")
        planning_input = get_value(result, "planning_input")

        if not isinstance(plan, dict) or not isinstance(planning_input, dict):
            raise ValueError("O resultado da análise não contém plano válido.")

        actions = plan.get("actions")
        inventory = planning_input.get("inventory")

        if not isinstance(actions, list):
            raise ValueError("A lista de ações do plano é inválida.")

        if not isinstance(inventory, list):
            raise ValueError("O inventário do projeto é inválido.")

        selected_action = next(
            (
                action for action in actions
                if isinstance(action, dict)
                and action.get("id") == action_id
            ),
            None,
        )

        if selected_action is None:
            raise ValueError("A ação selecionada não pertence ao plano atual.")

        action_files = selected_action.get("files")

        if (
            not isinstance(action_files, list)
            or relative_path not in action_files
        ):
            raise ValueError(
                "O arquivo selecionado não pertence à ação escolhida."
            )

        return selected_action, inventory

    def _register_proposal(self, proposal, action_id, relative_path):
        if not isinstance(proposal, dict):
            raise TypeError("PatchProposalService retornou proposta inválida.")

        proposal_id = self.approval_manager.request_approval(proposal)

        if not isinstance(proposal_id, str) or not proposal_id.strip():
            raise RuntimeError(
                "ApprovalManager não retornou um identificador válido."
            )

        notification = {
            "proposal_id": proposal_id,
            "proposal": proposal,
            "action_id": action_id,
            "relative_path": relative_path,
        }

        self.proposal_ready.emit(notification)
        return proposal_id

    def request_patch_proposal(self, action_id, relative_path):
        """
        Gera uma proposta de forma síncrona para manter compatibilidade.

        Para uso pela interface, prefira request_patch_proposal_async().
        Este método não aprova nem aplica alterações.
        """
        selected_action, inventory = self._prepare_patch_request(
            action_id,
            relative_path,
        )

        proposal = self.patch_proposal_service.create_proposal(
            action=selected_action,
            relative_path=relative_path,
            inventory=inventory,
        )

        return self._register_proposal(
            proposal,
            action_id,
            relative_path,
        )

    def request_patch_proposal_async(self, action_id, relative_path):
        """
        Inicia a geração da proposta em uma thread separada.

        A proposta só é registrada no ApprovalManager após a geração,
        no fluxo de sinais do objeto CorrectionWorkflow.
        Retorna True quando a operação é iniciada.
        """
        selected_action, inventory = self._prepare_patch_request(
            action_id,
            relative_path,
        )

        worker = _ProposalWorker(
            patch_proposal_service=self.patch_proposal_service,
            action=deepcopy(selected_action),
            relative_path=relative_path,
            inventory=deepcopy(inventory),
        )

        with self._lock:
            self._proposal_context = {
                "action_id": action_id,
                "relative_path": relative_path,
            }
            self._proposal_worker = worker

        worker.succeeded.connect(self._on_proposal_generated)
        worker.failed.connect(self._on_proposal_generation_failed)
        worker.finished.connect(self._on_proposal_worker_finished)
        worker.finished.connect(worker.deleteLater)

        self.proposal_started.emit(action_id, relative_path)
        worker.start()
        return True

    def _on_proposal_generated(self, proposal):
        with self._lock:
            context = self._proposal_context

        if context is None:
            self.proposal_failed.emit(
                "Não foi possível recuperar os dados da proposta gerada."
            )
            return

        try:
            self._register_proposal(
                proposal,
                context["action_id"],
                context["relative_path"],
            )
        except Exception as error:
            self.proposal_failed.emit(
                f"{type(error).__name__}: {error}"
            )

    def _on_proposal_generation_failed(self, message):
        self.proposal_failed.emit(message)

    def _on_proposal_worker_finished(self):
        with self._lock:
            self._proposal_worker = None
            self._proposal_context = None

    def reset(self):
        """
        Reinicia o coordenador após uma operação terminal.

        Não descarta um plano que esteja aguardando aprovação.
        """
        with self._lock:
            if self._state == CorrectionWorkflowState.AWAITING_APPROVAL:
                raise RuntimeError(
                    "Existe um plano aguardando aprovação."
                )

            if self._state == CorrectionWorkflowState.ANALYZING:
                raise RuntimeError(
                    "Não é possível reiniciar durante a análise."
                )

            if self._worker is not None and self._worker.isRunning():
                raise RuntimeError(
                    "A thread anterior ainda está em execução."
                )

            if (
                self._proposal_worker is not None
                and self._proposal_worker.isRunning()
            ):
                raise RuntimeError(
                    "Existe uma geração de proposta em andamento."
                )

            self._last_result = None
            self._state = CorrectionWorkflowState.IDLE

        self.state_changed.emit(
            CorrectionWorkflowState.IDLE.value
        )