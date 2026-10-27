"""Source adapters: normalise each external dataset into a common sample format.

Each adapter knows the peculiarities of one upstream source — how its files
are organised, what column names it uses, and how to decode its labels — and
produces :class:`RawSample` objects that the rest of the pipeline works with.

Current adapters
----------------
* ``SyntheticAdapter``      — reads the local ``datasets/synthetic/`` set produced
  by ``synthetic_generator.py``.  Always available.
* ``WebSightAdapter``       — reads the HuggingFace WebSight parquet shards
  (CC-BY-4.0) after they have been placed in ``datasets/raw/websight/``.
* ``SaltSketch2CodeAdapter``— reads the SALT-NLP Sketch2Code image/HTML pairs
  after they have been placed in ``datasets/raw/salt-sketch2code/``.
* ``ImageCLEFAdapter``      — reads the ImageCLEF DrawnUI 2021 wireframe set after
  manually placing gated data in ``datasets/raw/imageclef-drawnui-2021/``.
* ``RICOAdapter``           — reads the RICO Android UI dataset downloaded from
  HuggingFace (``creative-graphic-design/Rico``) into ``datasets/raw/rico/``.
  Run ``scripts/download_datasets.py --dataset rico`` to fetch it.
* ``MrtoyMobileUIAdapter``  — reads the ``mrtoy/mobile-ui-design`` HuggingFace
  dataset with ready-made bbox annotations into ``datasets/raw/mrtoy-mobile-ui/``.
  Run ``scripts/download_datasets.py --dataset mrtoy-mobile-ui`` to fetch it.
* ``RoboflowCOCOAdapter``   — reads any COCO-format export from Roboflow Universe.
  Place the unzipped export at ``datasets/raw/roboflow-wireframe/`` and run
  ``scripts/process_datasets.py --dataset roboflow-wireframe``.

Downloading
-----------
Only ``download_pilot()`` performs network IO — and only for public,
licence-clear datasets.  Gated sets must be placed manually.
``download_pilot()`` is intentionally minimal: it fetches the smallest useful
shard, stops, and records provenance.

Architecture constraint
-----------------------
Adapters are offline-first.  If the raw directory is absent, the adapter
returns an empty iterator.  It never crashes the application.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

# ---- Raw sample type -------------------------------------------------------


@dataclass
class RawSample:
    """Normalised single training example from any source."""
    sample_id: str
    source_dataset: str
    image_path: Path | None                   # None when only a URL is available
    image_bytes: bytes | None = None           # embedded image payload when not file-backed
    html: str | None = None                   # ground-truth HTML (if available)
    label: str | None = None                  # coarse UI component type (if labelled)
    bboxes: list[dict] = field(default_factory=list)  # [{label, x, y, w, h}]
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "sample_id": self.sample_id,
            "source_dataset": self.source_dataset,
            "image_path": str(self.image_path) if self.image_path else None,
            "has_image_bytes": self.image_bytes is not None,
            "has_html": self.html is not None,
            "label": self.label,
            "bbox_count": len(self.bboxes),
            "provenance": self.provenance,
        }


# ---- Base -------------------------------------------------------------------


class BaseAdapter:
    dataset_id: str = ""

    def samples(self) -> Iterator[RawSample]:
        """Yield :class:`RawSample` objects from the local raw directory."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """Return True when local raw data exists for this adapter."""
        return False


# ---- Synthetic (always available) ------------------------------------------


class SyntheticAdapter(BaseAdapter):
    """Reads the locally-generated synthetic sketch set."""

    dataset_id = "synthetic"

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        self._dir = Path(data_dir) if data_dir else repo_root() / "datasets" / "synthetic"

    def is_available(self) -> bool:
        return self._dir.is_dir() and any(self._dir.glob("*.png"))

    def samples(self) -> Iterator[RawSample]:
        manifest_path = self._dir / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                records = manifest.get("samples", []) if isinstance(manifest, dict) else manifest
                for rec in records:
                    img = self._dir / rec.get("image", rec.get("filename", ""))
                    annotation_path = self._dir / rec.get("labels", "")
                    bboxes = rec.get("annotations", [])
                    if not bboxes and annotation_path.is_file():
                        try:
                            truth = json.loads(annotation_path.read_text(encoding="utf-8"))
                            bboxes = [{"label": item.get("type", "unknown"),
                                       "x": item["bbox"][0], "y": item["bbox"][1],
                                       "w": item["bbox"][2], "h": item["bbox"][3]}
                                      for item in truth.get("components", [])]
                        except (json.JSONDecodeError, KeyError, TypeError):
                            bboxes = []
                    yield RawSample(
                        sample_id=rec.get("sample_id", img.stem),
                        source_dataset=self.dataset_id,
                        image_path=img if img.is_file() else None,
                        bboxes=bboxes,
                        provenance={"layout": rec.get("layout"), "condition": rec.get("condition")},
                    )
                return
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                log.warning("SyntheticAdapter: could not parse manifest: %s", exc)

        # Fallback: iterate PNG files directly
        for img in sorted(self._dir.glob("*.png")):
            yield RawSample(
                sample_id=img.stem,
                source_dataset=self.dataset_id,
                image_path=img,
            )


# ---- WebSight (CC-BY-4.0, public, parquet shards) --------------------------


class WebSightAdapter(BaseAdapter):
    """HuggingFaceM4/WebSight — HTML+screenshot pairs in parquet shards.

    Expected layout after manual or script placement::

        datasets/raw/websight-v02/ (or datasets/raw/websight/)
            data/train-00000-of-00071-*.parquet
            ...
    """

    dataset_id = "websight-v02"

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        if data_dir:
            self._dir = Path(data_dir)
        else:
            p1 = repo_root() / "datasets" / "raw" / "websight-v02"
            p2 = repo_root() / "datasets" / "raw" / "websight"
            self._dir = p1 if p1.is_dir() else p2

    def is_available(self) -> bool:
        return self._dir.is_dir() and any(self._dir.rglob("*.parquet"))

    def samples(self) -> Iterator[RawSample]:
        try:
            import pyarrow.parquet as pq  # type: ignore[import]
        except ImportError:
            log.warning("WebSightAdapter: pyarrow not installed; run: pip install pyarrow")
            return

        for parquet_file in sorted(self._dir.rglob("*.parquet")):
            try:
                row_offset = 0
                for batch in pq.ParquetFile(str(parquet_file)).iter_batches(batch_size=64):
                    data = batch.to_pydict()
                    html_col = data.get("text", data.get("html", []))
                    for i, html in enumerate(html_col):
                        image = data.get("image", [None] * len(html_col))[i]
                        image_bytes = image.get("bytes") if isinstance(image, dict) else None
                        if not image_bytes and isinstance(image, dict) and image.get("path"):
                            image_path = parquet_file.parent / image["path"]
                            image_bytes = image_path.read_bytes() if image_path.is_file() else None
                        yield RawSample(
                            sample_id=f"websight-{parquet_file.stem}-{row_offset+i:06d}",
                            source_dataset=self.dataset_id,
                            image_path=None,
                            image_bytes=image_bytes,
                            html=html,
                            provenance={"parquet": parquet_file.name, "row": row_offset+i},
                        )
                    row_offset += len(html_col)
            except Exception as exc:  # noqa: BLE001
                log.warning("WebSightAdapter: error reading %s: %s", parquet_file.name, exc)


# ---- SALT-NLP Sketch2Code --------------------------------------------------


class SaltSketch2CodeAdapter(BaseAdapter):
    """SALT-NLP/Sketch2Code hand-drawn sketch → HTML pairs.

    Expected layout::

        datasets/raw/salt-sketch2code/
            sketches/ (or images/)    *.png (sketch photos)
            webpages/ (or html/)      *.html, *.png (ground-truth web designs)
    """

    dataset_id = "salt-sketch2code"

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        self._dir = (
            Path(data_dir) if data_dir
            else repo_root() / "datasets" / "raw" / "salt-sketch2code"
        )

    def is_available(self) -> bool:
        img_dir = self._resolve_img_dir()
        return img_dir is not None and any(img_dir.rglob("*.png"))

    def _resolve_img_dir(self) -> Path | None:
        for candidate in ("sketches", "images", ""):
            d = self._dir / candidate if candidate else self._dir
            if d.is_dir() and any(d.rglob("*.png")):
                return d
        return None

    def _resolve_html_dir(self) -> Path:
        for candidate in ("webpages", "html", ""):
            d = self._dir / candidate if candidate else self._dir
            if d.is_dir() and any(d.glob("*.html")):
                return d
        return self._dir / "webpages"

    def samples(self) -> Iterator[RawSample]:
        img_dir = self._resolve_img_dir()
        if not img_dir:
            return
        html_dir = self._resolve_html_dir()

        for img_path in sorted(img_dir.rglob("*.png")):
            # Try exact stem match, then base webpage id (e.g. 10303_1 -> 10303)
            html_path = html_dir / (img_path.stem + ".html")
            if not html_path.is_file() and "_" in img_path.stem:
                base_id = img_path.stem.split("_")[0]
                html_path = html_dir / f"{base_id}.html"

            html = html_path.read_text(encoding="utf-8", errors="replace") if html_path.is_file() else None
            yield RawSample(
                sample_id=f"salt-{img_path.stem}",
                source_dataset=self.dataset_id,
                image_path=img_path,
                html=html,
                provenance={"has_html": html is not None, "source_stem": img_path.stem},
            )


# ---- WebCode2M -------------------------------------------------------------


class WebCode2MAdapter(BaseAdapter):
    """WebCode2M (xcodemind/webcode2m) — real-world webpage screenshots with HTML/CSS & bboxes.

    Expected layout::

        datasets/raw/webcode2m/
            data/*.parquet (or *.parquet)
    """

    dataset_id = "webcode2m"

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        self._dir = Path(data_dir) if data_dir else repo_root() / "datasets" / "raw" / "webcode2m"

    def is_available(self) -> bool:
        return self._dir.is_dir() and any(self._dir.rglob("*.parquet"))

    def samples(self) -> Iterator[RawSample]:
        try:
            import pyarrow.parquet as pq
        except ImportError:
            log.warning("WebCode2MAdapter: pyarrow not installed; run: pip install pyarrow")
            return

        for parquet_file in sorted(self._dir.rglob("*.parquet")):
            try:
                table = pq.read_table(str(parquet_file))
                df = table.to_pydict()
                text_col = df.get("text", [])
                n = len(text_col)
                for i in range(n):
                    html = text_col[i] if i < len(text_col) else None
                    sid = f"webcode2m-{parquet_file.stem}-{i:06d}"
                    bboxes = df.get("bbox", [[]])[i] if "bbox" in df and i < len(df["bbox"]) else []
                    yield RawSample(
                        sample_id=sid,
                        source_dataset=self.dataset_id,
                        image_path=None,
                        html=html,
                        bboxes=bboxes if isinstance(bboxes, list) else [],
                        provenance={"parquet": parquet_file.name, "row": i},
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("WebCode2MAdapter: error reading %s: %s", parquet_file.name, exc)


# ---- Teklia IAM-line -------------------------------------------------------


class TekliaIAMLineAdapter(BaseAdapter):
    """Teklia IAM-line handwriting OCR dataset.

    Expected layout::

        datasets/raw/teklia-iam-line/
            data/*.parquet (train.parquet, validation.parquet, test.parquet)
    """

    dataset_id = "teklia-iam-line"

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        self._dir = Path(data_dir) if data_dir else repo_root() / "datasets" / "raw" / "teklia-iam-line"

    def is_available(self) -> bool:
        return self._dir.is_dir() and any(self._dir.rglob("*.parquet"))

    def samples(self) -> Iterator[RawSample]:
        try:
            import pyarrow.parquet as pq
        except ImportError:
            log.warning("TekliaIAMLineAdapter: pyarrow not installed; run: pip install pyarrow")
            return

        for parquet_file in sorted(self._dir.rglob("*.parquet")):
            try:
                table = pq.read_table(str(parquet_file))
                df = table.to_pydict()
                text_col = df.get("text", [])
                for i, text in enumerate(text_col):
                    sid = f"iamline-{parquet_file.stem}-{i:06d}"
                    yield RawSample(
                        sample_id=sid,
                        source_dataset=self.dataset_id,
                        image_path=None,
                        label=str(text) if text is not None else None,
                        provenance={"split": parquet_file.stem, "row": i},
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("TekliaIAMLineAdapter: error reading %s: %s", parquet_file.name, exc)


# ---- Teklia IAM Forms (page-level) -----------------------------------------


class TekliaIAMFormsAdapter(BaseAdapter):
    """Teklia IAM forms-level handwriting dataset (Teklia/IAM).

    Provides full page/form handwriting samples for document layout, handwriting
    region detection, and multi-line transcription.

    Expected layout::

        datasets/raw/teklia-iam/
            data/*.parquet or images/
    """

    dataset_id = "teklia-iam"

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        self._dir = Path(data_dir) if data_dir else repo_root() / "datasets" / "raw" / "teklia-iam"

    def is_available(self) -> bool:
        return self._dir.is_dir() and (any(self._dir.rglob("*.parquet")) or any(self._dir.rglob("*.png")) or any(self._dir.rglob("*.jpg")))

    def samples(self) -> Iterator[RawSample]:
        # 1. Parquet format
        parquets = sorted(self._dir.rglob("*.parquet"))
        if parquets:
            try:
                import pyarrow.parquet as pq
                for parquet_file in parquets:
                    table = pq.read_table(str(parquet_file))
                    df = table.to_pydict()
                    text_col = df.get("text", df.get("transcription", []))
                    image_col = df.get("image", [])
                    for i in range(len(text_col)):
                        text = text_col[i] if i < len(text_col) else None
                        img_payload = image_col[i] if i < len(image_col) else None
                        yield RawSample(
                            sample_id=f"iamform-{parquet_file.stem}-{i:06d}",
                            source_dataset=self.dataset_id,
                            image_path=None,
                            image_bytes=_image_bytes(img_payload),
                            label=str(text) if text is not None else None,
                            provenance={"split": parquet_file.stem, "row": i, "level": "form"},
                        )
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("TekliaIAMFormsAdapter: error reading parquet: %s", exc)

        # 2. Image directory format fallback
        for img_path in sorted(self._dir.glob("*")):
            if img_path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                yield RawSample(
                    sample_id=f"iamform-{img_path.stem}",
                    source_dataset=self.dataset_id,
                    image_path=img_path,
                    provenance={"level": "form", "source_file": img_path.name},
                )


# ---- Sketch2Diagram Benchmark ----------------------------------------------


class Sketch2DiagramAdapter(BaseAdapter):
    """DiagramAgent/Sketch2Diagram-Benchmark hand-drawn diagram dataset.

    Expected layout::

        datasets/raw/sketch2diagram/
            Sketch2Diagram Benchmark.zip (or extracted files/folders)
    """

    dataset_id = "sketch2diagram"

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        self._dir = Path(data_dir) if data_dir else repo_root() / "datasets" / "raw" / "sketch2diagram"

    def is_available(self) -> bool:
        if not self._dir.is_dir():
            return False
        benchmark = next((p for p in self._dir.rglob("test_set_sketch_2_code.json")), None)
        if benchmark is not None:
            try:
                records = json.loads(benchmark.read_text(encoding="utf-8"))
                base = benchmark.parent
                return any(
                    (base / str(ref).removeprefix("./")).is_file()
                    and (base / str(ref).removeprefix("./")).stat().st_size > 0
                    for record in records
                    for ref in record.get("sketch_image", [])
                )
            except (OSError, json.JSONDecodeError, TypeError):
                return False
        return any(p.stat().st_size > 0 for p in self._dir.rglob("initial_image/*.png"))

    def samples(self) -> Iterator[RawSample]:
        benchmark = next(iter(self._dir.rglob("test_set_sketch_2_code.json")), None)
        if benchmark is None:
            return
        try:
            records = json.loads(benchmark.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Sketch2DiagramAdapter: cannot read benchmark records: %s", exc)
            return
        base = benchmark.parent
        for record in records:
            refs = record.get("sketch_image", [])
            if isinstance(refs, str):
                refs = [refs]
            img_path = next((base / str(ref).removeprefix("./") for ref in refs
                             if (base / str(ref).removeprefix("./")).is_file()
                             and (base / str(ref).removeprefix("./")).stat().st_size > 0), None)
            if img_path is None:
                continue
            prompt = "\n".join(str(m.get("content", "")) for m in record.get("messages", [])
                               if m.get("role") == "user")
            yield RawSample(
                sample_id=f"diagram-{record.get('id', img_path.stem)}",
                source_dataset=self.dataset_id,
                image_path=img_path,
                label=prompt or None,
                provenance={"benchmark_id": record.get("id"),
                            "code_image": record.get("code_image", [])},
            )


# ---- ImageCLEF DrawnUI 2021 ------------------------------------------------


class ImageCLEFAdapter(BaseAdapter):
    """ImageCLEF DrawnUI 2021 — gated dataset; must be placed manually.

    Expected layout::

        datasets/raw/imageclef-drawnui-2021/
            images/    *.jpg or *.png
            annotations/ *.xml (Pascal VOC bounding boxes, optional)
    """

    dataset_id = "imageclef-drawnui-2021"

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        self._dir = (
            Path(data_dir) if data_dir
            else repo_root() / "datasets" / "raw" / "imageclef-drawnui-2021"
        )

    def is_available(self) -> bool:
        img_dir = self._dir / "images"
        return img_dir.is_dir() and any(img_dir.glob("*.*"))

    def samples(self) -> Iterator[RawSample]:
        img_dir = self._dir / "images"
        ann_dir = self._dir / "annotations"
        if not img_dir.is_dir():
            return
        for img_path in sorted(img_dir.glob("*")):
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            bboxes = _parse_voc_xml(ann_dir / (img_path.stem + ".xml"))
            yield RawSample(
                sample_id=f"imageclef-{img_path.stem}",
                source_dataset=self.dataset_id,
                image_path=img_path,
                bboxes=bboxes,
                provenance={"has_annotations": bool(bboxes)},
            )


# ---- RICO Android UI Dataset -----------------------------------------------


class RICOAdapter(BaseAdapter):
    """RICO Android UI dataset — 66k screenshots with component bounding boxes.

    Reads data pre-downloaded from HuggingFace (``creative-graphic-design/Rico``)
    or from the original interaction-mining.org release.

    Expected layout after running ``scripts/download_datasets.py --dataset rico``::

        datasets/raw/rico/
            data.json          (view hierarchy JSON, one per screen)
            combined/          (screenshot PNGs keyed by screen id)
                0.jpg, 1.jpg, ...
    """

    dataset_id = "rico"

    # Map Rico semantic class names to SketchForge component type strings.
    _TYPE_MAP: dict[str, str] = {
        "Button": "button",
        "Text Button": "button",
        "Image": "image",
        "Text": "text",
        "Input": "input",
        "Icon": "icon",
        "List Item": "list_item",
        "Toolbar": "toolbar",
        "Web View": "container",
        "Background Image": "image",
        "Drawer": "container",
        "Advertisement": "image",
        "Pager Indicator": "indicator",
        "Modal": "modal",
        "Slider": "slider",
        "Radio Button": "radio",
        "Checkbox": "checkbox",
        "Multi-Tab": "tabs",
        "Card": "card",
        "Number Stepper": "stepper",
        "Toggle": "toggle",
        "Date Picker": "picker",
        "Map View": "map",
        "On/Off Switch": "toggle",
        "Video": "image",
        "Bottom Navigation": "navbar",
    }

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        self._dir = Path(data_dir) if data_dir else repo_root() / "datasets" / "raw" / "rico"

    def is_available(self) -> bool:
        if (self._dir / "dataset").is_dir():
            return True
        # Accept either JSONL semantics file or combined/ image directory
        has_images = (self._dir / "combined").is_dir() and any(
            (self._dir / "combined").glob("*.jpg")
        )
        has_semantic = any(self._dir.glob("*.json")) or any(self._dir.glob("*.jsonl"))
        return self._dir.is_dir() and (has_images or has_semantic)

    def samples(self) -> Iterator[RawSample]:
        img_dir = self._dir / "combined"
        saved_dataset = self._dir / "dataset"
        if saved_dataset.is_dir():
            try:
                from datasets import load_from_disk  # type: ignore[import]
                dataset = load_from_disk(str(saved_dataset))
            except ImportError:
                log.warning("RICOAdapter: install the data extra: pip install -e '.[data]'")
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("RICOAdapter: cannot open saved Hugging Face dataset: %s", exc)
                return
            for i, row in enumerate(dataset):
                image = row.get("image", row.get("screenshot"))
                image_bytes = _image_bytes(image)
                if image_bytes is None:
                    continue
                width = int(row.get("width", 0) or 0)
                height = int(row.get("height", 0) or 0)
                try:
                    from PIL import Image
                    import io
                    with Image.open(io.BytesIO(image_bytes)) as decoded:
                        width, height = decoded.size
                except Exception:  # noqa: BLE001
                    pass
                boxes = _rico_row_boxes(row, width, height)
                yield RawSample(
                    sample_id=f"rico-{row.get('screen_id', row.get('id', i))}",
                    source_dataset=self.dataset_id,
                    image_path=None,
                    image_bytes=image_bytes,
                    bboxes=boxes,
                    provenance={"row": i, "has_annotations": bool(boxes), "format": "huggingface"},
                )
            return

        # Find annotation source: prefer semantic_annotations.json
        ann_file = self._dir / "semantic_annotations.json"
        if not ann_file.exists():
            candidates = list(self._dir.glob("*.json")) + list(self._dir.glob("*.jsonl"))
            ann_file = candidates[0] if candidates else None

        annotations: dict = {}
        if ann_file and ann_file.exists():
            try:
                raw = ann_file.read_text(encoding="utf-8")
                # Support both JSON array and JSONL
                if raw.strip().startswith("["):
                    records = json.loads(raw)
                    for rec in records:
                        sid = str(rec.get("screen_id", rec.get("id", "")))
                        annotations[sid] = rec
                else:
                    for line in raw.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            sid = str(rec.get("screen_id", rec.get("id", "")))
                            annotations[sid] = rec
                        except json.JSONDecodeError:
                            pass
            except Exception as exc:  # noqa: BLE001
                log.warning("RICOAdapter: could not load annotations: %s", exc)

        if not img_dir.is_dir():
            return
        for img_path in sorted(img_dir.glob("*.jpg")):
            sid = img_path.stem
            bboxes = []
            ann = annotations.get(sid, {})
            for comp in ann.get("components", []):
                label = self._TYPE_MAP.get(comp.get("componentLabel", ""), "unknown")
                bounds = comp.get("bounds", [])
                if len(bounds) == 4:
                    x1, y1, x2, y2 = bounds
                    bboxes.append({
                        "label": label,
                        "x": float(x1), "y": float(y1),
                        "w": float(x2 - x1), "h": float(y2 - y1),
                    })
            yield RawSample(
                sample_id=f"rico-{sid}",
                source_dataset=self.dataset_id,
                image_path=img_path,
                bboxes=bboxes,
                provenance={"screen_id": sid, "has_annotations": bool(bboxes)},
            )


# ---- mrtoy/mobile-ui-design (HuggingFace) ----------------------------------


class MrtoyMobileUIAdapter(BaseAdapter):
    """mrtoy/mobile-ui-design — HuggingFace dataset with ready bbox annotations.

    Run ``scripts/download_datasets.py --dataset mrtoy-mobile-ui`` to fetch.
    Alternatively, set data_dir to a pre-downloaded parquet/arrow cache directory.

    Expected layout::

        datasets/raw/mrtoy-mobile-ui/
            data-*.arrow  (or *.parquet from HuggingFace cache)
    """

    dataset_id = "mrtoy-mobile-ui"

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        self._dir = (
            Path(data_dir) if data_dir
            else repo_root() / "datasets" / "raw" / "mrtoy-mobile-ui"
        )

    def is_available(self) -> bool:
        if not self._dir.is_dir():
            return False
        return (
            any(self._dir.rglob("*.arrow"))
            or any(self._dir.rglob("*.parquet"))
            or any(self._dir.rglob("*.png"))
            or any(self._dir.rglob("*.jpg"))
        )

    def samples(self) -> Iterator[RawSample]:
        # Try loading via HuggingFace datasets library from local cache
        try:
            from datasets import load_dataset, load_from_disk  # type: ignore[import]
            # If saved with save_to_disk()
            disk_path = self._dir / "dataset"
            if disk_path.exists():
                ds = load_from_disk(str(disk_path))
            else:
                ds = load_dataset("mrtoy/mobile-ui-design", cache_dir=str(self._dir),
                                  split="train")
            for i, row in enumerate(ds):
                img = row.get("image")
                # Current mrtoy/mobile-ui-design stores its annotations in an
                # `objects` struct: {bbox: [...], category: [...], ...}.
                # Older exports used top-level bbox/category columns.
                objects = row.get("objects", {})
                if not isinstance(objects, dict):
                    objects = {}
                mrtoy_xyxy = "bbox" in objects
                bboxes_raw = row.get("bbox", row.get("bboxes", objects.get("bbox", [])))
                categories = row.get("category", row.get("categories", objects.get("category", [])))
                bboxes = []
                # bbox format varies — normalize to {label, x, y, w, h}
                for j, bbox in enumerate(bboxes_raw if isinstance(bboxes_raw, list) else []):
                    cat = categories[j] if isinstance(categories, list) and j < len(categories) else "unknown"
                    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                        x, y, w, h = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                        # MrToy uses [x1, y1, x2, y2]; older exports use [x,y,w,h].
                        if mrtoy_xyxy:
                            w, h = w - x, h - y
                        label = {"rectangle": "container", "group": "container"}.get(
                            str(cat).lower(), str(cat).lower())
                        bboxes.append({"label": label, "x": x, "y": y, "w": w, "h": h})
                    elif isinstance(bbox, dict):
                        bboxes.append({
                            "label": str(cat),
                            "x": float(bbox.get("x", bbox.get("xmin", 0))),
                            "y": float(bbox.get("y", bbox.get("ymin", 0))),
                            "w": float(bbox.get("w", bbox.get("width", 0))),
                            "h": float(bbox.get("h", bbox.get("height", 0))),
                        })
                # Convert PIL image to bytes if needed
                image_bytes = None
                if img is not None and hasattr(img, "tobytes"):
                    import io
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    image_bytes = buf.getvalue()
                yield RawSample(
                    sample_id=f"mrtoy-{i:07d}",
                    source_dataset=self.dataset_id,
                    image_path=None,
                    image_bytes=image_bytes,
                    bboxes=bboxes,
                    provenance={"row": i, "source": "mrtoy/mobile-ui-design"},
                )
        except ImportError:
            log.warning("MrtoyMobileUIAdapter: huggingface datasets not installed. "
                        "Run: pip install datasets")
        except Exception as exc:  # noqa: BLE001
            log.warning("MrtoyMobileUIAdapter: error loading dataset: %s", exc)


# ---- Roboflow COCO Export --------------------------------------------------


class RoboflowCOCOAdapter(BaseAdapter):
    """Reads any COCO-format dataset exported from Roboflow Universe.

    Download any wireframe/UI dataset from https://universe.roboflow.com,
    choose "COCO" export format, and unzip to ``datasets/raw/roboflow-wireframe/``.

    Expected layout::

        datasets/raw/roboflow-wireframe/
            train/
                _annotations.coco.json
                image1.jpg, image2.jpg, ...
            valid/
                _annotations.coco.json
                ...
            test/          (optional)
                _annotations.coco.json
                ...
    """

    dataset_id = "roboflow-wireframe"

    def __init__(self, data_dir: Path | str | None = None) -> None:
        from sketchforge.utilities.paths import repo_root
        self._dir = (
            Path(data_dir) if data_dir
            else repo_root() / "datasets" / "raw" / "roboflow-wireframe"
        )

    def is_available(self) -> bool:
        if not self._dir.is_dir():
            return False
        return any(self._dir.rglob("_annotations.coco.json")) or any(
            self._dir.rglob("annotations.json")
        )

    def samples(self) -> Iterator[RawSample]:
        # Walk all splits (train / valid / test)
        for ann_path in sorted(self._dir.rglob("*annotations*.json")):
            split_dir = ann_path.parent
            try:
                coco = json.loads(ann_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                log.warning("RoboflowCOCOAdapter: cannot read %s: %s", ann_path, exc)
                continue

            # Build category id → name map
            categories = {c["id"]: c["name"] for c in coco.get("categories", [])}
            # Build image id → info map
            images = {img["id"]: img for img in coco.get("images", [])}
            # Group annotations by image id
            ann_by_image: dict[int, list] = {}
            for ann in coco.get("annotations", []):
                ann_by_image.setdefault(ann["image_id"], []).append(ann)

            for img_id, img_info in images.items():
                img_path = split_dir / img_info["file_name"]
                if not img_path.is_file():
                    # Try without subdirectory prefix
                    img_path = split_dir / Path(img_info["file_name"]).name
                if not img_path.is_file():
                    continue

                bboxes = []
                for ann in ann_by_image.get(img_id, []):
                    cat_name = categories.get(ann.get("category_id", -1), "unknown")
                    bbox = ann.get("bbox", [])
                    if len(bbox) == 4:
                        # COCO format: [x, y, width, height]
                        bboxes.append({
                            "label": cat_name,
                            "x": float(bbox[0]), "y": float(bbox[1]),
                            "w": float(bbox[2]), "h": float(bbox[3]),
                        })

                yield RawSample(
                    sample_id=f"roboflow-{img_path.stem}",
                    source_dataset=self.dataset_id,
                    image_path=img_path,
                    bboxes=bboxes,
                    provenance={
                        "split": split_dir.name,
                        "coco_image_id": img_id,
                        "has_annotations": bool(bboxes),
                    },
                )


# ---------------------------------------------------------------------------
# Pilot downloader (public, licence-clear datasets only)
# ---------------------------------------------------------------------------


def download_pilot(
    dataset_id: str,
    *,
    target_bytes: int = 100 * 1024 * 1024,   # 100 MB default pilot
    force: bool = False,
) -> dict:
    """Download the smallest useful shard of a public dataset.

    This function is the **only** place in the pipeline that initiates a
    network request for external data.  It:

    1. Checks that the dataset is in the manifest and access is ``"public"``.
    2. Refuses gated or rights-unclear datasets with a clear error message.
    3. Downloads exactly one shard / part up to ``target_bytes``.
    4. Records a provenance JSON alongside the downloaded file.

    Returns a summary dict; raises ``ValueError`` on bad input or policy
    violation; raises ``OSError`` / ``requests.RequestException`` on network
    failure.

    Currently only ``websight`` can be downloaded automatically (one parquet
    shard via direct HTTPS).  Add new public datasets here as rights are
    confirmed.
    """
    from sketchforge.utilities.paths import repo_root

    DOWNLOADABLE: dict[str, str] = {
        # dataset_id → direct URL for the first shard / zip file
        "websight": (
            "https://huggingface.co/datasets/HuggingFaceM4/WebSight"
            "/resolve/10d8285c49c88608dcf82f3f76ee58377a3a1216"
            "/data/train-00000-of-00060.parquet"
        ),
        # SALT-NLP Sketch2Code — first parquet shard from HuggingFace
        "salt-sketch2code": (
            "https://huggingface.co/datasets/SALT-NLP/Sketch2Code"
            "/resolve/main/data/train-00000-of-00001.parquet"
        ),
    }

    if dataset_id not in DOWNLOADABLE:
        raise ValueError(
            f"Dataset '{dataset_id}' is not available for automatic download.  "
            "Either it is gated (place files manually) or it has not been cleared "
            "for automatic retrieval.  Check docs/DATASET_AUDIT.md."
        )

    url = DOWNLOADABLE[dataset_id]
    dest_dir = repo_root() / "datasets" / "raw" / dataset_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / "data" / Path(url.split("/")[-1])
    dest_file.parent.mkdir(parents=True, exist_ok=True)

    if dest_file.exists() and not force:
        return {
            "dataset_id": dataset_id,
            "status": "already_present",
            "path": str(dest_file),
            "bytes": dest_file.stat().st_size,
        }

    try:
        import requests  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("Install requests: pip install requests") from exc

    log.info("Downloading pilot shard for %s from %s", dataset_id, url)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        content_length = int(response.headers.get("Content-Length", 0))
        if content_length > target_bytes * 2:
            raise ValueError(
                f"Remote file is {content_length / 1e6:.0f} MB which exceeds the "
                f"{target_bytes * 2 / 1e6:.0f} MB safety limit.  "
                "Increase target_bytes explicitly if intentional."
            )
        downloaded = 0
        hasher = hashlib.sha256()
        with dest_file.open("wb") as fout:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    fout.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if downloaded > target_bytes:
                        log.warning(
                            "Stopped after %.1f MB (pilot limit)", downloaded / 1e6
                        )
                        break

    sha256 = hasher.hexdigest()
    provenance = {
        "dataset_id": dataset_id,
        "source_url": url,
        "sha256": sha256,
        "bytes": downloaded,
        "pilot": True,
    }
    (dest_file.with_suffix(".provenance.json")).write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )
    log.info("Pilot download complete: %s (%.1f MB)", dest_file.name, downloaded / 1e6)
    return {**provenance, "path": str(dest_file)}


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[BaseAdapter]] = {
    "synthetic": SyntheticAdapter,
    "websight": WebSightAdapter,
    "websight-v02": WebSightAdapter,
    "salt-sketch2code": SaltSketch2CodeAdapter,
    "webcode2m": WebCode2MAdapter,
    "teklia-iam-line": TekliaIAMLineAdapter,
    "teklia-iam": TekliaIAMFormsAdapter,
    "sketch2diagram": Sketch2DiagramAdapter,
    "imageclef-drawnui-2021": ImageCLEFAdapter,
    # Free / open datasets with real bbox annotations:
    "rico": RICOAdapter,
    "mrtoy-mobile-ui": MrtoyMobileUIAdapter,
    "roboflow-wireframe": RoboflowCOCOAdapter,
}


def get_adapter(dataset_id: str, data_dir: Path | str | None = None) -> BaseAdapter:
    """Return the adapter for *dataset_id*, raising ``KeyError`` if unknown."""
    cls = _ADAPTERS[dataset_id]
    return cls(data_dir=data_dir) if data_dir else cls()


def available_adapters() -> list[str]:
    """Return dataset IDs for which local data currently exists."""
    return [did for did, cls in _ADAPTERS.items() if cls().is_available()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _image_bytes(image: object) -> bytes | None:
    """Encode a Hugging Face image feature or image payload as PNG bytes."""
    if isinstance(image, bytes):
        return image
    if isinstance(image, dict):
        payload = image.get("bytes")
        if payload:
            return payload
        image_path = image.get("path")
        if image_path and Path(str(image_path)).is_file():
            return Path(str(image_path)).read_bytes()
        return None
    if image is not None and hasattr(image, "save"):
        import io
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    return None


def _rico_row_boxes(row: dict, width: int, height: int) -> list[dict]:
    """Normalize common RICO/FiftyOne detection records to pixel xywh boxes."""
    detections = row.get("detections", row.get("components", []))
    if isinstance(detections, dict):
        detections = detections.get("detections", detections.get("objects", []))
    if not isinstance(detections, list):
        return []
    result = []
    for item in detections:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", item.get("component_label", item.get("componentLabel", "unknown"))))
        label = RICOAdapter._TYPE_MAP.get(label, RICOAdapter._TYPE_MAP.get(label.title(), label.lower()))
        bbox = item.get("bounding_box", item.get("bbox"))
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            bounds = item.get("bounds")
            if not isinstance(bounds, (list, tuple)) or len(bounds) < 4:
                continue
            x1, y1, x2, y2 = map(float, bounds[:4])
            x, y, w, h = x1, y1, x2 - x1, y2 - y1
        else:
            x, y, w, h = map(float, bbox[:4])
            if max(abs(x), abs(y), abs(w), abs(h)) <= 1.0 and width > 0 and height > 0:
                x, w = x * width, w * width
                y, h = y * height, h * height
        if w > 0 and h > 0:
            result.append({"label": label, "x": x, "y": y, "w": w, "h": h})
    return result

def _parse_voc_xml(path: Path) -> list[dict]:
    """Parse a Pascal VOC XML annotation file into a list of bbox dicts."""
    if not path.is_file():
        return []
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(str(path))
        bboxes = []
        for obj in tree.findall("object"):
            name_el = obj.find("name")
            bndbox = obj.find("bndbox")
            if name_el is None or bndbox is None:
                continue
            xmin = float(bndbox.findtext("xmin", "0"))
            ymin = float(bndbox.findtext("ymin", "0"))
            xmax = float(bndbox.findtext("xmax", "0"))
            ymax = float(bndbox.findtext("ymax", "0"))
            bboxes.append({
                "label": name_el.text or "unknown",
                "x": xmin,
                "y": ymin,
                "w": xmax - xmin,
                "h": ymax - ymin,
            })
        return bboxes
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not parse VOC XML %s: %s", path.name, exc)
        return []
