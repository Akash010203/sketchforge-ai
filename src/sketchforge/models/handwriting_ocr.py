"""Small CNN-BiLSTM-CTC recognizer used by the offline handwriting OCR path."""

from __future__ import annotations


def build_model(num_classes: int, hidden_size: int = 128):
    """Create the compact recognizer. PyTorch is imported lazily for non-OCR installs."""
    import torch.nn as nn

    class CRNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
                nn.MaxPool2d(2, 2),
                nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
                nn.MaxPool2d(2, 2),
                nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
                nn.MaxPool2d((2, 1), (2, 1)),
                nn.Conv2d(128, 192, 3, padding=1), nn.BatchNorm2d(192), nn.ReLU(inplace=True),
                nn.MaxPool2d((2, 1), (2, 1)),
                nn.Conv2d(192, 256, (3, 1), padding=(1, 0)), nn.BatchNorm2d(256),
                nn.ReLU(inplace=True),
            )
            self.sequence = nn.LSTM(256, hidden_size, bidirectional=True, batch_first=True)
            self.classifier = nn.Linear(hidden_size * 2, num_classes)

        def forward(self, images):
            features = self.features(images)
            # Height is collapsed; width is the CTC time axis.
            sequence = features.mean(dim=2).transpose(1, 2)
            sequence, _ = self.sequence(sequence)
            return self.classifier(sequence).log_softmax(dim=-1).transpose(0, 1)

    return CRNN()
