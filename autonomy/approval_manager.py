from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from threading import RLock
from time import monotonic
from uuid import uuid4


@dataclass
class ApprovalRecord:
    proposal_id: str
    proposal: dict
    status: str
    created_at: float
    expires_at: float


class ApprovalManager:
    """
    Gerencia aprovacoes explicitas, individuais e de uso unico.

    Nao modifica arquivos nem executa comandos.
    """

    VALID_STATUSES = {
        "pending",
        "approved",
        "rejected",
        "expired",
        "consumed",
    }

    def __init__(self, event_manager=None, default_ttl_seconds=900):
        if event_manager is not None and not callable(
            getattr(event_manager, "publish", None)
        ):
            raise TypeError("event_manager precisa implementar publish().")

        self._validate_ttl(default_ttl_seconds)

        self.event_manager = event_manager
        self.default_ttl_seconds = float(default_ttl_seconds)
        self._records = {}
        self._lock = RLock()

    @staticmethod
    def _validate_ttl(ttl_seconds):
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            raise ValueError("O prazo de aprovacao precisa ser positivo.")

    def _publish_event(self, event_type, message, status, proposal_id):
        if self.event_manager is None:
            return

        self.event_manager.publish(
            category="approval",
            event_type=event_type,
            message=message,
            status=status,
            source="ApprovalManager",
            task_id=proposal_id,
            details={"proposal_id": proposal_id},
        )

    def _expire_if_needed(self, record):
        if (
            record.status in {"pending", "approved"}
            and monotonic() >= record.expires_at
        ):
            record.status = "expired"

            self._publish_event(
                "approval_expired",
                "A aprovacao expirou.",
                "warning",
                record.proposal_id,
            )

            return True

        return False

    def request_approval(self, proposal, ttl_seconds=None):
        if not isinstance(proposal, dict) or not proposal:
            raise ValueError("A proposta precisa ser um dicionario nao vazio.")

        ttl = (
            self.default_ttl_seconds
            if ttl_seconds is None
            else ttl_seconds
        )
        self._validate_ttl(ttl)

        now = monotonic()
        proposal_id = uuid4().hex

        record = ApprovalRecord(
            proposal_id=proposal_id,
            proposal=deepcopy(proposal),
            status="pending",
            created_at=now,
            expires_at=now + float(ttl),
        )

        with self._lock:
            self._records[proposal_id] = record

        self._publish_event(
            "approval_requested",
            "Nova proposta aguardando aprovacao explicita.",
            "waiting",
            proposal_id,
        )

        return proposal_id

    def approve(self, proposal_id):
        with self._lock:
            record = self._records.get(proposal_id)

            if record is None:
                raise KeyError("Proposta de aprovacao nao encontrada.")

            self._expire_if_needed(record)

            if record.status != "pending":
                raise ValueError(
                    f"Proposta nao pode ser aprovada. Estado: {record.status}"
                )

            record.status = "approved"

        self._publish_event(
            "approval_granted",
            "Proposta aprovada explicitamente.",
            "success",
            proposal_id,
        )

        return True

    def reject(self, proposal_id):
        with self._lock:
            record = self._records.get(proposal_id)

            if record is None:
                raise KeyError("Proposta de aprovacao nao encontrada.")

            self._expire_if_needed(record)

            if record.status != "pending":
                raise ValueError(
                    f"Proposta nao pode ser rejeitada. Estado: {record.status}"
                )

            record.status = "rejected"

        self._publish_event(
            "approval_rejected",
            "Proposta rejeitada explicitamente.",
            "cancelled",
            proposal_id,
        )

        return True

    def consume_approval(self, proposal_id):
        with self._lock:
            record = self._records.get(proposal_id)

            if record is None:
                raise KeyError("Proposta de aprovacao nao encontrada.")

            self._expire_if_needed(record)

            if record.status != "approved":
                raise PermissionError(
                    "Aprovacao inexistente, expirada ou ja consumida."
                )

            proposal = deepcopy(record.proposal)
            record.status = "consumed"

        self._publish_event(
            "approval_consumed",
            "A aprovacao foi consumida e nao pode ser reutilizada.",
            "success",
            proposal_id,
        )

        return proposal

    def get_status(self, proposal_id):
        with self._lock:
            record = self._records.get(proposal_id)

            if record is None:
                raise KeyError("Proposta de aprovacao nao encontrada.")

            self._expire_if_needed(record)
            return record.status

    def has_pending_approval(self, proposal_id):
        return self.get_status(proposal_id) == "pending"
