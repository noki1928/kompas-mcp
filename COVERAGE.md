# Actual coverage (2026-10-01)

Environment: Windows, Python 3.13, KOMPAS-3D v25 Study, installed official API5/API7 TLBs. MCP publishes **77 tools**. This count is not a claim of complete CAD API coverage. Eight explicit-coordinate/contract convenience tools are documented in `EXPLICIT_GEOMETRY.md`.

## Live-tested through MCP, Python-script tool disabled

Latest completed runs (each has `passed.json`):

- `artifacts/stability-20261002-002455-569526/report.json`
- `artifacts/extended-20261002-002703-925074/report.json`
- `artifacts/explicit-20261002-002758-715784/report.json`

Combined: **271 MCP calls, all 76 published tool names exercised**, including intentional-denial cases. **56 unit tests pass**. This is tool-route coverage, not every input combination or SDK member. Native crashes in preceding failed attempts are explicitly recorded in `STABILITY.md`, not counted as complete runs. See `EXPLICIT_GEOMETRY.md` for coordinate/result contracts.

| Group | Verified |
|---|---|
| Discovery | State, SDK lookup, exact enums, generic property get, denied shutdown/private members |
| Documents | New part/drawing/assembly, activation, protected save, owned-document close |
| Recovery | Snapshot/working-copy SaveAs, new recovered document, matching properties |
| Basic model | Rectangle extrusion, circular through-cut, analytic volume, depth edit and restoration |
| Topology | Cylindrical face radius lookup, line edges/lengths, stale edge rejected after chamfer |
| Features | Chamfer, tree, parameters, native validity and rebuild |
| Sketch/rotation | Empty XY sketch, managed edit, rectangle plus axis, 360° boss rotation, analytic cylinder volume |
| Visualization | Isometric/front/top/right projections, viewport and multi-view PNG files |
| Neutral export | Nonempty STEP AP214 and binary STL |
| Drawing | A4 portrait/stamp, three model-source views, true 50 mm linear dimension, typed geometry coordinates and nominal-value reading |
| Drawing export | Native 300 dpi PNG, native PDF with `%PDF-` signature, 150 dpi sheet tiles |
| Assembly | Two linked components, translation with origin readback, recursive tree, rebuild, PNG, A3D save |

Earlier 16 unit tests and original live 2D/3D tests established primitive validation, rollback behavior, origin planes and extrusion/cut direction conventions. Additional unit tests cover registry, policy and output guards.

The part is a 50×30×20 plate, Ø10 through-hole and one 1 mm chamfer. Before chamfer: `30000 - pi*25*20` mm³; after chamfer: approximately `28404.2036732051` mm³. Rotation example: radius 15 mm, length 120 mm, volume `pi*225*120` mm³. Test assembly's second origin is read back as `[100,0,0]` mm.

## Implemented but not established by this end-to-end run

The additional stability suite now verifies fillet/radius editing; cut rotation with analytic volume reduction; sketch-on-face; arbitrary camera; all supported dimension kinds and orientations; selection; generic setters, batches and release; special document creation/closure; IGES and Parasolid; fragment JPEG/readback; protected saves; and component axes after save/reopen. Unexercised generic interfaces, non-XY custom managed profiles and full content editing of special documents still need individual tests.

## Discoverable API routes, not semantic or verified workflows

Lofts, sweeps, shells, drafts, booleans, patterns, complex surfaces, imported geometry healing, advanced constraints, angular dimensions, sections/detail views, drawing tolerances/technical demands, assembly mates, BOM/specification generation and complete dependency graphs. Generic discovery/dispatch enables investigation, not a promise that these operations work unchanged. Native enum/signature presence alone is insufficient.

## Known limitations

- Topology handles are transient, not persistent face/edge naming. Manual changes may outrun update-stamp detection.
- Generic COM output arguments depend on pywin32 and native signatures. No universal typed marshaler for every SDK structure.
- New tools return structured errors; legacy tools retain prior behavior.
- Model views remain linked to saved source paths. Lookup preserves existing source documents and closes only temporary documents it opened; the stability suite checks document-count preservation. View types should be read back: KOMPAS may return type 2 despite creation with standard-view enum 3.
- Coordinate dimensions are real CAD dimensions but not bound to model edges. Test drawing is an integration fixture, not a complete production drawing.
- API7 `UpdatePlacement` can return false despite matching placement readback. Tools report a warning; origin and requested axes are verified explicitly. Component rotation is tested with SAFEARRAY matrix initialization and persistence through save/reopen.
- Checkpoints are copied files, not transactions or dependency snapshots. No automatic Undo or guaranteed rollback.
- PDF print scale and neutral-export geometric fidelity have not been independently certified. Only output existence/signature and drawing raster appearance were checked.
- PrintWindow depends on visible/restored windows and renderer behavior. Cropped parent-window fallback is used when child capture fails.
- Output files are protected by default, but generic dispatch is not a sandbox. Do not expose the server to untrusted clients.
- Logs need external rotation. Tests do not prove long-session memory behavior, every license tier or older KOMPAS versions.

The earlier 100×60×30 source model remains unchanged. `scripts/example_plate_drawing.py` creates a NEW associative A3 drawing plus PNG/PDF. Horizontal/vertical and Ø18 nominal values are asserted; this exposed and fixed the actual SDK orientation values (parallel=0, horizontal=1, vertical=2). This replaces neither the earlier partial manual drawing nor a complete section A–A/manufacturing specification.

Corrected original-model drawing: `artifacts/original-plate-drawing-20261001-201834-651366/plate-100x60x30-corrected.{cdw,png,pdf}`. The side-view thickness dimension was corrected using generic setters and Update after checking the image: that projection extends from X=-30 to X=0, not X=0 to X=30. Existing output files were retained. Vertical 60/32 and diameter 18 values were checked, but source-like stepped section A–A, full locating dimensions and technical requirements are still missing.
