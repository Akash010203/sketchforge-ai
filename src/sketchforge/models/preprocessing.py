"""Model preprocessing: normalisation transforms applied before inference."""
from __future__ import annotations

import numpy as np


# ImageNet stats (used during training)
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def preprocess_for_inference(image_bgr: np.ndarray, target_size: int = 512) -> "torch.Tensor":
    """Convert a BGR OpenCV image to a normalised float tensor (1, C, H, W).

    Steps:
        1. Resize to ``target_size × target_size``
        2. BGR → RGB
        3. [0, 255] uint8 → [0, 1] float32
        4. Normalise with ImageNet mean/std
        5. HWC → CHW → add batch dim
    """
    import cv2
    import torch

    img = cv2.resize(image_bgr, (target_size, target_size), interpolation=cv2.INTER_LINEAR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img = (img - _MEAN) / _STD          # (H, W, C)
    tensor = torch.from_numpy(img.transpose(2, 0, 1)).unsqueeze(0)  # (1, C, H, W)
    return tensor


def denormalise(tensor: "torch.Tensor") -> np.ndarray:
    """Reverse normalisation for visualisation.  Returns uint8 RGB numpy array."""
    arr = tensor.squeeze(0).permute(1, 2, 0).cpu().numpy()
    arr = (arr * _STD + _MEAN).clip(0, 1)
    return (arr * 255).astype(np.uint8)
