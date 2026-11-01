# Explicit geometry and verified constructive steps

This layer prevents the coordinate, unintended multi-body and view-orientation mistakes found while rebuilding the supplied bracket. It does not interpret an image or make engineering assumptions for the agent.

## Coordinates

`get_sketch_frame(sketch_id)` transfers the API5 sketch to the official API7 `ISketch` (`TransferInterface(..., ksAPI7Dual=2, ksObjectSketch=11006)`) and samples `GetPoint3D(0,0)/(1,0)/(0,1)`. **Support-surface UV is not sketch UV.** The returned origin, X/Y and cross-product normal describe the actual sketch, including its handedness, rotation and location.

`transform_sketch_points` performs model/sketch conversion. Off-plane points are rejected, not silently projected.

`create_closed_profile` accepts ordered closed contours:

```json
{
  "plane": "XZ",
  "origin": [0, 0, 0],
  "x_axis": [1, 0, 0],
  "y_axis": [0, 0, 1],
  "contours": [[
    {"kind":"line", "start":[12.5,35], "end":[52.5,35]},
    {"kind":"line", "start":[52.5,35], "end":[52.5,50]},
    {"kind":"arc", "center":[32.5,50], "radius":20, "start_angle":0, "end_angle":180},
    {"kind":"line", "start":[12.5,50], "end":[12.5,35]}
  ]]
}
```

Input axes are normalized and checked for orthogonality. Coordinates are converted to the actual native sketch frame; reflected arcs reverse their winding. With no axes the input is native sketch-local.

All contour topology is checked before creation: closure, zero-length segments, line/arc/circle intersections, overlaps and touching nonadjacent boundaries. Circles occupy their own contours; nested nonintersecting contours are allowed. Splines are not supported by this validator. Native kernel acceptance is still checked during feature creation.

The selected support must be an existing origin plane or planar face/plane handle. Explicit input origins and axes must lie on that support. This does **not** silently create arbitrary offset/tilted construction planes. Use a validated support handle for those planes. If conversion/editing fails, only the newly created sketch is eligible for cleanup; failed EndEdit retains recovery state and prevents unsafe deletion.

## Direction, targets and result contracts

`extrude` and `cut_extrude` now accept a model-space `direction` vector. It must align with the sketch normal; combining it with `reverse=true` is rejected. There is no opposite-direction retry.

- `extrude(result_mode="join")` defaults to **exactly one solid body**. Detached material is rejected and the new feature is cleaned up.
- `result_mode="auto"` permits intentional multi-body output.
- `result_mode="new_body"` explicitly selects the native new-body mode; its default count contract is prior count + 1 (override explicitly for multiple profiles).
- Cuts preserve body count by default; splitting/removing an entire body needs an explicit count in `expected`.
- `cut_through_all` uses native `etThroughAll=1`, not a guessed large depth. `both_sides=true` uses native `dtBoth=2`.
- Cuts target all top-part bodies by default; `target_body_ids` selects fresh body handles from `get_model_properties`. Reacquire them after sketch creation/rebuild.

Official selection enums are distinct: feature `chooseType=ksChBodies(3)` selects the body domain; `ChooseBodies().ChooseBodiesType` selects new/automatic/manual/all (0/1/2/3). Manual targets go into `ChooseBodies().BodyCollection()`. Do not confuse those two properties.

```json
{
  "sketch_id":"obj_from_profile",
  "depth":80,
  "direction":[0,1,0],
  "result_mode":"join",
  "expected":{
    "body_count":1,
    "bounds_mm":[0,0,0,120,80,70],
    "volume_mm3":532530.9649148734
  }
}
```

`expected` supports `body_count`, `bounds_mm`, `volume_mm3`, absolute `tolerance` (default 1e-6) and `relative_tolerance` (default 1e-6; kernel volume readback noise is ~5e-7 relative), each capped at 0.01. Unknown keys and invalid tolerances fail before the operation.

Each new extrusion/rotation/edge operation reads before/after body metrics, validates solidity/native feature errors and the contract. Addition/subtraction checks actual volume change; edge operations do not assume a particular volume sign. `check_model_contract` exposes the same read-only checks independently.

For cuts, a direction interval provides an initial necessary test. A freshly validated profile additionally provides a swept bounding-box intersection test, when its native update stamp still matches. This is **not proof of kernel intersection**; actual volume decrease remains the decisive postcheck. A stale/missing profile cache falls back to the direction check.

Rejected geometry returns `success=false`, before/rejected metrics, failed checks and cleanup outcome. Cleanup only deletes the new feature, rebuilds and compares body count, volume and bounds with the pre-operation state. It is not a universal transaction or complete dependency rollback. If cleanup fails, stop and recover explicitly. `cleanup_sketch=true` on `extrude`/`cut_extrude`/`cut_through_all` also deletes the profile sketch after a successful feature cleanup. Only feature errors introduced by the operation fail it; errors already present are returned as `preexisting_feature_errors`.

## Stable drawing orientation

`create_model_view` supports either standard native projection, `projection_name`, or explicit model-space `x_axis`/`y_axis`/`origin`. Explicit axes set the drawing's official `ProjectionMatrix`; the saved source model is not modified. **This native matrix is a view-to-model placement**, not the model-to-view matrix one might otherwise expect.

The server verifies the requested origin and basis using native `IAssociationView.GetProjectionPoint`. A successful property assignment is not treated as proof of correct orientation. Returned `projected_model_bbox_mm` is the projection of the model's 3D bounding-box corners: conservative, not exact visible geometry extents.

`create_model_projection` creates a permanent named projection in the active model, without saving any file. Existing names cannot be overwritten. Permanent projections are not removed by subsequent `set_camera` calls. Save explicitly before creating a linked drawing by name.

`project_model_points` converts model XYZ to actual view UV with `GetProjectionPoint`; `to_sheet=true` includes native view scale/angle/translation. `add_model_dimension` projects two model points and a model-space label point, creates a real linear dimension and checks its nominal value. These dimensions are coordinate-driven, not automatically associated with model edges; projection is not a visibility test.

## Regression recipe

Run sequentially:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe tests/smoke_explicit_geometry.py
.\.venv\Scripts\python.exe tests/smoke_extended.py
.\.venv\Scripts\python.exe tests/smoke_stability.py
```

The explicit suite reconstructs the bracket with direct YZ separation and no geometry repairs or sign guesses, checks **one solid 120×80×70 mm**, analytic **327519.6334468673 mm³**, single/bilateral/selected-body cuts, contract-failure cleanup, coordinate roundtrips, persistent projections, actual drawing orientation, model-point dimensions and drawing save/reopen. All outputs/documents are separate from the original bracket files. Only a final `passed.json` marker certifies whole-suite completion.

Complete verified run: `artifacts/explicit-20261002-002758-715784/report.json` (with `passed.json`). Combined with the latest two baseline suites: 271 calls, all 76 tool names. Unit total: 56. See `STABILITY.md` for preceding native process-crash incidents and remaining limits.
