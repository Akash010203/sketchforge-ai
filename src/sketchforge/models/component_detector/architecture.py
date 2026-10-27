"""Lightweight CNN component detector for sketch UI elements.

Design goals:
- Runs on CPU in < 200 ms per image (< 800 px long side).
- Trained from random initialization on synthetic + real sketch data.
- Input: grayscale ink-mask image (1 × H × W), values in [0, 1].
- Output: per-anchor class scores + bounding-box offsets.

Architecture: MobileNet-style depthwise-separable convolutions with a FPN-lite
feature pyramid, followed by a shared detection head.  The backbone is deliberately
small so it trains on a CPU in a reasonable time.

Anchor grid:
  Three scales (0.1, 0.2, 0.4 of feature-map stride) at three aspect ratios
  (1:1, 2:1, 1:2).  Total: 3 × 3 = 9 anchors per spatial location.

This module requires PyTorch.  The rest of SketchForge does not depend on it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch
    import torch.nn as nn

# ──────────────────────────────────────────── component classes ────────────────
COMPONENT_CLASSES = [
    "background",
    "header",
    "footer",
    "sidebar",
    "card",
    "container",
    "button",
    "input",
    "text",
    "heading",
    "image",
    "divider",
    "checkbox",
    "radio",
    "unknown",
]
NUM_CLASSES = len(COMPONENT_CLASSES)  # 15
CLASS_TO_IDX = {c: i for i, c in enumerate(COMPONENT_CLASSES)}

ANCHOR_SCALES = (0.10, 0.20, 0.40)
ANCHOR_RATIOS = (1.0, 2.0, 0.5)
NUM_ANCHORS = len(ANCHOR_SCALES) * len(ANCHOR_RATIOS)  # 9


def _anchors_for_scale(scale: float, ratios: tuple[float, ...]) -> list[tuple[float, float]]:
    """Return (w, h) anchors as fractions of the feature stride."""
    out = []
    for r in ratios:
        w = scale * (r ** 0.5)
        h = scale / (r ** 0.5)
        out.append((w, h))
    return out


# ─────────────────────────────────────── backbone building blocks ─────────────────────────────

def _dw_conv(in_ch: int, out_ch: int, stride: int = 1) -> "nn.Module":
    import torch.nn as nn

    return nn.Sequential(
        nn.Conv2d(in_ch, in_ch, 3, stride=stride, padding=1, groups=in_ch, bias=False),
        nn.BatchNorm2d(in_ch),
        nn.ReLU6(inplace=True),
        nn.Conv2d(in_ch, out_ch, 1, bias=False),
        nn.BatchNorm2d(out_ch),
        nn.ReLU6(inplace=True),
    )


class _TinyBackbone(object):
    """
    Lazy-constructed backbone. Instantiate via ``TinyBackbone()``.
    Produces P3 (stride 8), P4 (stride 16), P5 (stride 32) feature maps.
    """


def build_backbone() -> "nn.Module":
    """Return the CNN backbone (eager construction for training)."""
    import torch.nn as nn

    class Backbone(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            # stem: 1 → 16 channels, stride 2
            self.stem = nn.Sequential(
                nn.Conv2d(1, 16, 3, stride=2, padding=1, bias=False),
                nn.BatchNorm2d(16),
                nn.ReLU6(inplace=True),
            )
            # Stage 1: 16 → 32, stride 2  → P3
            self.s1 = nn.Sequential(
                _dw_conv(16, 32, stride=2), _dw_conv(32, 32)
            )
            # Stage 2: 32 → 64, stride 2  → P4
            self.s2 = nn.Sequential(
                _dw_conv(32, 64, stride=2), _dw_conv(64, 64)
            )
            # Stage 3: 64 → 128, stride 2 → P5
            self.s3 = nn.Sequential(
                _dw_conv(64, 128, stride=2), _dw_conv(128, 128)
            )

        def forward(self, x: "torch.Tensor") -> tuple["torch.Tensor", "torch.Tensor", "torch.Tensor"]:
            x = self.stem(x)
            p3 = self.s1(x)
            p4 = self.s2(p3)
            p5 = self.s3(p4)
            return p3, p4, p5

    return Backbone()


def build_fpn(in_channels: tuple[int, int, int] = (32, 64, 128), out_ch: int = 64) -> "nn.Module":
    """Feature Pyramid Network lite: lateral 1×1 conv + top-down upsampling."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class FPN(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            c3, c4, c5 = in_channels
            self.lat5 = nn.Conv2d(c5, out_ch, 1)
            self.lat4 = nn.Conv2d(c4, out_ch, 1)
            self.lat3 = nn.Conv2d(c3, out_ch, 1)
            self.out5 = nn.Conv2d(out_ch, out_ch, 3, padding=1)
            self.out4 = nn.Conv2d(out_ch, out_ch, 3, padding=1)
            self.out3 = nn.Conv2d(out_ch, out_ch, 3, padding=1)

        def forward(
            self, p3: "torch.Tensor", p4: "torch.Tensor", p5: "torch.Tensor"
        ) -> tuple["torch.Tensor", "torch.Tensor", "torch.Tensor"]:
            f5 = self.lat5(p5)
            f4 = self.lat4(p4) + F.interpolate(f5, size=p4.shape[-2:], mode="nearest")
            f3 = self.lat3(p3) + F.interpolate(f4, size=p3.shape[-2:], mode="nearest")
            return self.out3(f3), self.out4(f4), self.out5(f5)

    return FPN()


def build_head(in_ch: int = 64, num_classes: int = NUM_CLASSES,
               num_anchors: int = NUM_ANCHORS) -> "nn.Module":
    """Shared classification + regression head."""
    import torch
    import torch.nn as nn

    class Head(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.cls = nn.Sequential(
                _dw_conv(in_ch, in_ch),
                nn.Conv2d(in_ch, num_anchors * num_classes, 1),
            )
            self.reg = nn.Sequential(
                _dw_conv(in_ch, in_ch),
                nn.Conv2d(in_ch, num_anchors * 4, 1),
            )

        def forward(self, feat: "torch.Tensor") -> tuple["torch.Tensor", "torch.Tensor"]:
            b, _, h, w = feat.shape
            cls = self.cls(feat).permute(0, 2, 3, 1).reshape(b, -1, NUM_CLASSES)
            reg = self.reg(feat).permute(0, 2, 3, 1).reshape(b, -1, 4)
            return cls, reg

    return Head()


class ComponentDetectorModel(object):
    """Full model: backbone + FPN + head.  Use ``build_model()`` to create."""


def build_model(
    fpn_channels: int = 64,
    num_classes: int = NUM_CLASSES,
    num_anchors: int = NUM_ANCHORS,
) -> "nn.Module":
    """Construct and return the untrained component detector."""
    import torch
    import torch.nn as nn

    class Model(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.backbone = build_backbone()
            self.fpn = build_fpn(out_ch=fpn_channels)
            self.head = build_head(fpn_channels, num_classes, num_anchors)

        def forward(
            self, x: "torch.Tensor"
        ) -> list[tuple["torch.Tensor", "torch.Tensor"]]:
            """
            Args:
                x: (B, 1, H, W) grayscale ink mask in [0, 1].
            Returns:
                List of (cls_logits, box_deltas) per feature-map level.
                cls_logits: (B, A*H'*W', num_classes)
                box_deltas: (B, A*H'*W', 4)  — (cx, cy, w, h) log-space offsets
            """
            p3, p4, p5 = self.backbone(x)
            f3, f4, f5 = self.fpn(p3, p4, p5)
            return [self.head(f) for f in (f3, f4, f5)]

    return Model()


def parameter_count(model: "nn.Module") -> int:
    return sum(p.numel() for p in model.parameters())
