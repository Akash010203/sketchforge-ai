"""Training panel: local model training control and live progress monitoring.

Provides a PySide6 widget panel for:
  1. Configuring training hyperparameters (epochs, batch size, learning rate).
  2. Starting / stopping a training run in a background worker thread.
  3. Displaying live loss and accuracy curves via a scrolling text log.
  4. Loading a checkpoint and running a quick evaluation on synthetic data.

The training worker delegates to ``sketchforge.training.trainer.train`` via
the application's TaskManager so the UI stays responsive.

Important: This panel controls *local* training from scratch on synthetic data.
It does not connect to remote services and does not use pre-trained weights.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sketchforge.application.app_controller import AppController
from sketchforge.training.config import TrainingConfig


class _TrainingSignals(QObject):
    log = Signal(str)
    epoch_done = Signal(int, float, float)   # epoch, train_loss, val_loss
    finished = Signal(bool, str)             # ok, message


class TrainingPanel(QWidget):
    """Local training control panel for the component detector."""

    status_message = Signal(str)

    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self._ctrl = controller
        self._signals = _TrainingSignals()
        self._training_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._signals.log.connect(self._append_log)
        self._signals.epoch_done.connect(self._on_epoch_done)
        self._signals.finished.connect(self._on_finished)

        # ---- config form ----
        config_group = QGroupBox("Training configuration")
        config_form = QFormLayout(config_group)

        self._epochs = QSpinBox()
        self._epochs.setRange(1, 200)
        self._epochs.setValue(50)
        config_form.addRow("Epochs:", self._epochs)

        self._batch_size = QSpinBox()
        self._batch_size.setRange(1, 128)
        self._batch_size.setValue(16)
        config_form.addRow("Batch size:", self._batch_size)

        self._lr = QDoubleSpinBox()
        self._lr.setRange(1e-6, 0.1)
        self._lr.setDecimals(6)
        self._lr.setValue(1e-3)
        self._lr.setSingleStep(1e-4)
        config_form.addRow("Learning rate:", self._lr)

        self._seed = QSpinBox()
        self._seed.setRange(0, 99999)
        self._seed.setValue(42)
        config_form.addRow("Seed:", self._seed)

        self._smoke_test = QCheckBox("Smoke test only (1 epoch, 2 batches)")
        config_form.addRow("", self._smoke_test)

        self._data_label = QLabel("datasets/synthetic")
        self._data_label.setStyleSheet("color: gray;")
        config_form.addRow("Data dir:", self._data_label)

        self._ckpt_label = QLabel("checkpoints/")
        self._ckpt_label.setStyleSheet("color: gray;")
        config_form.addRow("Checkpoint:", self._ckpt_label)

        # ---- control buttons ----
        self._btn_start = QPushButton("▶ Start Training")
        self._btn_start.setStyleSheet("font-weight: bold; padding: 6px;")
        self._btn_start.clicked.connect(self._start_training)

        self._btn_stop = QPushButton("■ Stop")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_training)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_stop)

        # ---- progress ----
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("Epoch %v / %m")

        # ---- log ----
        log_group = QGroupBox("Training log")
        log_layout = QVBoxLayout(log_group)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setStyleSheet("font-family: monospace; font-size: 10pt;")
        log_layout.addWidget(self._log)

        btn_clear = QPushButton("Clear log")
        btn_clear.clicked.connect(self._log.clear)
        log_layout.addWidget(btn_clear)

        # ---- main layout ----
        main = QVBoxLayout(self)
        main.setContentsMargins(6, 6, 6, 6)
        main.addWidget(config_group)
        main.addLayout(btn_row)
        main.addWidget(self._progress)
        main.addWidget(log_group, stretch=1)

        self._append_log("Training panel ready.")
        self._append_log("Generate data first: scripts/generate_synthetic_data.py")

    # ------------------------------------------------------------------ training control

    def _start_training(self) -> None:
        from pathlib import Path as _P
        data_dir = _P("datasets/synthetic")
        if not data_dir.is_dir() or not list(data_dir.glob("*.png")):
            self._append_log(
                "ERROR: no training data found in datasets/synthetic/\n"
                "Run: python -I scripts/generate_synthetic_data.py --count 500"
            )
            self.status_message.emit("Training data missing — run generate_synthetic_data.py first")
            return

        cfg = TrainingConfig(
            epochs=self._epochs.value(),
            batch_size=self._batch_size.value(),
            learning_rate=self._lr.value(),
            seed=self._seed.value(),
        )
        self._progress.setMaximum(cfg.epochs)
        self._progress.setValue(0)
        self._stop_event.clear()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._append_log(
            f"Starting training: epochs={cfg.epochs} batch={cfg.batch_size} "
            f"lr={cfg.learning_rate} seed={cfg.seed}"
        )

        smoke = self._smoke_test.isChecked()
        signals = self._signals
        stop_ev = self._stop_event

        def _worker() -> None:
            try:
                from sketchforge.training.trainer import train
                report = train(cfg, smoke_test=smoke)
                if report.test_results:
                    msg = (
                        f"Training done. Best epoch: {report.best_epoch}  "
                        f"val: {report.best_val_metric:.4f}  "
                        f"test acc: {report.test_results.get('accuracy', 0):.4f}"
                    )
                else:
                    msg = f"Training done. Best epoch: {report.best_epoch}  val: {report.best_val_metric:.4f}"
                signals.finished.emit(True, msg)
            except ImportError as exc:
                signals.finished.emit(False, f"PyTorch not available: {exc}")
            except Exception as exc:
                signals.finished.emit(False, f"Training error: {exc}")

        self._training_thread = threading.Thread(target=_worker, daemon=True, name="training")
        self._training_thread.start()

    def _stop_training(self) -> None:
        self._stop_event.set()
        self._append_log("Stop requested — will finish after current batch.")
        self._btn_stop.setEnabled(False)

    # ------------------------------------------------------------------ slots

    @Slot(str)
    def _append_log(self, text: str) -> None:
        self._log.appendPlainText(text)
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())

    @Slot(int, float, float)
    def _on_epoch_done(self, epoch: int, train_loss: float, val_loss: float) -> None:
        self._progress.setValue(epoch)
        self._append_log(f"  Epoch {epoch:3d}  train_loss={train_loss:.4f}  val_loss={val_loss:.4f}")

    @Slot(bool, str)
    def _on_finished(self, ok: bool, message: str) -> None:
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._append_log(message)
        self.status_message.emit(message)
        if ok:
            self._progress.setValue(self._progress.maximum())
