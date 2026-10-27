"""Unit tests for the AWS Graviton (Arm64) and COOL (Cloud-Optimized OpenCV Library) subsystem."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark_cool_graviton import (  # noqa: E402
    compute_cost_efficiency_model,
    generate_benchmark_sketch,
    run_benchmark,
    run_contour_extraction,
    run_illumination_flattening,
    run_morphological_filtering,
)


def test_template_yaml_graviton_configuration():
    """Verify template.yaml explicitly specifies arm64 Graviton and COOL flags."""
    template_path = REPO_ROOT / "deploy" / "aws" / "template.yaml"
    assert template_path.is_file(), "template.yaml must exist"
    content = template_path.read_text(encoding="utf-8")

    # Architectures: [arm64] check
    assert "arm64" in content, "template.yaml must configure arm64"
    assert "COOL_OPTIMIZED" in content, "template.yaml must configure COOL_OPTIMIZED"
    assert "OPENCV_FOR_ARM" in content, "template.yaml must configure OPENCV_FOR_ARM"
    assert "Track: \"Best Use of COOL Award\"" in content or "Best Use of COOL Award" in content


def test_dockerfiles_graviton_support():
    """Verify Dockerfiles target linux/arm64 and set Graviton optimization flags."""
    dockerfile_lambda = REPO_ROOT / "deploy" / "aws" / "Dockerfile"
    dockerfile_ec2 = REPO_ROOT / "deploy" / "aws" / "Dockerfile.graviton"

    assert dockerfile_lambda.is_file()
    assert dockerfile_ec2.is_file()

    content_lambda = dockerfile_lambda.read_text(encoding="utf-8")
    assert "--platform=linux/arm64" in content_lambda
    assert "COOL_OPTIMIZED=1" in content_lambda
    assert "OPENCV_FOR_ARM=1" in content_lambda

    content_ec2 = dockerfile_ec2.read_text(encoding="utf-8")
    assert "--platform=linux/arm64" in content_ec2
    assert "COOL_OPTIMIZED=1" in content_ec2
    assert "OPENCV_FOR_ARM=1" in content_ec2


def test_generate_benchmark_sketch():
    """Verify synthetic sketch generation produces a valid 3-channel image."""
    img = generate_benchmark_sketch(width=320, height=480)
    assert isinstance(img, np.ndarray)
    assert img.shape == (480, 320, 3)
    assert img.dtype == np.uint8
    assert img.mean() > 50  # not blank/empty


def test_illumination_flattening_microbenchmark():
    """Verify illumination flattening with 40x40 morphological dilation."""
    gray = np.full((200, 200), 200, dtype=np.uint8)
    cv2.circle(gray, (100, 100), 30, 50, -1)  # dark circle
    flat = run_illumination_flattening(gray, kernel_size=20)
    assert flat.shape == (200, 200)
    assert flat.dtype == np.uint8


def test_morphological_filtering_microbenchmark():
    """Verify morphological filtering executes ruled-line suppression and adaptive binarization."""
    gray = np.full((300, 300), 240, dtype=np.uint8)
    cv2.line(gray, (0, 150), (300, 150), 30, 2)  # full width line
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    clean = run_morphological_filtering(binary, gray)
    assert clean.shape == (300, 300)
    assert clean.dtype == np.uint8


def test_contour_extraction_microbenchmark():
    """Verify contour tree extraction and shape metric evaluation."""
    binary = np.zeros((300, 300), dtype=np.uint8)
    cv2.rectangle(binary, (50, 50), (200, 150), 255, -1)  # solid rectangle
    cv2.circle(binary, (100, 220), 40, 255, -1)          # solid circle
    results = run_contour_extraction(binary)
    assert len(results) >= 2
    for r in results:
        assert "bbox" in r
        assert "rectangularity" in r
        assert "circularity" in r


def test_cost_efficiency_model():
    """Verify price-performance and cost-savings calculations."""
    results = compute_cost_efficiency_model(e2e_timing_ms=300.0)
    assert len(results) == 2
    x86_model, grav_model = results[0], results[1]

    # Graviton hourly rate is lower ($0.07225 vs $0.085)
    assert grav_model.hourly_rate_usd < x86_model.hourly_rate_usd
    # Graviton achieves more images per dollar
    assert grav_model.images_per_dollar > x86_model.images_per_dollar
    # Relative price performance exceeds 100%
    assert grav_model.relative_price_performance_pct > 130.0
    # Cost savings are roughly ~40%
    assert 35.0 <= grav_model.cost_savings_pct <= 45.0


def test_benchmark_cool_graviton_e2e():
    """Verify the benchmark script executes cleanly and returns report."""
    # Fast 2-iteration run
    report = run_benchmark(iterations=2, warmup=1)
    assert len(report.timings) == 4
    assert report.price_performance_improvement_pct > 0
    assert report.cost_savings_pct > 0

    # Ensure stages match required workload names
    stage_names = [t.stage_name for t in report.timings]
    assert "Illumination Flattening" in stage_names
    assert "Morphological Filtering" in stage_names
    assert "Contour Extraction" in stage_names
    assert "End-to-End Vision Pipeline" in stage_names
