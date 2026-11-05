from collections import deque
from copy import deepcopy
from threading import RLock

from PySide6.QtCore import QObject, Signal

from core.event_models import AgentEvent


class EventManager(QObject):
    """
    Central de eventos do VINI_JR Agent Studio.

    Pode receber publicações de diferentes threads.
    A interface deve consumir os eventos pelo sinal event_published.
    """

    event_published = Signal(object)
    history_changed = Signal()

    def __init__(self, max_history=2000, parent=None):
        super().__init__(parent)

        if not isinstance(max_history, int) or max_history < 1:
            raise ValueError("max_history deve ser um inteiro positivo.")

        self.max_history = max_history
        self._events = deque(maxlen=max_history)
        self._lock = RLock()

    def publish(
        self,
        category,
        event_type,
        message,
        status="info",
        source="system",
        task_id=None,
        details=None,
    ):
        event = AgentEvent.create(
            category=category,
            event_type=event_type,
            message=message,
            status=status,
            source=source,
            task_id=task_id,
            details=details,
        )

        with self._lock:
            self._events.append(event)

        # Os sinais Qt permitem atualização segura da interface.
        self.event_published.emit(event)
        self.history_changed.emit()

        return event

    def history(self, limit=None):
        if limit is not None:
            if not isinstance(limit, int) or limit < 0:
                raise ValueError("limit deve ser um inteiro não negativo.")

        with self._lock:
            events = list(self._events)

        if limit is not None:
            events = events[-limit:] if limit else []

        return tuple(deepcopy(events))

    def clear_history(self):
        with self._lock:
            self._events.clear()

        self.history_changed.emit()

    def count(self):
        with self._lock:
            return len(self._events)
