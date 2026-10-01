# Architecture

## Layers

1. `server.py`: FastMCP stdio transport and original 20 tools.
2. `extended_tools.py`: 56 additional typed tools; errors normalized by `diagnostics.error_info`.
3. `kompas.py`: one `ComWorker` thread initialized as COM STA, message pumping and serialized requests. COM proxies never cross the worker boundary. `Kompas` composes mixins instead of replacing the working backend.
4. Native adapters: `cad3d.py` (basic modeling), `modeling.py`, `safe_modeling.py` (explicit frames and contracts), `drawing.py`, `assembly.py`, `visualization.py`, `documents.py`, `api_adapter.py`. `geometry.py` is pure geometry validation/transforms, without COM.
5. `registry.py`: process-local object handles, document ownership and topology generations.
6. `sdk_catalog.py` and `scripts/audit_sdk.py`: installed official TLB discovery. Audit snapshots are in `artifacts/sdk/`.

API5 attaches to KOMPAS, then obtains API7 through `ksGetApplication7`, keeping both APIs on the same application instance. API5 supplies proven constructive operations; API7 supplies document collections, drawing interfaces and assembly components. `CastTo` is needed when a collection returns only a base drawing/model object.

## Generic access

`describe_object` reads runtime ITypeInfo. `sdk_catalog` supplies declared signatures and `api_constants` exact installed enum values. `kompas_api_call` performs one public get/set/call/cast; no expression evaluation. COM results become handles, arrays become JSON arrays. `{object_id: ...}` arguments resolve on the STA; `{missing:true}` supplies an optional argument.

Calls and setters require `allow_mutation=true`. This is explicit intent, not a security sandbox. Lifecycle, raw IUnknown and known file-writing methods are denied; managed document/export tools protect existing output paths. The legacy Python tool remains opt-in through `KOMPAS_ALLOW_SCRIPTS=1`; tests run with it disabled. The denylist is not a guarantee that every native side effect is intercepted.

## Ownership and consistency

Handles are valid only within the server process and originating document. Closing a document drops its handles. Rebuilds and modeled mutations invalidate topology handles; model update stamps detect many manual changes. Neither persistent topology naming nor an application-wide edit lock is implemented. Do not use handles across server restarts or restored documents. Document native references and handles are different identifiers.

Most tools operate on the active document. Activate explicitly before mutation; reacquire geometry after rebuild. Semantic feature/sketch handles survive topology invalidation but cannot survive deletion/closure. Application-root document navigation infers ownership from runtime type/reference; descendants inherit scope. Prefer explicit document roots for ambiguous native interfaces. Managed sketch edit contexts expire at EndEdit, and conflicting lifecycle/modeling operations are blocked while editing.

## Errors, logs, recovery

Extended errors contain `success=false`, exception type, message, API method, HRESULT/hex, COM excepinfo, argument error and recovery suggestions. Original tools retain their prior MCP exception behavior. Native boolean return values can be misleading: standard-view activation checks current state; assembly placement reads back origin/axes and reports false-return warnings. A lost COM session invalidates all handles, never replays mutations and allows safe status reconnection. Shutdown is idempotent. See `STABILITY.md` for regression evidence and remaining boundaries.

`artifacts/actions.jsonl` logs actions, arguments, results and duration. Override `KOMPAS_LOG_PATH`; `KOMPAS_DEBUG=1` enables script text. Individual records are bounded, but the log file is not rotated automatically. Paths and geometry can be sensitive.

Checkpoint SaveAs switches the current document to a new working file, copies a snapshot, and leaves the original untouched. Restore opens a new recovered copy. This is not Undo, not an atomic transaction, and does not snapshot all external assembly dependencies. Batches stop at first error without rolling back prior actions.

## Coordinates and output

Lengths mm; angles degrees; area mm²; volume mm³; native mass grams using stored density. Sketch points are plane-local; 2D annotations are view-local; view placement is sheet-local; component origins are parent-local. Native by-reference getters often return `[status, values...]`.

Native raster export renders a selected drawing sheet independently of viewport size; fragments use work-area export. PDF uses installed `Pdf2d.dll`; neutral formats use native additional-format parameters. These exporters validate a private staging file before publishing it, preserving older output on converter failure. PrintWindow captures the application/viewport, not desktop pixels. Validate file size and visually inspect exports; a nonempty file is not manufacturing approval.
