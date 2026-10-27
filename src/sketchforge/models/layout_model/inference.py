"""Inference wrapper for semantic UI layout checkpoints."""
from __future__ import annotations

from pathlib import Path


class LayoutInference:
    def __init__(self, checkpoint_path: str | Path, device: str = "auto"):
        import torch
        from sketchforge.models.device import get_device
        from sketchforge.models.layout_model.architecture import build_model

        self.device = get_device(None if device == "auto" else device)
        checkpoint = torch.load(str(checkpoint_path), map_location=self.device, weights_only=True)
        config = checkpoint.get("config", {})
        self.model = build_model(num_classes=config.get("num_classes", 15),
                                 width=config.get("width", 24)).to(self.device)
        self.model.load_state_dict(checkpoint.get("model_state_dict", checkpoint))
        self.model.eval()

    def predict(self, image):
        import torch
        import cv2
        import numpy as np
        from sketchforge.models.component_detector.architecture import COMPONENT_CLASSES

        if image.ndim == 3:
            image = image.unsqueeze(0)
        with torch.no_grad():
            output = self.model(image.to(self.device))
            class_map = output["semantic_logits"].argmax(1)[0].cpu().numpy().astype(np.uint8)
            alignment = output["alignment_logits"].sigmoid()[0].cpu().tolist()
        h, w = class_map.shape
        boxes = []
        for class_id in np.unique(class_map):
            if class_id == 0:
                continue
            count, _, stats, _ = cv2.connectedComponentsWithStats(
                (class_map == class_id).astype(np.uint8), 8)
            for component_id in range(1, count):
                x, y, bw, bh, area = map(int, stats[component_id])
                if area < 4:
                    continue
                boxes.append({"class_id": int(class_id),
                              "class_name": COMPONENT_CLASSES[int(class_id)],
                              "bbox": (x / w, y / h, bw / w, bh / h)})
        # Group boxes sharing a row or column into simple flex-like layout groups.
        groups = {"rows": [], "columns": []}
        for axis, key in ((1, "rows"), (0, "columns")):
            ordered = sorted(range(len(boxes)),
                             key=lambda i: boxes[i]["bbox"][axis] + boxes[i]["bbox"][axis + 2] / 2)
            current, center = [], None
            for index in ordered:
                box = boxes[index]["bbox"]
                value = box[axis] + box[axis + 2] / 2
                if center is None or abs(value - center) <= 0.04:
                    current.append(index)
                    center = value if center is None else (center * (len(current) - 1) + value) / len(current)
                else:
                    if len(current) > 1:
                        groups[key].append(current)
                    current, center = [index], value
            if len(current) > 1:
                groups[key].append(current)
        return {"class_map": class_map, "boxes": boxes,
                "alignment": alignment, "groups": groups}
