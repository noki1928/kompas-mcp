# Agent workflow

The agent interprets tasks, selects geometry and decides corrections. MCP performs explicit CAD operations; no hidden model-planning service is provided.

1. `get_kompas_state`, `list_documents`: record initial documents and active reference. Use a new document unless editing was requested. Never close/discard unrelated documents.
2. Convert the task into units, origin, profiles, feature order and measurable invariants. Ask about ambiguous dimensions or manufacturing assumptions.
3. Prefer `create_document(part)` → `create_closed_profile` with explicit model-space input axes → `extrude(direction=..., expected=...)` / `cut_through_all`. For existing/simple native-local sketches use `get_sketch_frame` and `transform_sketch_points`; never guess XZ/YZ signs. Default extrusion joins into exactly one solid body; intentional multi-body output needs explicit auto/new_body mode. Custom manual edits remain supported, but finish them even after an error.
4. `get_model_tree`, `get_model_properties`, `find_faces`, `find_edges`: inspect solidness, bbox, volume and expected geometry. Select edges by measured properties, not collection index alone. Reacquire after every mutation.
5. Store measurable requirements with `assert_register` (e.g. `bounds_within` the enclosure envelope). Wrap each logical change in `change_begin(label)` … `change_end`; read every result's `effect.verdict` and stop on `no_effect`, `broken` or `assertion_failed`. `change_abort` reverts the stage's appended features and parameter edits. Use `create_checkpoint` additionally before deleting existing features or generic API edits, which a stage cannot revert. `get_feature_parameters` → `set_feature_parameters` or `edge_operation` → `rebuild_model` → `validate_document`.
6. `show_application` → `capture_views`: inspect independent projections, not only an isometric screenshot. Correct discrepancies and remeasure. Screenshot success can still produce blank pixels; inspect actual images.
7. `save_document` to a new M3D path. `create_document(drawing)` → `drawing_sheet` → `create_model_view` with explicit X/Y axes for required orientation. Alternatively create permanent `create_model_projection` in the model BEFORE saving, then select it by name. Returned conservative projection bounds help layout. Changing viewport camera must not replace permanent drawing projections.
8. Prefer `add_model_dimension` to project model XYZ through the actual native view; use `project_model_points` for custom annotations. `add_dimension` still accepts native view-local coordinates. Read `get_document_structure`/`find_drawing_objects` and verify nominal values. Coordinate-driven dimensions are not model-edge associative; missing dimensions, tolerances and sections remain the agent's responsibility.
9. Save CDW before `export_drawing_pdf`; render `export_drawing_image` and, for dense sheets, `capture_drawing_tiles`. Inspect layout, readability and PDF print scale.
10. `export_model` for STEP/STL; report native files, exported files, measured invariants and remaining limitations.

## When a semantic tool is missing

Use `sdk_catalog(interface=...)` and `describe_object(target)` to find installed members. Fetch exact enums with `api_constants`. Navigate one property at a time with `kompas_api_call`; cast base objects to official interfaces as necessary. Pass returned handles using `{object_id: ...}`. Calls need `allow_mutation=true`, including read methods. Never invent a member based on its English name. Declared SDK availability is not evidence of runtime success.

## Error loop

On `success=false`, inspect HRESULT/details, `failures`, `cleanup` and actual state. A failed call may already have changed CAD. Verified constructive tools clean only their new feature and report metric readback; a failed cleanup requires stopping and explicit recovery, not retry. `check_model_contract` verifies the intended body count/bounds/volume. Do not blindly replay a batch or automatically reverse extrusion direction. Refresh state, finish any open sketch and correct explicitly or restore a checkpoint into a new document. Keep the damaged working copy until recovery is verified. Before closing, use an explicit reference and save or obtain intent to discard.

## Reproducible examples

`tests/smoke_extended.py` is a complete MCP-client example: scripts disabled, separate documents, analytic volume checks, editing, fresh topology, chamfer, three associative views, real dimension, recovery, rotation, linked assembly and exports. `tests/smoke_mcp.py` and `tests/smoke_3d.py` exercise earlier tools. `scripts/example_plate_drawing.py` generates an associative drawing from the original 100×60×30 model without editing that source.

Run with the project interpreter:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe tests/smoke_extended.py
.\.venv\Scripts\python.exe tests/smoke_stability.py
.\.venv\Scripts\python.exe tests/smoke_explicit_geometry.py
```

Live tests require installed KOMPAS and create unique `artifacts/extended-*` output directories. They close only their owned documents and restore the initial active document. An interrupted process may leave test documents open: inspect paths before cleanup.
