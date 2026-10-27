"""Early stopping: halt training when validation loss stops improving."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EarlyStopping:
    patience: int = 8
    min_delta: float = 1e-4
    mode: str = "min"    # "min" for loss, "max" for mAP/accuracy
    best_score: float | None = None
    counter: int = 0
    triggered: bool = False
    best_epoch: int = 0

    def step(self, score: float, epoch: int) -> bool:
        """Record ``score`` for ``epoch``. Returns True if training should stop."""
        if self.best_score is None:
            self.best_score = score
            self.best_epoch = epoch
            return False

        improved = (
            (self.mode == "min" and score < self.best_score - self.min_delta) or
            (self.mode == "max" and score > self.best_score + self.min_delta)
        )
        if improved:
            self.best_score = score
            self.best_epoch = epoch
            self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.triggered = True
                return True
        return False

    def status(self) -> str:
        return (
            f"EarlyStopping: best={self.best_score:.6f} @ epoch {self.best_epoch}, "
            f"counter={self.counter}/{self.patience}"
        )
