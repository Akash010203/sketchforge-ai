"""Download approved public datasets with strict size caps and safe storage limits.

Supports:
  1. salt-sketch2code    (~80 MB zip, hand-drawn sketch to HTML/webpage)
  2. teklia-iam-line      (~253 MB parquet, handwriting OCR)
  3. sketch2diagram       (~125 MB zip, hand-drawn diagrams and symbols)
  4. websight-v02         (capped at 20 GB, webpage screenshots + HTML/Tailwind)
  5. webcode2m            (capped at 20 GB, real-world webpages with layout/DOM)

Usage
-----
    # Download small datasets (all of them in < 5 minutes):
    python scripts/download_datasets.py --dataset salt-sketch2code
    python scripts/download_datasets.py --dataset teklia-iam-line
    python scripts/download_datasets.py --dataset sketch2diagram

    # Download large multimodal datasets with 20 GB cap:
    python scripts/download_datasets.py --dataset websight-v02 --max-gb 20
    python scripts/download_datasets.py --dataset webcode2m --max-gb 20

    # Or download all approved small datasets in one go:
    python scripts/download_datasets.py --small-all
"""

from __future__ import annotations

import argparse
import logging
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def download_salt_sketch2code(dest_dir: Path) -> int:
    """Download SALT-NLP/Sketch2Code (~80 MB zip) and extract it."""
    from huggingface_hub import hf_hub_download

    dest_dir.mkdir(parents=True, exist_ok=True)
    log.info("Downloading SALT-NLP/Sketch2Code (sketch2code_dataset_v1.zip, ~80 MB)...")
    archive_path = hf_hub_download(
        repo_id="SALT-NLP/Sketch2Code",
        filename="sketch2code_dataset_v1.zip",
        repo_type="dataset",
        local_dir=str(dest_dir),
    )
    log.info("Downloaded to %s. Extracting...", archive_path)
    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(dest_dir)
    log.info("Extraction complete in %s", dest_dir)
    return 1


def download_teklia_iam_line(dest_dir: Path) -> int:
    """Download Teklia/IAM-line (~253 MB parquet splits)."""
    from huggingface_hub import hf_hub_download

    dest_data_dir = dest_dir / "data"
    dest_data_dir.mkdir(parents=True, exist_ok=True)
    files = ["data/train.parquet", "data/validation.parquet", "data/test.parquet"]
    log.info("Downloading Teklia/IAM-line (3 parquet splits, ~253 MB total)...")
    for fname in files:
        log.info("  Downloading %s...", fname)
        hf_hub_download(
            repo_id="Teklia/IAM-line",
            filename=fname,
            repo_type="dataset",
            local_dir=str(dest_dir),
        )
    log.info("Teklia/IAM-line download complete in %s", dest_dir)
    return len(files)


def download_teklia_iam_forms(dest_dir: Path) -> int:
    """Download Teklia/IAM (forms level handwriting)."""
    from huggingface_hub import hf_hub_download

    dest_data_dir = dest_dir / "data"
    dest_data_dir.mkdir(parents=True, exist_ok=True)
    files = ["data/train.parquet", "data/validation.parquet", "data/test.parquet"]
    log.info("Downloading Teklia/IAM forms (parquet splits)...")
    count = 0
    for fname in files:
        try:
            hf_hub_download(
                repo_id="Teklia/IAM",
                filename=fname,
                repo_type="dataset",
                local_dir=str(dest_dir),
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not download %s: %s", fname, exc)
    log.info("Teklia/IAM forms download complete in %s", dest_dir)
    return count


def download_sketch2diagram(dest_dir: Path) -> int:
    """Download DiagramAgent/Sketch2Diagram-Benchmark (~125 MB zip) and extract."""
    from huggingface_hub import hf_hub_download

    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = "Sketch2Diagram Benchmark.zip"
    log.info("Downloading Sketch2Diagram Benchmark (~125 MB)...")
    archive_path = hf_hub_download(
        repo_id="DiagramAgent/Sketch2Diagram-Benchmark",
        filename=filename,
        repo_type="dataset",
        local_dir=str(dest_dir),
    )
    log.info("Downloaded to %s. Extracting...", archive_path)
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
    except Exception as exc:
        log.warning("Could not auto-extract zip (%s); archive is preserved at %s", exc, archive_path)
    log.info("Sketch2Diagram download complete in %s", dest_dir)
    return 1


def download_capped_shards(
    repo_id: str,
    dest_dir: Path,
    path_in_repo: str,
    max_bytes: int,
) -> int:
    """Download parquet shards up to a strict byte limit."""
    from huggingface_hub import HfApi, hf_hub_download

    dest_dir.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    log.info("Querying file list for %s in '%s'...", repo_id, path_in_repo)
    all_files = list(api.list_repo_tree(repo_id, repo_type="dataset", path_in_repo=path_in_repo))
    parquet_files = [f for f in all_files if getattr(f, "path", "").endswith(".parquet")]
    parquet_files.sort(key=lambda x: getattr(x, "path", ""))

    log.info(
        "Found %d parquet shards in %s. Downloading up to %.2f GB cap...",
        len(parquet_files),
        repo_id,
        max_bytes / (1024**3),
    )

    downloaded_bytes = 0
    downloaded_count = 0

    for item in parquet_files:
        file_path = item.path
        file_size = getattr(item, "size", 0)
        if downloaded_bytes + file_size > max_bytes and downloaded_count > 0:
            log.info(
                "Reached size cap (%.2f GB downloaded). Stopping shard retrieval.",
                downloaded_bytes / (1024**3),
            )
            break

        log.info(
            "[%d] Downloading %s (%.1f MB)...",
            downloaded_count + 1,
            file_path,
            file_size / (1024 * 1024),
        )
        hf_hub_download(
            repo_id=repo_id,
            filename=file_path,
            repo_type="dataset",
            local_dir=str(dest_dir),
        )
        downloaded_bytes += file_size
        downloaded_count += 1

    log.info(
        "Finished downloading %d shards (%.2f GB) to %s",
        downloaded_count,
        downloaded_bytes / (1024**3),
        dest_dir,
    )
    return downloaded_count


def download_commitpackft(dest_dir: Path, languages: list[str] | None = None) -> int:
    """Download bigcode/commitpackft for relevant languages (default: python, html, javascript, typescript)."""
    from huggingface_hub import HfApi, hf_hub_download

    langs = languages or ["python", "html", "javascript", "typescript"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    log.info("Downloading bigcode/commitpackft for languages: %s", langs)
    count = 0
    for lang in langs:
        path_in_repo = f"data/{lang}"
        files = list(api.list_repo_tree("bigcode/commitpackft", repo_type="dataset", path_in_repo=path_in_repo))
        for f in files:
            p = getattr(f, "path", "")
            if p.endswith(".parquet") or p.endswith(".jsonl"):
                sz = getattr(f, "size", 0) / (1024 * 1024)
                log.info("  Downloading %s (%.1f MB)...", p, sz)
                hf_hub_download(
                    repo_id="bigcode/commitpackft",
                    filename=p,
                    repo_type="dataset",
                    local_dir=str(dest_dir),
                )
                count += 1
    log.info("CommitPackFT download complete (%d files) in %s", count, dest_dir)
    return count


def download_codesearchnet(dest_dir: Path) -> int:
    """Clone CodeSearchNet repository and download python & javascript pairs."""
    import subprocess

    dest_dir.mkdir(parents=True, exist_ok=True)
    log.info("Cloning github/CodeSearchNet repository into %s...", dest_dir / "repo")
    repo_dest = dest_dir / "repo"
    if not repo_dest.is_dir():
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/github/CodeSearchNet.git", str(repo_dest)],
            check=True,
        )
        log.info("CodeSearchNet repo cloned.")
    else:
        log.info("CodeSearchNet repo already present at %s", repo_dest)
    return 1


def download_the_stack_dedup(
    dest_dir: Path,
    languages: list[str] | None = None,
    max_bytes: int = 20 * 1024 * 1024 * 1024,
    token: str | None = None,
) -> int:
    """Download specific languages from bigcode/the-stack-dedup up to a strict byte limit (Gated: requires HF login)."""
    import os
    from huggingface_hub import HfApi, get_token, hf_hub_download

    auth_token = token or os.environ.get("HF_TOKEN") or get_token()
    if not auth_token:
        log.error(
            "bigcode/the-stack-dedup is a GATED dataset and requires authentication.\n"
            "  1. Accept terms at: https://huggingface.co/datasets/bigcode/the-stack-dedup\n"
            "  2. Create a token at: https://huggingface.co/settings/tokens\n"
            "  3. In PowerShell run: huggingface-cli login (or set $env:HF_TOKEN='hf_...')"
        )
        return 0

    langs = languages or ["html", "css", "javascript", "typescript", "python"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    api = HfApi(token=auth_token)

    log.info("Downloading bigcode/the-stack-dedup up to %.2f GB cap for languages: %s", max_bytes / (1024**3), langs)

    downloaded_bytes = 0
    downloaded_count = 0

    for lang in langs:
        if downloaded_bytes >= max_bytes:
            break
        path_in_repo = f"data/{lang}"
        try:
            files = list(api.list_repo_tree("bigcode/the-stack-dedup", repo_type="dataset", path_in_repo=path_in_repo))
        except Exception as exc:
            log.error("Could not access bigcode/the-stack-dedup for %s: %s", lang, exc)
            continue

        parquet_files = [f for f in files if getattr(f, "path", "").endswith(".parquet")]
        parquet_files.sort(key=lambda x: getattr(x, "path", ""))

        for f in parquet_files:
            file_path = getattr(f, "path", "")
            file_size = getattr(f, "size", 0)
            if downloaded_bytes + file_size > max_bytes and downloaded_count > 0:
                log.info("Reached %.2f GB cap. Stopping download.", downloaded_bytes / (1024**3))
                return downloaded_count

            log.info(
                "[%d] Downloading %s (%.1f MB, total: %.2f / %.2f GB)...",
                downloaded_count + 1,
                file_path,
                file_size / (1024 * 1024),
                (downloaded_bytes + file_size) / (1024**3),
                max_bytes / (1024**3),
            )
            hf_hub_download(
                repo_id="bigcode/the-stack-dedup",
                filename=file_path,
                repo_type="dataset",
                local_dir=str(dest_dir),
                token=auth_token,
            )
            downloaded_bytes += file_size
            downloaded_count += 1

    log.info("the-stack-dedup download complete: %d shards (%.2f GB) in %s", downloaded_count, downloaded_bytes / (1024**3), dest_dir)
    return downloaded_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dataset",
        choices=[
            "salt-sketch2code",
            "websight-v01",
            "websight-v02",
            "websight",
            "webcode2m",
            "teklia-iam-line",
            "teklia-iam",
            "sketch2diagram",
            "commitpackft",
            "the-stack-dedup",
            "codesearchnet",
        ],
        help="Dataset identifier to download",
    )
    parser.add_argument(
        "--small-all",
        action="store_true",
        help="Download all 3 small auxiliary datasets (salt-sketch2code, teklia-iam-line, sketch2diagram, ~450 MB total)",
    )
    parser.add_argument(
        "--max-gb",
        type=float,
        default=20.0,
        help="Maximum download cap in GB for large datasets (default: 20 GB)",
    )
    args = parser.parse_args()

    raw_dir = ROOT / "datasets" / "raw"
    max_bytes = int(args.max_gb * 1024**3)

    if args.small_all:
        log.info("--- Downloading SALT-NLP Sketch2Code ---")
        download_salt_sketch2code(raw_dir / "salt-sketch2code")
        log.info("--- Downloading Teklia IAM-line ---")
        download_teklia_iam_line(raw_dir / "teklia-iam-line")
        log.info("--- Downloading Sketch2Diagram Benchmark ---")
        download_sketch2diagram(raw_dir / "sketch2diagram")
        log.info("All small datasets downloaded successfully.")
        return 0

    if not args.dataset:
        parser.print_help()
        return 1

    ds = args.dataset
    if ds in ("websight", "websight-v02"):
        download_capped_shards(
            repo_id="HuggingFaceM4/WebSight",
            dest_dir=raw_dir / "websight-v02",
            path_in_repo="data",
            max_bytes=max_bytes,
        )
    elif ds == "websight-v01":
        download_capped_shards(
            repo_id="HuggingFaceM4/WebSight",
            dest_dir=raw_dir / "websight-v01",
            path_in_repo="data",
            max_bytes=max_bytes,
        )
    elif ds == "webcode2m":
        download_capped_shards(
            repo_id="xcodemind/webcode2m",
            dest_dir=raw_dir / "webcode2m",
            path_in_repo="data",
            max_bytes=max_bytes,
        )
    elif ds == "salt-sketch2code":
        download_salt_sketch2code(raw_dir / "salt-sketch2code")
    elif ds == "teklia-iam-line":
        download_teklia_iam_line(raw_dir / "teklia-iam-line")
    elif ds == "teklia-iam":
        download_teklia_iam_forms(raw_dir / "teklia-iam")
    elif ds == "sketch2diagram":
        download_sketch2diagram(raw_dir / "sketch2diagram")
    elif ds == "commitpackft":
        download_commitpackft(raw_dir / "commitpackft")
    elif ds == "codesearchnet":
        download_codesearchnet(raw_dir / "codesearchnet")
    elif ds == "the-stack-dedup":
        download_the_stack_dedup(raw_dir / "the-stack-dedup", max_bytes=max_bytes)

    log.info("Done. Check with: python scripts/validate_manifest.py or launch the GUI Dataset Panel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
