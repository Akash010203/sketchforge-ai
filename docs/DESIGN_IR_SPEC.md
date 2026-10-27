# Design IR specification (schema 1.0.0)

The Design IR is the single contract between vision, layout, rendering, editing, evaluation and
repair. A `DesignDocument` remains one page; a `DesignProject` composes independently valid page
documents and provides application routes. Its canonical pydantic v2 models are defined under `src/sketchforge/domain/`; the historical
`src/sketchforge/design_ir/schema.py` import path re-exports those models. It is serialised as
deterministic JSON (`serialization.to_json`: schema field order, 2-space indent, UTF-8).

## Conventions

* **Coordinates are absolute page coordinates in design pixels** (top-left origin, y down), for
  every component regardless of nesting. A component's box is *not* relative to its parent in the
  IR (the HTML/CSS export converts to parent-relative). Moving a component with `MoveCommand`
  moves its whole subtree.
* `BBox` is immutable, finite, rounded to 3 decimals and must have `w > 0`, `h > 0`.
* Design width is 1024 px for landscape sketches and 414 px for portrait ones
  (`config/app.yaml`); `metadata.source_transform` records `design = (source − offset) × scale`.
* IDs match `^[a-z][a-z0-9_-]{0,63}$` and are stable for the life of a document (`input-1`, …).
* Unknown fields are rejected (`extra="forbid"`); assignments are re-validated.

## Document

| Field | Meaning |
|---|---|
| `schema_version` | `"1.0.0"`; documents from a newer version are rejected, older ones are migrated (`migrations.py`) |
| `document_id`, `name` | identity and display name |
| `page` | `width`, `height`, `background`, `viewport {width, height, device}` |
| `root_id` | id of the single `page` component (the root) |
| `components` | flat list; hierarchy via `parent_id`; sibling paint order by `z_index` then list order |
| `metadata` | `source_image_sha256`, `source_size`, `source_transform`, `pipeline_version`, `notes` |

## Multi-page projects

`DesignProject` is the multi-page routing envelope. It contains a stable `project_id`, a list of
single-page `DesignDocument` values, one `PageRoute` per page, and a `start_page_id`. A route maps
the page document's `document_id` to an absolute URL path (for example `/` or `/settings`), with an
optional display title and authentication requirement. Project validation rejects duplicate page
IDs, duplicate routes (case-insensitive), references to missing pages, pages without routes, and
an unknown start page. Page documents remain unchanged and can still be serialized and hashed using
the existing single-document APIs.

## Component

| Field | Meaning |
|---|---|
| `type` | `page, container, header, sidebar, footer, card, button, input, text, heading, image, divider, checkbox, radio, unknown` |
| `bbox`, `z_index`, `parent_id` | geometry and tree position |
| `text`, `text_is_inferred` | text content; **`true` means a placeholder, not the user's words** (sketch text is not recognised). A user edit sets it to `false` |
| `typography` | `font_family, font_size (6–200), font_weight, line_height, text_align, color` (only on text-bearing types) |
| `style` | `fill, stroke, stroke_width, corner_radius, opacity` (`#rrggbb[aa]`, `transparent`, `none`) |
| `layout` | containers only: `mode (absolute/flex/grid), direction, gap, padding, align_items, justify_content, columns, inferred`. Geometry stays authoritative; this is a constraint and code-generation hint |
| `detection` | provenance for image-derived components: `confidence, source (heuristic/model/user/synthetic/remote), source_bbox (original-image px), type_scores, evidence[], ambiguous` |
| `states`, `interactions` | component states and `{event, action, target, inferred}` (inferred = guessed) |
| `visible`, `locked`, `editable` | editing guards: a locked component or a field not listed in `editable` cannot be changed by user commands |
| `codegen` | filled by the generation phase (Phase 8): `component_name`, `file_path` |

## Validation (`validation.validate_document`)

Errors make a document unusable (`raise_if_invalid()` is the gate used by the workflow):
`E_SCHEMA_VERSION`, `E_DUPLICATE_ID`, `E_ROOT_COUNT` (exactly one parentless component),
`E_ROOT_MISSING`, `E_ROOT_PARENT`, `E_PARENT_MISSING`, `E_SELF_PARENT`, `E_PAGE_NOT_ROOT` (only the
root may be type `page`), `E_CYCLE`, `E_UNREACHABLE` (not connected to the root), `E_OUTSIDE_PAGE`
(box entirely off the page).

Warnings are findings, not failures: `W_ROOT_BOX` (root differs from page size),
`W_OUTSIDE_PAGE` and `W_OVERFLOW_PARENT` (extends past page/parent beyond 1 px — the evaluator and
repair engine own these as `OVERFLOW_*` issues), `W_TEXT_ON_NON_TEXT` (text on a divider/image/page),
`W_INFERRED_FLAG_NO_TEXT`. Geometry checks are skipped when the tree itself is broken
(cycle / missing parent / duplicate id). `serialization.from_dict` additionally validates every field
through the models.

## Editing contract

All changes go through `editor.Command`s that (1) validate through the models, (2) capture the exact
prior state, and (3) can be undone byte-for-byte (`document_hash` equality is tested). A failed
command leaves the document untouched.

## Versioning

`SCHEMA_VERSION` follows MAJOR.MINOR.PATCH. A migration is a pure `dict → dict` function registered
for one version step (`Migrator.register`); the shipped chain is empty because 1.0.0 is the first
version. The mechanism is tested with a throw-away chain.

## Example (abridged)

```json
{"schema_version": "1.0.0", "document_id": "doc", "name": "login_page_synthetic.png",
 "page": {"width": 1024.0, "height": 743.0, "background": "#ffffff", "viewport": {"width": 1024, "height": 743, "device": "desktop"}},
 "root_id": "page",
 "components": [
  {"id": "page", "type": "page", "parent_id": null, "bbox": {"x": 0, "y": 0, "w": 1024, "h": 743}, ...},
  {"id": "input-1", "type": "input", "parent_id": "card-1", "text": "Enter text", "text_is_inferred": true,
   "bbox": {"x": 355.122, "y": 237.215, "w": 250.0, "h": 38.0},
   "detection": {"confidence": 0.82, "source": "heuristic", "ambiguous": true, ...}}]}
```
