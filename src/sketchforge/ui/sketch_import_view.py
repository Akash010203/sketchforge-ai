"""The imported sketch, with the detector's boxes drawn on top so they can be checked by eye."""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QCheckBox, QLabel, QScrollArea, QVBoxLayout, QWidget

from sketchforge.application.app_controller import AppController
from sketchforge.vision.visualization import draw_detections


def bgr_to_pixmap(image: np.ndarray) -> QPixmap:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    qimage = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()  # copy: detach from numpy
    return QPixmap.fromImage(qimage)


class SketchImportView(QWidget):
    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        self.show_boxes = QCheckBox("Show detections")
        self.show_boxes.setChecked(True)
        self.info = QLabel("No sketch imported.")
        self.info.setWordWrap(True)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea()
        scroll.setWidget(self.image_label)
        scroll.setWidgetResizable(True)
        layout.addWidget(self.info)
        layout.addWidget(self.show_boxes)
        layout.addWidget(scroll, 1)
        self.show_boxes.toggled.connect(lambda _: self.refresh())

    def refresh(self) -> None:
        if not self.controller.has_project:
            self.image_label.clear()
            self.info.setText("No sketch imported.")
            return
        project = self.controller.project
        vision = project.vision
        if vision is not None:
            image = vision.normalized.color
            if self.show_boxes.isChecked():
                image = draw_detections(image, vision.detections, vision.proposals.frame)
            notes = f" · {'; '.join(vision.notes[:2])}" if vision.notes else ""
            self.info.setText(
                f"{project.source.name if project.source else 'sketch'} · {len(vision.detections)} detections · "
                f"threshold: {vision.preprocessed.variant}{notes}")
        elif project.source is not None:
            image = project.source.bgr
            self.info.setText(f"{project.source.name} (reopened project: detections are not stored)")
        else:
            self.image_label.clear()
            self.info.setText("This project has no source sketch.")
            return
        pix = bgr_to_pixmap(image)
        if pix.width() > 900:
            pix = pix.scaledToWidth(900, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(pix)
