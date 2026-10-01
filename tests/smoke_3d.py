"""Live 3D MCP test: volume/bounds, cut, reverse, persistence, screenshots."""
import asyncio
import base64
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / datetime.now().strftime("3d-%Y%m%d-%H%M%S-%f")


async def main():
    OUT.mkdir(parents=True)
    report = []
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")],
                                  env={**os.environ, "KOMPAS_ALLOW_SCRIPTS": "1"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Tools:", len((await session.list_tools()).tools))

            async def call(name, args=None, error=False):
                r = await session.call_tool(name, args or {})
                text = [c.text for c in r.content if c.type == "text"]
                report.append({"tool": name, "is_error": bool(r.isError), "text": text})
                if bool(r.isError) != error:
                    raise AssertionError(f"{name}: {text}")
                print("PASS", name, "(expected error)" if error else "")
                return json.loads(text[0]) if text and not error else r

            async def close(ref):
                await call("execute_python_script", {"code": f"for i in range(app7.Documents.Count):\n    d=app7.Documents.Item(i)\n    if int(d.Reference)=={ref}:\n        d.Close(False)\n        break\nresult=True"})

            await call("status")
            created = await call("create_document", {"kind": "part"})
            try:
                sketch = await call("sketch3d", {"rectangles": [[0, 0, 100, 50]], "name": "Base"})
                await call("extrude", {"sketch_id": sketch["sketch_id"], "depth": 12})
                info = await call("model_info")
                body = info["main_body"]
                assert body["solid"]
                assert math.isclose(body["volume_mm3"], 60000, rel_tol=1e-7), body
                assert all(math.isclose(a, b, abs_tol=1e-6) for a, b in
                           zip(body["bounds_mm"], [0, 0, 0, 100, 50, 12])), body
                hole = await call("sketch3d", {"circles": [[25, 25, 5]], "name": "Hole"})
                await call("cut_extrude", {"sketch_id": hole["sketch_id"], "depth": 12})
                info = await call("model_info")
                volume = 60000-math.pi*5**2*12
                assert math.isclose(info["main_body"]["volume_mm3"], volume, rel_tol=1e-7), info
                assert len(info["features"]) == 4, info
                outside = await call("sketch3d", {"circles": [[1000, 1000, 2]]})
                await call("cut_extrude", {"sketch_id": outside["sketch_id"], "depth": 12}, error=True)
                unchanged = await call("model_info")
                assert math.isclose(unchanged["main_body"]["volume_mm3"], volume, rel_tol=1e-7)
                await call("extrude", {"sketch_id": "invalid", "depth": 10}, error=True)
                await call("sketch3d", {"circles": [[0, 0, -1]]}, error=True)
                await call("fit_view3d")
                await call("save_document", {"path": str(OUT / "plate.m3d")})
                await call("execute_python_script", {"code": "import ctypes, pythoncom\nctypes.windll.user32.ShowWindow(int(app7.MainWindowHandle), 9)\npythoncom.PumpWaitingMessages()\nresult=True"})
                image = await session.call_tool("screenshot")
                assert not image.isError, image
                data = next(c.data for c in image.content if c.type == "image")
                (OUT / "plate.png").write_bytes(base64.b64decode(data))
            finally:
                await close(created["reference"])
            opened = await call("open_document", {"path": str(OUT / "plate.m3d")})
            try:
                info = await call("model_info")
                assert math.isclose(info["main_body"]["volume_mm3"], volume, rel_tol=1e-7)
                await call("extrude", {"sketch_id": sketch["sketch_id"], "depth": 1}, error=True)
            finally:
                await close(opened["reference"])

            # Reverse extrusion: full depth on the other side of XY plane.
            created = await call("create_document", {"kind": "part"})
            try:
                sketch = await call("sketch3d", {"circles": [[0, 0, 10]]})
                await call("extrude", {"sketch_id": sketch["sketch_id"], "depth": 20, "reverse": True})
                info = await call("model_info")
                assert math.isclose(info["main_body"]["volume_mm3"], math.pi*100*20, rel_tol=1e-7)
                assert math.isclose(info["main_body"]["bounds_mm"][2], -20, abs_tol=1e-6), info
                assert math.isclose(info["main_body"]["bounds_mm"][5], 0, abs_tol=1e-6), info
                hole = await call("sketch3d", {"circles": [[0, 0, 2]]})
                await call("cut_extrude", {"sketch_id": hole["sketch_id"], "depth": 20, "reverse": True})
                cut_info = await call("model_info")
                assert math.isclose(cut_info["main_body"]["volume_mm3"], math.pi*96*20, rel_tol=1e-7)
                await call("save_document", {"path": str(OUT / "reverse-cylinder.m3d")})
            finally:
                await close(created["reference"])

            # Both remaining origin planes and polygon profile.
            for plane in ("XZ", "YZ"):
                created = await call("create_document", {"kind": "part"})
                try:
                    sketch = await call("sketch3d", {"plane": plane, "polygons": [[[0, 0], [20, 0], [0, 20]]]})
                    await call("extrude", {"sketch_id": sketch["sketch_id"], "depth": 10})
                    info = await call("model_info")
                    assert math.isclose(info["main_body"]["volume_mm3"], 2000, rel_tol=1e-7), info
                finally:
                    await close(created["reference"])
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("3D MCP checks passed. Artifacts:", OUT)


if __name__ == "__main__":
    asyncio.run(main())
