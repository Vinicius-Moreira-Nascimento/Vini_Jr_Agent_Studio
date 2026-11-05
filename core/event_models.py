from dataclasses import dataclass, field
from datetime import datetime, timezone
from copy import deepcopy
from uuid import uuid4


VALID_STATUSES = frozenset({
    "info",
    "running",
    "success",
    "warning",
    "error",
    "waiting",
    "cancelled",
})


@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    timestamp: str
    category: str
    event_type: str
    message: str
    status: str
    source: str
    task_id: str = None
    details: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        category,
        event_type,
        message,
        status="info",
        source="system",
        task_id=None,
        details=None,
    ):
        values = {
            "category": category,
            "event_type": event_type,
            "message": message,
            "source": source,
        }

        for name, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"O campo {name} deve ser um texto não vazio."
                )

        if status not in VALID_STATUSES:
            raise ValueError("Status de evento inválido.")

        if task_id is not None and not isinstance(task_id, str):
            raise TypeError("task_id deve ser texto ou None.")

        if details is not None and not isinstance(details, dict):
            raise TypeError("details deve ser um dicionário.")

        return cls(
            event_id=uuid4().hex,
            timestamp=datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            category=category.strip(),
            event_type=event_type.strip(),
            message=message,
            status=status,
            source=source.strip(),
            task_id=task_id,
            details=deepcopy(details or {}),
        )

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "category": self.category,
            "event_type": self.event_type,
            "message": self.message,
            "status": self.status,
            "source": self.source,
            "task_id": self.task_id,
            "details": deepcopy(self.details),
        }
