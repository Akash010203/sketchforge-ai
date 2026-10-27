# Design IR specification (schema 1.0.0)

Design IR defines the data contract used by SketchForge across vision, layout, rendering, editing, evaluation, and repair.

A `DesignDocument` represents a single page. A `DesignProject` combines multiple valid page documents and defines how users navigate between them.

The canonical Pydantic v2 models live under `src/sketchforge/domain/`. The older import path, `src/sketchforge/design_ir/schema.py`, re-exports these models for compatibility.

Documents are serialized as deterministic JSON using `serialization.to_json`, with fields in schema order, two-space indentation, and UTF-8 encoding.

## Conventions

- **Coordinates:** All component positions use absolute page coordinates in design pixels, with the origin at the top-left and the y-axis increasing downward. Child coordinates are not relative to their parents. HTML/CSS export converts them to parent-relative positions where needed. Moving a component with `MoveCommand` moves its entire subtree.
- **Bounding boxes:** `BBox` is immutable, contains finite values rounded to three decimal places, and requires `w > 0` and `h > 0`.
- **Page width:** Landscape sketches use a design width of 1024 px, while portrait sketches use 414 px. These defaults are defined in `config/app.yaml`. The `metadata.source_transform` field records the transformation as `design = (source − offset) × scale`.
- **IDs:** IDs must match `^[a-z][a-z0-9_-]{0,63}$` and remain stable throughout a document's lifetime. Examples include `input-1` and `card-1`.
- **Validation:** Unknown fields are rejected through `extra="forbid"`, and assignments are revalidated.

## Document structure

| Field | Description |
|---|---|
| `schema_version` | The schema version, currently `"1.0.0"`. Newer versions are rejected, while older versions are migrated through `migrations.py`. |
| `document_id`, `name` | Document identity and display name. |
| `page` | Page dimensions, background color, and viewport settings (`width`, `height`, `device`). |
| `root_id` | ID of the single root component, which must have type `page`. |
| `components` | A flat component list. Hierarchy is defined by `parent_id`; sibling paint order follows `z_index`, then list order. |
| `metadata` | Source image SHA-256 hash, source dimensions, source transformation, pipeline version, and notes. |

## Multi-page projects

`DesignProject` provides the routing structure for multi-page applications. It contains a stable `project_id`, a list of `DesignDocument` instances, one `PageRoute` per page, and a `start_page_id`.

Each route maps a page's `document_id` to an absolute URL path, such as `/` or `/settings`. Routes can also include a display title and an authentication requirement.

Project validation rejects duplicate page IDs, duplicate routes (case-insensitive), routes that reference missing pages, pages without routes, and unknown start pages.

Each page remains an independent `DesignDocument`. Existing single-document serialization and hashing APIs continue to work without modification.

## Component model

| Field | Description |
|---|---|
| `type` | Component type: `page`, `container`, `header`, `sidebar`, `footer`, `card`, `button`, `input`, `text`, `heading`, `image`, `divider`, `checkbox`, `radio`, or `unknown`. |
| `bbox`, `z_index`, `parent_id` | Geometry, paint order, and hierarchy. |
| `text`, `text_is_inferred` | Text content and whether it is a placeholder. When `text_is_inferred` is `true`, the text is inferred rather than recognized from the user's sketch. A user edit sets it to `false`. |
| `typography` | Text styling: `font_family`, `font_size` (6 to 200), `font_weight`, `line_height`, `text_align`, and `color`. Available only on text-bearing component types. |
| `style` | Visual properties: `fill`, `stroke`, `stroke_width`, `corner_radius`, and `opacity`. Colors accept `#rrggbb[aa]`, `transparent`, or `none`. |
| `layout` | Container-only settings: `mode` (`absolute`, `flex`, or `grid`), `direction`, `gap`, `padding`, `align_items`, `justify_content`, `columns`, and `inferred`. Geometry remains authoritative; layout settings guide constraint handling and code generation. |
| `detection` | Provenance for image-derived components, including `confidence`, `source` (`heuristic`, `model`, `user`, `synthetic`, or `remote`), `source_bbox` in original-image pixels, `type_scores`, `evidence[]`, and `ambiguous`. |
| `states`, `interactions` | Component states and interaction definitions. Each interaction contains `event`, `action`, `target`, and `inferred`; `inferred` indicates that the interaction was guessed. |
| `visible`, `locked`, `editable` | Editing controls. Locked components and fields excluded from `editable` cannot be changed through user commands. |
| `codegen` | Generation metadata populated during Phase 8, including `component_name` and `file_path`. |

## Validation rules

`validation.validate_document` reports errors that make a document unusable. The workflow uses `raise_if_invalid()` as the validation gate.

The supported error codes are:

- `E_SCHEMA_VERSION`: Unsupported schema version.
- `E_DUPLICATE_ID`: Duplicate component IDs.
- `E_ROOT_COUNT`: The document does not have exactly one parentless component.
- `E_ROOT_MISSING`: The specified root does not exist.
- `E_ROOT_PARENT`: The root has a parent.
- `E_PARENT_MISSING`: A component references a missing parent.
- `E_SELF_PARENT`: A component references itself as its parent.
- `E_PAGE_NOT_ROOT`: A component other than the root has type `page`.
- `E_CYCLE`: The component hierarchy contains a cycle.
- `E_UNREACHABLE`: A component is disconnected from the root.
- `E_OUTSIDE_PAGE`: A component's bounding box lies entirely outside the page.

Warnings identify issues without automatically invalidating the document:

- `W_ROOT_BOX`: The root bounding box differs from the page dimensions.
- `W_OUTSIDE_PAGE`: A component extends beyond the page.
- `W_OVERFLOW_PARENT`: A component extends more than 1 px beyond its parent. The evaluator and repair engine handle these as `OVERFLOW_*` issues.
- `W_TEXT_ON_NON_TEXT`: Text is assigned to a divider, image, or page.
- `W_INFERRED_FLAG_NO_TEXT`: The inferred-text flag is set when no text is present.

Geometry checks are skipped when the component tree is structurally broken by a cycle, missing parent, or duplicate ID. In addition, `serialization.from_dict` validates every field through the Pydantic models.

## Editing contract

All document changes must go through `editor.Command` implementations. Each command must:

1. Validate changes through the models.
2. Capture the exact previous state.
3. Support byte-for-byte undo, verified through `document_hash` equality.

If a command fails, the document must remain unchanged.

## Versioning and migrations

`SCHEMA_VERSION` follows semantic versioning in `MAJOR.MINOR.PATCH` format.

Each migration is a pure `dict → dict` function registered for a single version step through `Migrator.register`. Since `1.0.0` is the first schema version, the shipped migration chain is empty. The migration mechanism is tested separately using a temporary migration chain.

## Example

The following abridged JSON illustrates a page document with a root component and an inferred input field.

```json
{
  "schema_version": "1.0.0",
  "document_id": "doc",
  "name": "login_page_synthetic.png",
  "page": {
    "width": 1024.0,
    "height": 743.0,
    "background": "#ffffff",
    "viewport": {
      "width": 1024,
      "height": 743,
      "device": "desktop"
    }
  },
  "root_id": "page",
  "components": [
    {
      "id": "page",
      "type": "page",
      "parent_id": null,
      "bbox": {
        "x": 0,
        "y": 0,
        "w": 1024,
        "h": 743
      }
    },
    {
      "id": "input-1",
      "type": "input",
      "parent_id": "card-1",
      "text": "Enter text",
      "text_is_inferred": true,
      "bbox": {
        "x": 355.122,
        "y": 237.215,
        "w": 250.0,
        "h": 38.0
      },
      "detection": {
        "confidence": 0.82,
        "source": "heuristic",
        "ambiguous": true
      }
    }
  ]
}
```

The example is abbreviated. A complete document must include all required fields and satisfy the schema's validation rules.
