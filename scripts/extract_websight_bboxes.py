"""Extract approximate component boxes from processed WebSight HTML.

Requires the optional Playwright browser extra and its Chromium runtime. HTML is
rendered with page JavaScript disabled and external requests blocked.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_EXTRACT = r"""() => {
  const rx = /header|navbar|navigation|footer|sidebar|button|input|search|card|image|hero|title|heading|text|content|menu|form|modal|dialog/i;
  const selector = 'header,nav,main,footer,aside,section,article,button,input,textarea,select,img,a,form,[role],div';
  const nodes = [...document.querySelectorAll(selector)];
  const boxes = [];
  const seen = new Set();
  for (const el of nodes) {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const x = Math.max(0, r.left + scrollX), y = Math.max(0, r.top + scrollY);
    const right = Math.min(document.documentElement.scrollWidth, r.right + scrollX);
    const bottom = Math.min(document.documentElement.scrollHeight, r.bottom + scrollY);
    const w = right - x, h = bottom - y;
    if (w < 12 || h < 10 || style.display === 'none' || style.visibility === 'hidden') continue;
    const area = w * h / (innerWidth * innerHeight);
    if (area < 0.001 || area > 0.92) continue;
    const tag = el.tagName.toLowerCase();
    const hint = `${tag} ${el.getAttribute('role') || ''} ${el.id || ''} ${el.className || ''}`;
    let label = ({header:'header', nav:'sidebar', footer:'footer', aside:'sidebar', button:'button', input:'input', textarea:'input', select:'input', img:'image', a:'button', form:'container', main:'container', section:'container', article:'card'})[tag];
    if (!label && rx.test(hint)) {
      const s = hint.toLowerCase();
      label = /button|menu-item|nav-link/.test(s) ? 'button' : /input|search/.test(s) ? 'input' : /image|img|hero/.test(s) ? 'image' : /heading|title/.test(s) ? 'heading' : /text/.test(s) ? 'text' : /card/.test(s) ? 'card' : /nav|menu/.test(s) ? 'sidebar' : 'container';
    }
    if (!label) continue;
    const key = [Math.round(x),Math.round(y),Math.round(w),Math.round(h),label].join(':');
    if (seen.has(key)) continue;
    seen.add(key);
    boxes.push({label, x, y, w, h});
  }
  return boxes;
}"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "datasets/processed/websight-v02")
    parser.add_argument("--limit", type=int, default=None, help="Limit processed records (for a pilot)")
    args = parser.parse_args()
    manifest_path = args.data_dir / "manifest.json"
    if not manifest_path.is_file():
        parser.error(f"manifest not found: {manifest_path}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is required. Run: pip install -e '.[browser]' && playwright install chromium", file=sys.stderr)
        return 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples = manifest.get("samples", [])
    limit = args.limit if args.limit is not None else len(samples)
    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(java_script_enabled=False)
        page = context.new_page()
        page.route("**/*", lambda route: route.abort())
        for record in samples[:limit]:
            html_name = record.get("html")
            html_path = args.data_dir / html_name if html_name else None
            if not html_path or not html_path.is_file():
                record["bboxes"] = []
                record["has_detection_labels"] = False
                failures += 1
                continue
            try:
                width = max(1, min(int(record.get("width", 1280)), 4096))
                height = max(1, min(int(record.get("height", 720)), 4096))
                page.set_viewport_size({"width": width, "height": height})
                page.set_content(html_path.read_text(encoding="utf-8", errors="replace"), wait_until="domcontentloaded")
                boxes = page.evaluate(_EXTRACT)
                record["bboxes"] = boxes
                record["has_detection_labels"] = bool(boxes)
                # Keep the original image dimensions in the manifest coordinates.
                record["bbox_source"] = "html_dom_approximate"
            except Exception as exc:  # continue through imperfect pages
                record["bboxes"] = []
                record["has_detection_labels"] = False
                record["bbox_error"] = str(exc)[:300]
                failures += 1
        context.close()
        browser.close()

    manifest["has_detection_labels"] = any(r.get("has_detection_labels") for r in samples)
    manifest["bbox_extraction"] = {
        "method": "offline_browser_dom_bounds",
        "approximate": True,
        "processed": min(limit, len(samples)),
        "labeled": sum(bool(r.get("has_detection_labels")) for r in samples[:limit]),
        "failures": failures,
    }
    # Persist per-sample records (also consumed by the existing pipeline tooling).
    for record in samples[:limit]:
        sample_path = args.data_dir / f"{record['sample_id']}.json"
        if sample_path.is_file():
            sample_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"DOM boxes: {manifest['bbox_extraction']['labeled']}/{manifest['bbox_extraction']['processed']} labeled; {failures} failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
