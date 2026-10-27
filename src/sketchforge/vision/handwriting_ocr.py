"""Optional offline handwritten line recognition.

Point ``SKETCHFORGE_OCR_MODEL`` at a local SketchForge CTC checkpoint for fully offline use.
Hugging Face TrOCR remains supported as a compatibility fallback for model IDs/directories.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from sketchforge.vision.text_regions import TextRegion


@lru_cache(maxsize=1)
def _load_model(model_name: str):
    path = Path(model_name)
    if path.is_file() and path.suffix.lower() in {".pt", ".pth"}:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("Offline handwriting OCR needs the optional 'ocr' dependencies.") from exc
        from sketchforge.models.handwriting_ocr import build_model

        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        alphabet = checkpoint["alphabet"]
        model = build_model(len(alphabet) + 1)
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        return ("ctc", alphabet), model
    try:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    except ImportError as exc:
        raise RuntimeError(
            "Handwriting OCR needs the optional 'ocr' dependencies; install sketchforge[ocr]."
        ) from exc
    processor = TrOCRProcessor.from_pretrained(model_name)
    model = VisionEncoderDecoderModel.from_pretrained(model_name)
    model.eval()
    return ("trocr", processor), model


def _decode_ctc(logits: np.ndarray, alphabet: str) -> str:
    indices = logits.argmax(axis=-1).tolist()
    result: list[str] = []
    previous = 0
    for index in indices:
        if index and index != previous:
            result.append(alphabet[index - 1])
        previous = index
    return "".join(result).strip()


def recognize_regions(gray: np.ndarray, regions: list[TextRegion]) -> list[str]:
    """Recognize line crops, returning one string per candidate region.

    Blank or unreadable crops return an empty string, allowing callers to preserve the
    clearly flagged inferred placeholder rather than pretending OCR succeeded.
    """
    model_name = os.environ.get("SKETCHFORGE_OCR_MODEL", "").strip()
    if not model_name:
        return [""] * len(regions)
    metadata, model = _load_model(model_name)
    image_h, image_w = gray.shape[:2]
    outputs: list[str] = []
    for region in regions:
        x, y, w, h = region.bbox
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(image_w, int(np.ceil(x + w))), min(image_h, int(np.ceil(y + h)))
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0:
            outputs.append("")
            continue
        # TrOCR was trained on light backgrounds with dark writing.
        if metadata[0] == "ctc":
            import torch

            alphabet = metadata[1]
            height = 48
            width = max(16, int(round(crop.shape[1] * height / crop.shape[0])))
            crop = cv2.resize(crop, (width, height), interpolation=cv2.INTER_CUBIC)
            tensor = torch.from_numpy((255 - crop).astype(np.float32) / 255.0)[None, None]
            with torch.inference_mode():
                logits = model(tensor).squeeze(1).cpu().numpy()
            outputs.append(_decode_ctc(logits, alphabet))
        else:
            processor = metadata[1]
            crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            rgb = cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB)
            pixels = processor(images=Image.fromarray(rgb), return_tensors="pt").pixel_values
            generated = model.generate(pixels, max_new_tokens=64)
            outputs.append(processor.batch_decode(generated, skip_special_tokens=True)[0].strip())
    return outputs
