# Stability baseline

Original scope: repair and verify the existing 68 tools, not add new CAD operation families. The later explicit-coordinate/contract layer adds eight convenience tools (76 total), described in `EXPLICIT_GEOMETRY.md`.

## Fixed

- Closed-document handles are pruned even without prior topology invalidation. Application-root navigation records document ownership, including `IPartDocument`.
- Generic gets inspect invocation kinds before getattr, preventing accidental API5 zero-argument method execution. Lifecycle deny checks are case-insensitive.
- Lost COM sessions clear handles/edit state without replaying mutations. `status` can reconnect; other operations report connection loss and require explicit recovery.
- Managed sketch edits block document switching, save/close, checkpoints and feature construction. EndEdit releases edit-context handles. Shutdown attempts EndEdit without saving/discarding user work.
- Worker shutdown is idempotent; submissions after shutdown fail explicitly. Logging failures cannot turn completed CAD actions into retries.
- Numeric/boolean inputs, dimensions, vectors, filters and batch output paths are validated before their first relevant mutation. Rotation edits preserve the existing angle if only direction changes.
- Fragment reading/raster export no longer assumes LayoutSheets exists. Reading sheet format does not Update or mark a drawing changed.
- Model-view lookup restores drawing activation and closes only temporary documents it opened. Invalid lookup does not allocate a view first; failed new-view construction attempts cleanup.
- Camera uses a dedicated user projection because built-in projection placements are read-only. Standard orientations are preserved; prior server-owned camera projections are replaced.
- Parasolid uses official `format_XT`, not nonexistent `format_PARASOLID`.
- Component orientation uses `InitByMatrix3D` with SAFEARRAY(double), not successive SetVector calls (which rotate the entire basis). Origins/axes are read back and tested after save/reopen.
- PDF/raster/neutral/DXF exports use private sibling staging files. Failed converters cannot return success based on an older output; existing files remain protected by default.
- Save checks extension, file size, association and Changed flag. Parameter edits propagate rebuild failures. Failed new-feature construction attempts cleanup of only its newly allocated feature.

## Regression gate

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe tests/smoke_extended.py
.\.venv\Scripts\python.exe tests/smoke_stability.py
```

Run live suites sequentially: they share one KOMPAS instance and must not compete for its active document. Unit tests use mocks and can run independently. Currently **56 unit tests pass**.

`smoke_extended.py`: analytic plate/cylinder volumes, chamfer, parameters, native tree, stale topology, checkpoints, multi-view feedback, associative drawing, STEP/STL/PDF/raster and linked assembly.

`smoke_stability.py`: legacy 2D/DXF, fragment JPEG/readback, save/close guards, fillet radius edits, sketch-on-face, edit-state blocking, partial sketch errors, generic schema/read/set/batch/release, camera, IGES/Parasolid, partial-angle preservation, cut rotation, every supported dimension kind/orientation, lookup-document leaks, read-only sheet, component matrix roundtrip, selection and special-document creation/closure.

Both suites produce unique report directories. `passed.json` is written only after the entire suite completes. PASS lines without this marker may belong to failed/interrupted runs.

Complete strengthened stability run: `artifacts/stability-20261001-205308-381115/report.json` (component axes readback and save/reopen included).

Complete extended run: `artifacts/extended-20261001-205505-509013/report.json`. Combined coverage: **188 MCP calls and all 68 published tool names**, counting intentionally denied script execution. This does not imply all parameter combinations or every generic native API route are covered.

## Boundaries

A passing suite is not proof of indefinite uptime or all native parameter combinations. External application termination, license restrictions, degenerate kernel geometry and renderer behavior remain outside server guarantees.

There is no hard cancellation of COM, automatic mutation replay, automatic user-document save or guaranteed transaction rollback. RPC-loss reset is mock-tested; native termination is not intentionally induced while user work might be open. One externally interrupted run remains recorded as incomplete.

Generic access is not a sandbox or certification of every SDK interface. Legacy tools keep protocol `isError=true`; extended errors return structured `success=false`. Clients/tests must check both.

Checkpoints still use separate SaveAs working copies, without external dependency snapshots. Logs require external rotation. Neutral export fidelity and manufacturing approval are not certified.

See `COVERAGE.md` for CAD workflow coverage. Keep these regressions as the gate before further expansion.

## Explicit-coordinate verification, 2026-10-02

The eight convenience tools and stricter constructive-result contracts are described in `EXPLICIT_GEOMETRY.md`. Unit total is 56, including coordinate/projection matrices, contour intersections, bounds and cleanup-failure reporting.

During verification two broader runs encountered native application failures (drawing close and later standard-view creation). Windows Application Error/.NET Runtime entries recorded `kStudy.Exe` v25.0.0.2735 failures in `ucrtbase.dll` (0xc0000409, 00:03:21) and `VCRUNTIME140.dll` (0xc0000005 / 0xc000041d, 00:20:57 / 00:21:26). These are failed runs, not successful regressions. The native root cause is not established and is not claimed fixed by this server.

Drawing lookup now reads only body bounds instead of unrelated mass/inertia calculations, and errors include `cad_stage` to identify failing native phases. A later isolated stability suite completed (`artifacts/stability-20261002-002455-569526/`). Native process-crash risk remains: successful reruns are evidence for exercised paths, not proof of indefinite KOMPAS uptime. CAD mutations are never replayed automatically after a lost session.

Final completed verification on the revised code: stability `20261002-002455-569526`, extended `20261002-002703-925074`, explicit geometry `20261002-002758-715784`. All three have `passed.json`; together **271 calls / all 76 exposed tool names**. The explicit recipe includes rejected detached material, metric-restoring cleanup, targeted/bilateral through-cuts, bracket reconstruction and correct drawing orientation after save/reopen.

## Temporary quarter-cut drawing workflow: not completed

Later manual work on the slider exposed another boundary: an associative-view rebuild can affect sibling views using the same model. Closing an unsaved source document and reopening its path did not reliably evict the modified model retained by the open drawing. Treat this as shared native in-memory state, not proof that the file was saved.

Native `IKompasDocument2D1.DestroyObjects(view)` returned true and changed view type from associative to ordinary, but the attempted sequence did not retain the desired quarter-cut geometry after model restoration. This is NOT a certified cutaway workflow; do not advertise it as implemented or infer success from those return values alone. Temporary sketch/cut features were explicitly removed, original model volume restored and its on-disk hash verified unchanged. The cutaway drawing was not published as a completed result.
