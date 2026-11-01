# Working in this repository

## Runtime and commands
- Windows COM requires standard Windows Python 3.13. Use `.\.venv\Scripts\python.exe`, not bare `python` (which may resolve to MSYS2).
- Start MCP: `.\.venv\Scripts\python.exe server.py`. It waits for stdio protocol messages; stdout must contain no diagnostics or debug prints.
- Unit suite (no live CAD required): `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v`.
- Focused test: `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_geometry.py" -k test_frames_roundtrip_all_planes -v`.
- Live regressions, **sequentially**, with installed KOMPAS and an unminimized window:
  - `.\.venv\Scripts\python.exe tests/smoke_explicit_geometry.py`
  - `.\.venv\Scripts\python.exe tests/smoke_extended.py`
  - `.\.venv\Scripts\python.exe tests/smoke_stability.py`
- These three suites launch their own MCP processes with scripts disabled, but share the same KOMPAS instance. Do not operate CAD concurrently. Only a final `artifacts/<run>/passed.json` certifies a complete run; partial reports/PASS lines do not.
- Repo-local `opencode.json` is ignored, contains absolute machine-specific paths, and currently enables unrestricted Python scripts. Do not assume its script policy matches the test subprocesses. Reconnect only `kompas` after backend/tool-schema changes; the running server does not reload edits.
- Claude Code connects the server from the committed `.mcp.json` (relative `.venv` interpreter, scripts disabled); prefer it over ad-hoc stdio client scripts, which lose handles between runs.
- Startup error `module 'win32com.gen_py.69AC2981-…' has no attribute 'MinorVersion'` means a half-written makepy cache: delete only that folder under `%LOCALAPPDATA%\Temp\gen_py\3.13\`; it regenerates.

## Implementation boundaries
- `server.py` registers original tools; `extended_tools.register()` adds wrappers. `Kompas` composes backend mixins in `kompas.py`; `ComWorker` serializes all native calls on one COM STA thread. Never move COM proxies into MCP handlers, other threads, or JSON results; return registry handles/serializable data instead.
- `geometry.py` is COM-free validation/transforms; `safe_modeling.py` applies them to native operations and verifies result contracts. Keep engineering interpretation in the agent, not hidden server planning.
- Verify native members/enums against installed TLBs using `sdk_catalog`, `api_constants`, and runtime `describe_object`. `.\.venv\Scripts\python.exe scripts/audit_sdk.py` regenerates ignored `artifacts/sdk/` snapshots (defaults to v25 Study; accepts a Bin-directory argument). Discoverable API members are not evidence of a working CAD workflow.
- Every failure (original or extended tool, raised or rejected) is protocol `isError=true` with the same JSON (`success=false`, diagnostics, `failures`, `cleanup`) in `structuredContent` and the text block (`diagnostics.tool_result`). Clients still read `success`.
- Constructive operations fail only on feature errors they introduced; pre-existing broken user features are reported as `preexisting_feature_errors`, not blocking.

## CAD traps and safety
- Record initial documents/active reference before live work. Create separate test documents and unique output paths; never close/discard unrelated documents. Native KOMPAS crashes have occurred—see `STABILITY.md`; never automatically replay mutations after RPC loss.
- Object handles are process/document-local; topology handles expire on rebuild/update. Reacquire faces, edges and body targets after mutations. Finish managed sketch editing before document switching, saving, checkpoints or feature construction.
- All lengths are mm, angles degrees. Support-surface UV is **not** sketch UV: use `get_sketch_frame` (`ISketch.GetPoint3D`) or `create_closed_profile` with explicit axes; do not guess XZ/YZ signs. Explicit origins/axes must lie on the selected support.
- `extrude` defaults to a one-solid-body join. Intentional multi-body output requires `result_mode=auto/new_body`; cuts preserve body count unless the contract says otherwise. Inspect `failures` and `cleanup` on rejected results—cleanup of a new feature is not a universal transaction. Rejected extrusions keep their sketch unless `cleanup_sketch=true`; remove leftovers with `delete_feature` (reports every removed dependent).
- Feature `chooseType` selects bodies vs components; `ChooseBodies().ChooseBodiesType` selects new/automatic/manual/all bodies. They are different enums.
- Built-in camera placements are read-only. Permanent named model projections must survive camera changes. Native `ProjectionMatrix` is view-to-model placement; use `project_model_points`/`add_model_dimension` instead of guessing view coordinates. Coordinate-driven dimensions are not model-edge associated.
- `UpdatePlacement(True)` can return false despite a successful assembly move; verify origin/axes readback. Set an entire orientation with `InitByMatrix3D`, not successive `SetVector` calls.
- Checkpoints use SaveAs to a separate working copy, changing the active file association; recovery opens another document and does not snapshot external dependencies.
- Preserve staged exports and overwrite guards. Do not run exploratory `probe*.py` blindly; probes, `shots/`, `artifacts/` and local OpenCode config are ignored, not disposable user-free data.

## Detailed references
- `AGENT_WORKFLOW.md`: operational sequence and error recovery.
- `EXPLICIT_GEOMETRY.md`: profile schemas, coordinate conventions and result contracts.
- `COVERAGE.md` / `STABILITY.md`: verified paths, report locations and unresolved native failures; do not infer coverage from tool count.
