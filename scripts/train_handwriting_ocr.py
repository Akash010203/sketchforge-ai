#!/usr/bin/env python
"""Train SketchForge's offline CTC handwriting recognizer on Teklia/IAM-line parquet splits."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sketchforge.models.handwriting_ocr import build_model  # noqa: E402

ALPHABET = "\t\n\r" + "".join(chr(i) for i in range(32, 127))
CHAR_TO_ID = {character: i + 1 for i, character in enumerate(ALPHABET)}
HEIGHT = 48


class IAMLines(Dataset):
    def __init__(self, parquet_path: Path):
        table = pq.read_table(parquet_path, columns=["text", "image"])
        self.texts = table.column("text").to_pylist()
        self.images = table.column("image").to_pylist()

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, index):
        text = "".join(c for c in self.texts[index] if c in CHAR_TO_ID).strip()
        raw = self.images[index]["bytes"]
        image = np.asarray(Image.open(__import__("io").BytesIO(raw)).convert("L"))
        width = max(16, round(image.shape[1] * HEIGHT / image.shape[0]))
        image = cv2.resize(image, (width, HEIGHT), interpolation=cv2.INTER_AREA)
        image = (255 - image).astype(np.float32) / 255.0
        target = np.asarray([CHAR_TO_ID[c] for c in text], dtype=np.int32)
        return image, target


def collate(batch):
    images, targets = zip(*batch, strict=True)
    width = max(image.shape[1] for image in images)
    width = (width + 3) // 4 * 4
    tensor = torch.zeros((len(images), 1, HEIGHT, width), dtype=torch.float32)
    lengths = []
    for i, image in enumerate(images):
        tensor[i, 0, :, :image.shape[1]] = torch.from_numpy(image)
        lengths.append(image.shape[1] // 4)
    target_lengths = torch.tensor([len(target) for target in targets], dtype=torch.long)
    flat_targets = torch.from_numpy(np.concatenate(targets).astype(np.int64))
    return tensor, flat_targets, torch.tensor(lengths), target_lengths


def evaluate(model, loader, loss_fn, device):
    model.eval()
    losses = []
    with torch.inference_mode():
        for images, targets, input_lengths, target_lengths in loader:
            logits = model(images.to(device))
            losses.append(float(loss_fn(logits, targets.to(device), input_lengths, target_lengths)))
    return float(np.mean(losses)) if losses else float("inf")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "datasets/raw/teklia-iam-line/data")
    parser.add_argument("--out", type=Path, default=ROOT / "checkpoints/handwriting_ocr.pt")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    train = DataLoader(IAMLines(args.data / "train.parquet"), batch_size=args.batch_size,
                       shuffle=True, collate_fn=collate, num_workers=0)
    valid = DataLoader(IAMLines(args.data / "validation.parquet"), batch_size=args.batch_size,
                       shuffle=False, collate_fn=collate, num_workers=0)
    device = torch.device(args.device)
    model = build_model(len(ALPHABET) + 1).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = torch.nn.CTCLoss(blank=0, zero_infinity=True)
    best = float("inf")
    for epoch in range(1, args.epochs + 1):
        model.train()
        batch_losses = []
        for images, targets, input_lengths, target_lengths in train:
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = loss_fn(logits, targets, input_lengths, target_lengths)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            batch_losses.append(float(loss.detach()))
        val_loss = evaluate(model, valid, loss_fn, device)
        train_loss = float(np.mean(batch_losses))
        print(f"epoch {epoch}/{args.epochs}: train_ctc={train_loss:.4f} val_ctc={val_loss:.4f}", flush=True)
        if val_loss < best:
            best = val_loss
            args.out.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"state_dict": model.cpu().state_dict(), "alphabet": ALPHABET,
                        "height": HEIGHT, "validation_ctc_loss": best}, args.out)
            model.to(device)
    print(f"best validation CTC loss {best:.4f}; saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
