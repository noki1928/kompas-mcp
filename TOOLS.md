# Tool catalog

85 tools: original registrations in `server.py`, extended registrations in `extended_tools.py`. Tool schemas/docstrings are the authoritative parameter reference exposed through MCP `list_tools`. See [explicit geometry contracts](EXPLICIT_GEOMETRY.md).

## Original tools (preserved)

`status`, `create_document`, `open_document`, `save_document`, `set_layer`, `line`, `rectangle`, `circle`, `arc`, `polyline`, `text`, `delete_object`, `export_dxf`, `screenshot`, `execute_python_script`, `sketch3d`, `extrude`, `cut_extrude`, `model_info`, `fit_view3d`.

Scripts require `KOMPAS_ALLOW_SCRIPTS=1`; ordinary agent workflows should not need them. Native saves protect existing paths unless overwrite is explicit. `create_document` now also accepts assembly, specification, text and technology_assembly.

## Extended tools

| Category | Tools |
|---|---|
| State/discovery | `get_kompas_state`, `show_application`, `sdk_catalog`, `api_constants`, `describe_object` |
| Generic access | `kompas_api_call`, `api_batch`, `get_object_properties`, `release_objects` |
| Lifecycle | `list_documents`, `activate_document`, `close_document`, `save_current_document` |
| Recovery | `create_checkpoint`, `restore_checkpoint` |
| Sketches | `create_sketch`, `begin_sketch_edit`, `create_sketch_entities`, `end_sketch_edit`, `get_sketch_frame`, `transform_sketch_points`, `create_closed_profile` |
| Construction/edit | `revolve`, `edge_operation`, `get_feature_parameters`, `set_feature_parameters`, `rebuild_model`, `delete_feature` |
| Inspection | `get_model_tree`, `get_model_properties`, `find_faces`, `find_edges`, `validate_document`, `check_model_contract` |
| Camera/images | `set_standard_view`, `set_camera`, `fit_view`, `capture_viewport`, `capture_views`, `create_model_projection` |
| Drawing | `drawing_sheet`, `create_model_view`, `set_drawing_view`, `add_dimension`, `get_document_structure`, `find_drawing_objects`, `project_model_points`, `add_model_dimension` |
| Exports | `export_model`, `export_drawing_image`, `export_drawing_pdf`, `capture_drawing_tiles` |
| Assembly/selection | `get_assembly_tree`, `add_component`, `set_component_placement`, `selection` |
| Verified through-cut | `cut_through_all` |
| Change stages | `change_begin`, `change_status`, `change_end`, `change_abort` |
| Stored assertions | `assert_register`, `assert_list`, `assert_remove`, `assert_check` |

## Common contracts

- Document selectors: native `document_reference` from state/list. Object selectors: process-local `obj_*` IDs. Checkpoints: process-local `checkpoint_*` keys with saved files usable after restart.
- All lengths mm, angles degrees. Profiles and drawing annotations are local; view placement is sheet-local; components parent-local. Properties expose area mm², volume mm³, mass g.
- Extended success results use `success=true`. Every failure of every tool is protocol `isError=true` carrying the same `success=false` JSON in `structuredContent` and text. A successful native invocation can return `result=false` and must be interpreted per API semantics.
- Protected exports need `overwrite=true` for existing files; current-file save needs `confirm_overwrite=true`; closing unsaved work needs `discard_changes=true`.
- `capture_viewport` without path returns MCP image content; with path returns file metadata. Native drawing raster supports dpi 72..600 and 1-based sheet selection.
- `api_batch` and sketch entity batches are non-atomic. Check `executed`/partial results and actual state before retrying.
- `create_closed_profile` validates full contours and manages editing/cleanup. `extrude` now defaults to one-body join; intentional multi-body output requires `result_mode=auto/new_body`. Constructive failures can return structured `success=false`, including on original extrusion tools. Always check it.
- Successful part mutations (`extrude`, `cut_extrude`, `cut_through_all`, `revolve`, `edge_operation`, `set_feature_parameters`, `delete_feature`) return `effect`: `verdict` (`ok`, `no_effect`, `broken`, `assertion_failed`), volume delta, body count before/after, bounds change, new feature errors and failing stored assertions. `before`/`after` are compact metrics without the per-body list.
- A change stage (parts only) pins mutations to its document and refuses closing it. `change_abort` deletes features appended since `change_begin` (newest first), restores parameters edited through `set_feature_parameters`, and verifies the start metrics; it refuses when pre-existing features were deleted, renamed or reordered. It is not KOMPAS Undo (see `STABILITY.md`). `change_end` refuses a `broken`/`assertion_failed` verdict unless `force=true`. Stages and assertions are process-local.
- `set_component_placement` translations and normalized orthogonal axes are tested, including save/reopen. Camera uses a dedicated user projection instead of changing read-only standard orientations. Detailed tested scope is in `COVERAGE.md`.

## Generic example

```json
{"target":"document","operation":"cast","interface":"IKompasDocument2D"}
```

Read `ViewsAndLayersManager` on the returned handle using `operation=get`. Navigate `Views`; use `describe_object` to obtain methods and exact parameters. A call looks like:

```json
{"target":"obj_returned_collection","operation":"call","member":"Item","arguments":[0],"allow_mutation":true}
```

Collection results may be base interfaces; cast to the official specialized interface before reading geometry. Never infer writable properties from names: `IDimensionText.Prefix` is an `ITextLine`; set its `Str`, not the `Prefix` property itself.
