# Training guide

The component detector has a synthetic-only 10-epoch CUDA run. Its best checkpoint is `../checkpoints/component_detector_v1/best.pt`. A smoke run covers data loading, forward pass, finite loss, backpropagation, validation, and checkpoint creation. The training data is generated locally; external screenshot/HTML records without box labels are not included.

The detector loader groups samples by layout template when at least three templates exist, keeping validation and test templates out of training. The current held-out validation/test sets each contain one synthetic layout template; scores do not establish real-sketch performance. Detection IoU/mAP are not yet calculated by the training loop. Compare with the deterministic baseline before claiming an improvement. Training configuration defaults are in `../config/training.yaml`.
