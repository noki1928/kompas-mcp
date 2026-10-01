"""Local KOMPAS-3D MCP server (stdio). Run with standard Windows Python."""
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP, Image
from pydantic import Field

from kompas import ComWorker

mcp = FastMCP("kompas", instructions=(
    "Windows KOMPAS-3D API5/API7. Coordinates/radii in millimeters; angles in degrees. "
    "Check status before editing. Use a NEW document unless editing was requested. "
    "References are document-local and become stale after closing. Never overwrite "
    "files without permission. Scripts execute with full OS privileges, not in a sandbox."))
worker = ComWorker()
Style = Annotated[int, Field(ge=1, le=9)]


@mcp.tool()
def status() -> dict:
    """Connect to KOMPAS and list documents, active document and script permission."""
    return worker.call("status")


@mcp.tool()
def create_document(kind: Literal["drawing", "fragment", "part", "assembly", "specification", "text", "technology_assembly"] = "fragment") -> dict:
    """Create and activate a NEW 2D drawing, fragment, or 3D part."""
    return worker.call("create_document", kind)


@mcp.tool()
def open_document(path: str) -> dict:
    """Open an existing local CAD document by its full path."""
    return worker.call("open_document", path)


@mcp.tool()
def save_document(path: str, overwrite: bool = False) -> dict:
    """Save active document as .cdw (drawing), .frw (fragment), or .m3d (part)."""
    return worker.call("save_document", path, overwrite)


@mcp.tool()
def line(x1: float, y1: float, x2: float, y2: float, style: Style = 1) -> dict:
    """Create a line segment. style=1 is the main solid line."""
    return worker.call("line", x1, y1, x2, y2, style)


@mcp.tool()
def circle(x: float, y: float, radius: float, style: Style = 1) -> dict:
    """Create a circle by center and positive radius (mm)."""
    return worker.call("circle", x, y, radius, style)


@mcp.tool()
def arc(x: float, y: float, radius: float, start_angle: float, end_angle: float,
        direction: Literal[-1, 1] = 1, style: Style = 1) -> dict:
    """Create circular arc; angles in degrees; direction=1 counterclockwise."""
    return worker.call("arc", x, y, radius, start_angle, end_angle, direction, style)


@mcp.tool()
def rectangle(x: float, y: float, width: float, height: float, style: Style = 1) -> dict:
    """Create rectangle from lower-left corner as four separate line segments."""
    return worker.call("rectangle", x, y, width, height, style)


@mcp.tool()
def polyline(points: list[list[float]], closed: bool = False, style: Style = 1) -> dict:
    """Connect points [[x,y], ...] as separate line segments, optionally closed."""
    return worker.call("polyline", points, closed, style)


@mcp.tool()
def text(x: float, y: float, text: str, height: float = 5, angle: float = 0) -> dict:
    """Place text at x,y; height in mm and angle in degrees."""
    return worker.call("text", x, y, text, height, angle)


@mcp.tool()
def set_layer(layer: Annotated[int, Field(ge=0)]) -> dict:
    """Set active 2D layer number using API5."""
    return worker.call("set_layer", layer)


@mcp.tool()
def delete_object(reference: Annotated[int, Field(gt=0)]) -> dict:
    """Delete a 2D object in the active document by its reference."""
    return worker.call("delete_object", reference)


@mcp.tool()
def export_dxf(path: str, overwrite: bool = False) -> dict:
    """Export active 2D document to DXF; existing files are protected by default."""
    return worker.call("export_dxf", path, overwrite)


@mcp.tool()
def screenshot() -> Image:
    """Return a PNG of KOMPAS window (not the whole desktop). Unminimize it first."""
    return Image(data=worker.call("screenshot"), format="png")


@mcp.tool()
def sketch3d(plane: Literal["XY", "XZ", "YZ"] = "XY",
             rectangles: list[list[float]] = [], circles: list[list[float]] = [],
             polygons: list[list[list[float]]] = [], name: str = "") -> dict:
    """Create CLOSED profiles in a new 3D sketch on an origin plane of active part.
    rectangles=[[x,y,width,height]], circles=[[x,y,radius]], polygons=[[[x,y],...]].
    Coordinates are local to sketch plane, mm. Returns document-local sketch_id.
    No offset planes, face selection, or interactive sketch edit is needed.
    """
    return worker.call("sketch3d", plane, rectangles, circles, polygons, name)


@mcp.tool()
def extrude(sketch_id: str, depth: float, reverse: bool = False, name: str = "",
            direction: list[float]|None=None, result_mode: Literal['join','auto','new_body']='join', expected:dict|None=None) -> dict:
    """Extrude a closed sketch into solid material. Positive depth in mm.
    direction is a world-space vector perpendicular to sketch; do not combine with reverse.
    Default join verifies ONE solid body. auto allows intentional multiple bodies.
    new_body explicitly creates separate body/bodies (native ksNewBody).
    expected accepts body_count, bounds_mm, volume_mm3 and tolerances. Failed result
    removes only the new feature and reports cleanup/readback, never retries direction.
    """
    return worker.call("extrusion3d", sketch_id, depth, False, reverse, name,direction,result_mode,expected)


@mcp.tool()
def cut_extrude(sketch_id: str, depth: float, reverse: bool = False, name: str = "",
                direction:list[float]|None=None,expected:dict|None=None,target_body_ids:list[str]|None=None) -> dict:
    """Remove material by extrusion of a closed sketch, strictly to depth in mm.
    direction is explicit world-space normal; cannot combine with reverse. Checks
    actual volume decrease and optional body_count/bounds_mm/volume_mm3 contract.
    Targets all top-part bodies unless fresh target_body_ids from get_model_properties
    are supplied. Body count is preserved unless explicitly set in expected.
    """
    return worker.call("extrusion3d", sketch_id, depth, True, reverse, name,direction,'auto',expected,False,False,target_body_ids)


@mcp.tool()
def model_info() -> dict:
    """Inspect active 3D part: sketches/extrusions, IDs, main body's solidity,
    bounding box [xmin,ymin,zmin,xmax,ymax,zmax] mm and volume mm^3.
    Reopened documents require fresh IDs from this tool. Not full assembly tree.
    """
    return worker.call("model_info")


@mcp.tool()
def fit_view3d() -> dict:
    """Rebuild active 3D part and fit model in the viewport before screenshot."""
    return worker.call("fit_view3d")


@mcp.tool()
def execute_python_script(code: str) -> dict:
    """UNSANDBOXED Python. Requires KOMPAS_ALLOW_SCRIPTS=1. Globals: kompas,
    app7, doc2d, doc3d. Set JSON-serializable `result`; print output is captured.
    Scripts may modify CAD and any OS files. Only execute trusted code.
    """
    return worker.call("execute_python_script", code)


from extended_tools import register
register(mcp, worker)

if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    finally:
        worker.close()
