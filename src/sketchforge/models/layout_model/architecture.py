"""Small encoder-decoder for semantic UI layout maps."""
from __future__ import annotations


def build_model(num_classes: int = 15, width: int = 24):
    """Create a compact semantic segmentation model without pretrained weights."""
    import torch.nn as nn
    import torch.nn.functional as F

    class ConvBlock(nn.Module):
        def __init__(self, in_ch, out_ch):
            super().__init__()
            self.layers = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_ch), nn.SiLU(inplace=True),
                nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_ch), nn.SiLU(inplace=True),
            )

        def forward(self, x):
            return self.layers(x)

    class Model(nn.Module):
        def __init__(self):
            super().__init__()
            self.enc1 = ConvBlock(1, width)
            self.enc2 = ConvBlock(width, width * 2)
            self.enc3 = ConvBlock(width * 2, width * 4)
            self.pool = nn.MaxPool2d(2)
            self.up2 = ConvBlock(width * 6, width * 2)
            self.up1 = ConvBlock(width * 3, width)
            self.semantic = nn.Conv2d(width, num_classes, 1)
            self.alignment = nn.Linear(width * 4, 4)

        def forward(self, image):
            import torch

            e1 = self.enc1(image)
            e2 = self.enc2(self.pool(e1))
            e3 = self.enc3(self.pool(e2))
            d2 = F.interpolate(e3, size=e2.shape[-2:], mode="bilinear", align_corners=False)
            d2 = self.up2(torch.cat((d2, e2), dim=1))
            d1 = F.interpolate(d2, size=e1.shape[-2:], mode="bilinear", align_corners=False)
            d1 = self.up1(torch.cat((d1, e1), dim=1))
            return {"semantic_logits": self.semantic(d1),
                    "alignment_logits": self.alignment(e3.mean(dim=(-2, -1)))}

    return Model()


LayoutModel = build_model
