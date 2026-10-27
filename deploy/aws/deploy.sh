#!/usr/bin/env bash
# ==============================================================================
# SketchForge - 1-Command AWS Deployment & Verification Script (Linux / macOS)
# OpenCV AI Competition 2026 Cloud Subsystem
# ==============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

echo "======================================================================"
echo "  SKETCHFORGE - 1-COMMAND AWS DEPLOYMENT & VERIFICATION (Bash)        "
echo "  OpenCV AI Competition 2026 Cloud Subsystem                          "
echo "======================================================================"

python3 deploy/aws/deploy.py "$@"
