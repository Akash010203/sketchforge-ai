"""Main training loop for the SketchForge component detector.

Implements the disciplined training cycle:
  seed → data → model → optimizer → scheduler → epoch loop →
  validate → checkpoint → early-stop → test → report
"""
from __future__ import annotations

import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from sketchforge.training.config import TrainingConfig
from sketchforge.training.seed import seed_everything
from sketchforge.training.early_stopping import EarlyStopping
from sketchforge.training.metrics import EpochMetrics, compute_accuracy
from sketchforge.training.checkpoint_manager import CheckpointManager
from sketchforge.training.training_report import TrainingReport
from sketchforge.training.validation import validate_epoch


def _loss_and_metrics(model, images, targets, num_classes, amp=False, return_outputs=False):
    """Compute anchor classification and regression loss for a batch."""
    import torch
    import torch.nn.functional as F
    from sketchforge.training.detection_targets import match_batch
    amp_context = (torch.autocast(device_type="cuda", dtype=torch.float16)
                   if amp and images.device.type == "cuda" else nullcontext())
    with amp_context:
        outputs = model(images)
    # Keep anchor matching and regression loss in fp32 for numerical stability.
    outputs = [(cls.float(), box.float()) for cls, box in outputs]
    logits, deltas, class_ids, box_targets, positive = match_batch(
        outputs, targets, num_classes)
    ce = F.cross_entropy(logits.reshape(-1, num_classes), class_ids.reshape(-1), reduction="none")
    probs = torch.exp(-ce)
    alpha = torch.where(class_ids.reshape(-1) == 0, 0.25, 1.0)
    cls_loss = (alpha * (1.0 - probs).square() * ce).mean()
    box_loss = (F.smooth_l1_loss(deltas[positive], box_targets[positive])
                if positive.any() else deltas.sum() * 0)
    loss = cls_loss + 2.0 * box_loss
    predicted = logits.argmax(dim=-1)
    accuracy = (predicted == class_ids).float().mean().item()
    if return_outputs:
        return loss, accuracy, cls_loss, box_loss, outputs
    return loss, accuracy, cls_loss, box_loss


def train(cfg: TrainingConfig, smoke_test: bool = False) -> TrainingReport:
    """Run the full training loop.

    Args:
        cfg: Training configuration.
        smoke_test: If True, run only 1 epoch with 2 batches to verify the pipeline.

    Returns:
        TrainingReport with per-epoch metrics and test results.
    """
    try:
        import torch
        from torch.optim import AdamW
        from torch.optim.lr_scheduler import CosineAnnealingLR, StepLR
    except ImportError:
        raise ImportError("PyTorch is required. Install: pip install torch torchvision")

    seed_everything(cfg.seed)
    device = torch.device(cfg.resolve_device())
    print(f"[trainer] device={device}  seed={cfg.seed}")

    # ---- data ----------------------------------------------------------------
    from sketchforge.training.dataloader import make_loaders
    train_loader, val_loader, test_loader = make_loaders(cfg)
    print(f"[trainer] train={len(train_loader.dataset)} val={len(val_loader.dataset)} test={len(test_loader.dataset)}")

    # ---- model ---------------------------------------------------------------
    from sketchforge.models.component_detector.architecture import build_model
    model = build_model(num_classes=cfg.num_classes).to(device)
    if device.type == "cuda" and cfg.channels_last:
        model = model.to(memory_format=torch.channels_last)
        torch.backends.cudnn.benchmark = True
        torch.backends.cudnn.deterministic = False
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[trainer] model={model.__class__.__name__} params={n_params:,}")

    # ---- loss + optimiser ----------------------------------------------------
    optimizer = AdamW(model.parameters(), lr=cfg.learning_rate, weight_decay=cfg.weight_decay)

    if cfg.lr_scheduler == "cosine":
        scheduler = CosineAnnealingLR(optimizer, T_max=cfg.epochs, eta_min=1e-6)
    elif cfg.lr_scheduler == "step":
        scheduler = StepLR(optimizer, step_size=cfg.lr_step_size, gamma=cfg.lr_gamma)
    else:
        scheduler = None

    # ---- training scaffolding ------------------------------------------------
    ckpt_mgr   = CheckpointManager(cfg.checkpoint_path(), keep_best_n=cfg.keep_best_n,
                                  resume_history=False, mode="max")
    stopper    = EarlyStopping(patience=cfg.patience, min_delta=cfg.min_delta, mode="max")
    report     = TrainingReport(model_name=cfg.model_name, config=cfg.__dict__.copy())
    max_epochs = 1 if smoke_test else cfg.epochs
    max_batches = 2 if smoke_test else None
    amp_enabled = device.type == "cuda" and cfg.mixed_precision
    scaler = torch.amp.GradScaler("cuda", enabled=amp_enabled, init_scale=1024.0)

    # ---- epoch loop ----------------------------------------------------------
    for epoch in range(1, max_epochs + 1):
        model.train()
        ep_loss = ep_acc = ep_cls_loss = ep_box_loss = 0.0
        n_batches = 0
        n_samples = 0
        optimizer_steps = 0
        t0 = time.perf_counter()

        for i, (images, targets) in enumerate(train_loader):
            if max_batches and i >= max_batches:
                break

            images = images.to(device, non_blocking=True)
            if device.type == "cuda" and cfg.channels_last:
                images = images.contiguous(memory_format=torch.channels_last)
            optimizer.zero_grad(set_to_none=True)
            loss, accuracy, cls_loss, box_loss = _loss_and_metrics(
                model, images, targets, cfg.num_classes, amp=amp_enabled)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            previous_scale = scaler.get_scale()
            scaler.step(optimizer)
            scaler.update()
            optimizer_steps += int(not amp_enabled or scaler.get_scale() >= previous_scale)

            ep_loss += loss.item()
            ep_acc  += accuracy
            ep_cls_loss += cls_loss.item()
            ep_box_loss += box_loss.item()
            n_batches += 1
            n_samples += images.shape[0]

        if scheduler and optimizer_steps:
            scheduler.step()

        n = max(n_batches, 1)
        train_metrics = EpochMetrics(
            epoch=epoch, phase="train",
            loss=ep_loss / n, accuracy=ep_acc / n,
            cls_loss=ep_cls_loss / n, box_loss=ep_box_loss / n,
            samples=n_samples,
            duration_s=time.perf_counter() - t0,
        )
        report.add_epoch(train_metrics)
        print(train_metrics.summary())

        # val
        val_metrics = validate_epoch(model, val_loader, None, device, epoch, phase="val",
                                     num_classes=cfg.num_classes, amp=amp_enabled,
                                     channels_last=cfg.channels_last)
        report.add_epoch(val_metrics)
        print(val_metrics.summary())

        # At the start of training AP may still be zero; box loss then tracks
        # useful localization convergence until detections begin to match.
        selection_score = (val_metrics.mAP25 if val_metrics.mAP25 > 0
                           else -val_metrics.box_loss)
        val_record = val_metrics.to_dict()
        val_record["selection_score"] = selection_score

        # checkpoint every N epochs
        if epoch % cfg.save_every_n_epochs == 0:
            ckpt_mgr.save(model, optimizer, epoch, val_record, cfg.__dict__)

        # early stopping
        if stopper.step(selection_score, epoch):
            print(f"[trainer] early stop at epoch {epoch}. {stopper.status()}")
            break

    # ---- test ----------------------------------------------------------------
    best = ckpt_mgr.load()
    if best is not None:
        model.load_state_dict(best["model_state_dict"])
        best_epoch = int(best["epoch"])
    else:
        best_epoch = epoch
    test_metrics = validate_epoch(model, test_loader, None, device, epoch=best_epoch, phase="test",
                                  num_classes=cfg.num_classes, amp=amp_enabled,
                                  channels_last=cfg.channels_last)
    report.finish(test=test_metrics, stopped_early=stopper.triggered)

    # ---- save final checkpoint -----------------------------------------------
    if ckpt_mgr.best() is None:
        # Smoke runs shorter than the configured save interval still produce a valid checkpoint.
        ckpt_mgr.save(model, optimizer, epoch, val_record, cfg.__dict__)
    report_dir = Path(cfg.checkpoint_dir) / "reports"
    json_p, md_p = report.save(report_dir)
    print(f"[trainer] report saved: {md_p}")
    return report


def smoke_test(cfg: TrainingConfig | None = None) -> bool:
    """Run 1 epoch / 2 batches to verify the pipeline end-to-end.

    Returns True if successful.
    """
    if cfg is None:
        cfg = TrainingConfig(
            epochs=1, batch_size=2, num_workers=0,
            save_every_n_epochs=1, checkpoint_dir="checkpoints/smoke",
        )
    print("[smoke_test] starting …")
    try:
        report = train(cfg, smoke_test=True)
        ep = report.epochs[0]
        assert ep.loss < 1e9, "Loss is not finite"
        print(f"[smoke_test] PASS — loss={ep.loss:.4f} acc={ep.accuracy:.3f}")
        return True
    except Exception as e:
        print(f"[smoke_test] FAIL — {e}")
        return False
