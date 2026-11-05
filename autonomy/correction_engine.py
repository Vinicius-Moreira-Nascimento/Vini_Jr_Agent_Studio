from dataclasses import dataclass
from enum import Enum
from threading import RLock
from uuid import uuid4

from autonomy.plan_validator import validate_plan


class CorrectionEngineState(str, Enum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class CorrectionRunResult:
    task_id: str
    objective: str
    status: str
    analysis: dict
    planning_input: dict
    plan: dict


class CorrectionEngine:
    """
    Coordena a etapa de analise e planejamento da correcao inteligente.

    Esta primeira versao nao modifica arquivos, nao executa comandos
    e nao realiza compilacao.
    """

    def __init__(self, planning_service, event_manager=None):
        if not callable(
            getattr(planning_service, "analyze_and_plan", None)
        ):
            raise TypeError(
                "planning_service precisa implementar analyze_and_plan()."
            )

        if event_manager is not None and not callable(
            getattr(event_manager, "publish", None)
        ):
            raise TypeError(
                "event_manager precisa implementar publish()."
            )

        self.planning_service = planning_service
        self.event_manager = event_manager

        self._lock = RLock()
        self._running = False
        self._state = CorrectionEngineState.IDLE
        self._last_result = None

    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def last_result(self):
        with self._lock:
            return self._last_result

    def _set_state(self, state):
        with self._lock:
            self._state = state

    def _publish_event(
        self,
        event_type,
        message,
        status="info",
        task_id=None,
        details=None,
    ):
        if self.event_manager is None:
            return

        self.event_manager.publish(
            category="correction_engine",
            event_type=event_type,
            message=message,
            status=status,
            source="CorrectionEngine",
            task_id=task_id,
            details=details or {},
        )

    def analyze_and_plan(
        self,
        objective="Analisar e planejar melhorias no firmware",
    ):
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("O objetivo precisa ser um texto valido.")

        objective = objective.strip()
        task_id = uuid4().hex

        with self._lock:
            if self._running:
                raise RuntimeError(
                    "Ja existe uma execucao do CorrectionEngine."
                )

            self._running = True
            self._state = CorrectionEngineState.ANALYZING
            self._last_result = None

        try:
            self._publish_event(
                event_type="correction_analysis_started",
                message="Analise e planejamento iniciados.",
                status="running",
                task_id=task_id,
                details={"objective": objective},
            )

            service_result = self.planning_service.analyze_and_plan(
                objective=objective
            )

            if not isinstance(service_result, dict):
                raise TypeError(
                    "PlanningService retornou um resultado invalido."
                )

            analysis = service_result.get("analysis")
            planning_input = service_result.get("planning_input")
            plan = service_result.get("plan")

            if not isinstance(analysis, dict):
                raise ValueError("Analise do projeto invalida.")

            if not isinstance(planning_input, dict):
                raise ValueError("Entrada de planejamento invalida.")

            if not isinstance(plan, dict):
                raise ValueError("Plano tecnico invalido.")

            inventory = planning_input.get("inventory", [])

            if not isinstance(inventory, list):
                raise ValueError("Inventario do projeto invalido.")

            # Segunda validacao na fronteira do motor.
            validated_plan = validate_plan(
                plan,
                inventory=inventory,
            )

            result = CorrectionRunResult(
                task_id=task_id,
                objective=objective,
                status="completed",
                analysis=analysis,
                planning_input=planning_input,
                plan=validated_plan,
            )

            with self._lock:
                self._last_result = result
                self._state = CorrectionEngineState.COMPLETED

            self._publish_event(
                event_type="correction_plan_ready",
                message="Plano tecnico validado com sucesso.",
                status="success",
                task_id=task_id,
                details={
                    "findings_count": len(
                        validated_plan.get("findings", [])
                    ),
                    "actions_count": len(
                        validated_plan.get("actions", [])
                    ),
                },
            )

            return result

        except Exception as error:
            self._set_state(CorrectionEngineState.FAILED)

            self._publish_event(
                event_type="correction_run_failed",
                message="Falha durante analise ou planejamento.",
                status="error",
                task_id=task_id,
                details={
                    "error_type": type(error).__name__,
                },
            )

            raise

        finally:
            with self._lock:
                self._running = False
