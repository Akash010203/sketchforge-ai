# Vision Models: Real Photographed Sketch Training Roadmap

**Date:** 2026-10-25  
**Component:** Local Vision Model (`src/sketchforge/models/`, `experiments/`)  
**Status:** Architecture & Dataset Curation Specification (Item 9)

---

## 1. Problem Statement

On synthetic sketches (`assets/sample_sketches/`), the local rule-based OpenCV detector achieves **F1 0.982**, type accuracy **0.946**, and mean IoU **0.835**.
However, on real-world photographed paper sketches (`experiments/results/real_photo_benchmark.json`):
- Uneven ambient lighting, paper grain, and oblique shadows cause adaptive thresholding to fragment large contours.
- Pre-printed grid lines (notebook graph paper) create spurious bounding box intersections.
- Hand-drawn wobble breaks simple geometric convexity tests (`cv2.approxPolyDP`).
- Real-world benchmark yields **F1 0.0031** on unrectified photographs.

---

## 2. Dataset Curation Protocol

To advance the local vision system beyond synthetic layouts:

### A. Target Dataset Size
- **500 real photographed sketches** collected under 5 distinct lighting conditions:
  1. Direct daylight (high contrast)
  2. Warm indoor artificial lighting (2700K - 3000K, uneven falloff)
  3. Harsh directional side lighting (casting long shadows across strokes)
  4. Dim / underexposed ambient lighting (< 100 lux)
  5. Multi-light source with cast mobile device shadows
- **Paper substrates**: Blank white paper (40%), dot-grid notebook (30%), lined ruled paper (20%), yellow legal pad (10%).
- **Writing instruments**: Black ballpoint, blue ink, graphite pencil (HB and 2B), felt-tip marker, whiteboard marker.

### B. Annotation Schema (`COCO` and `DesignDocument` IR compatible)
Each image must have:
- Perspective corner points (`[top_left, top_right, bottom_right, bottom_left]`) for automatic 4-point quadrilateral rectification.
- Component bounding boxes in normalized coordinates `[ymin, xmin, ymax, xmax]`.
- Categorical class labels aligned with `sketchforge.design_ir.schema.ComponentType`:
  `BUTTON`, `INPUT`, `CARD`, `CONTAINER`, `HEADER`, `FOOTER`, `SIDEBAR`, `HEADING`, `TEXT`, `IMAGE`, `CHECKBOX`, `RADIO`, `DIVIDER`.
- Text transcripts for handwritten labels (`ocr_label`).

---

## 3. Augmentation & Preprocessing Pipeline

Before feeding into the convolutional feature extractor (`Compact CNN + FPN`):
1. **Dynamic Illumination Flattening**:
   - Rolling ball or morphological closing with large kernel ($51 \times 51$) to estimate background intensity surface.
   - Contrast Limited Adaptive Histogram Equalization (CLAHE) on luminance ($L^*$) channel in CIELAB space.
2. **Synthetic Grid/Shadow Injection Augmentation**:
   - Random shadow overlays (polygonal low-opacity alpha masks).
   - Frequency-domain notch filtering for notebook grid lines (detecting dominant orthogonal peaks in 2D FFT).
3. **Geometric Jitter**:
   - Random perspective warp ($|\theta| \le 15^\circ$), bilinear scaling ($0.8\times - 1.2\times$), and slight shear.

---

## 4. Model Architecture & Training Schedule

- **Architecture**: MobileNetV4 / EfficientNet-B0 backbone with Feature Pyramid Network (FPN) and anchor-free box regression head (`checkpoints/component_detector_v1/`).
- **Input Resolution**: $640 \times 640 \times 3$.
- **Loss Function**:
  $$\mathcal{L} = \mathcal{L}_{\text{Focal}}(\text{cls}) + \lambda_1 \mathcal{L}_{\text{GIoU}}(\text{bbox}) + \lambda_2 \mathcal{L}_{\text{L1}}(\text{corners})$$
- **Training Schedule**:
  - Phase 1: Pre-train on 10,000 synthetic layouts (20 epochs).
  - Phase 2: Fine-tune on 500 annotated real photographed sketches with heavy photometric augmentation (50 epochs, cosine annealing learning rate $1\times 10^{-4} \to 1\times 10^{-6}$).
- **Target Metrics**: Real-photo test set F1 $\ge 0.85$, mean IoU $\ge 0.70$.
