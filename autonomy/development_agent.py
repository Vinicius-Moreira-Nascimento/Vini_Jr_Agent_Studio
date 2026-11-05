from dataclasses import dataclass
from enum import Enum


class AutonomyMode(str, Enum):
    ASSISTED = "assisted"
    SEMI_AUTONOMOUS = "semi_autonomous"
    AUTONOMOUS = "autonomous"


@dataclass(frozen=True)
class AutonomyPolicy:
    mode: AutonomyMode = AutonomyMode.ASSISTED
    max_correction_attempts: int = 3
    allow_build: bool = True
    allow_fullclean: bool = False
    allow_flash: bool = False

    def __post_init__(self):
        if not 1 <= self.max_correction_attempts <= 10:
            raise ValueError("max_correction_attempts deve ficar entre 1 e 10.")
        if self.allow_flash:
            raise ValueError(
                "Flash automatico bloqueado: exige confirmacao explicita."
            )


class DevelopmentAgent:
    """Controlador de politicas para o futuro ciclo analisar-corrigir-testar."""

    def __init__(self, policy=None):
        self.policy = policy or AutonomyPolicy()
        self.correction_attempts = 0

    def reset(self):
        self.correction_attempts = 0

    def can_attempt_correction(self):
        return self.correction_attempts < self.policy.max_correction_attempts

    def register_correction_attempt(self):
        if not self.can_attempt_correction():
            return False
        self.correction_attempts += 1
        return True

    def requires_approval_to_apply(self):
        return self.policy.mode != AutonomyMode.AUTONOMOUS

    def can_run_build(self):
        return self.policy.allow_build

    def can_run_fullclean(self):
        return self.policy.allow_fullclean

    def can_flash(self):
        return False