import numpy as np

from sketchforge.vision import handwriting_ocr
from sketchforge.vision.text_regions import TextRegion


def test_recognize_regions_uses_opt_in_model_and_returns_line_text(monkeypatch):
    class Processor:
        def __call__(self, **kwargs):
            return type("Batch", (), {"pixel_values": object()})()

        def batch_decode(self, generated, skip_special_tokens):
            assert skip_special_tokens
            return ["Hello world"]

    class Model:
        def generate(self, pixels, max_new_tokens):
            assert max_new_tokens == 64
            return object()

    monkeypatch.setenv("SKETCHFORGE_OCR_MODEL", "local-test-model")
    monkeypatch.setattr(handwriting_ocr, "_load_model", lambda name: (("trocr", Processor()), Model()))
    region = TextRegion(0, (2, 3, 20, 8), ink_pixels=20, pieces=4, confidence=0.8)
    recognized = handwriting_ocr.recognize_regions(np.full((20, 30), 255, np.uint8), [region])
    assert recognized == ["Hello world"]


def test_recognize_regions_is_off_without_model_setting(monkeypatch):
    monkeypatch.delenv("SKETCHFORGE_OCR_MODEL", raising=False)
    region = TextRegion(0, (0, 0, 10, 6), ink_pixels=10, pieces=2, confidence=0.5)
    assert handwriting_ocr.recognize_regions(np.zeros((20, 20), np.uint8), [region]) == [""]
