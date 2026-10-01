"""Live MCP stdio test. Creates its OWN fragment; never edits an existing file."""
import asyncio
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / datetime.now().strftime("smoke-%Y%m%d-%H%M%S-%f")


async def main():
    OUT.mkdir(parents=True)
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")],
                                  env={**os.environ, "KOMPAS_ALLOW_SCRIPTS": "1"})
    report = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("MCP initialized; tools:", len(tools.tools))

            async def call(name, args=None, expect_error=False):
                result = await session.call_tool(name, args or {})
                error = bool(result.isError)
                details = [c.text for c in result.content if c.type == "text"]
                report.append({"tool": name, "is_error": error, "text": details})
                if error != expect_error:
                    raise AssertionError(f"{name}: {details}")
                print("PASS", name, "(expected error)" if expect_error else "")
                return result

            await call("status")
            created = await call("create_document", {"kind": "fragment"})
            docref = json.loads(created.content[0].text)["reference"]
            try:
                await call("rectangle", {"x": 0, "y": 0, "width": 100, "height": 50})
                await call("circle", {"x": 25, "y": 25, "radius": 10})
                await call("arc", {"x": 70, "y": 25, "radius": 10,
                                   "start_angle": 0, "end_angle": 180})
                await call("polyline", {"points": [[0, 60], [50, 80], [100, 60]]})
                await call("text", {"x": 0, "y": -10, "text": "MCP KOMPAS test"})
                await call("set_layer", {"layer": 0})
                line = await call("line", {"x1": 0, "y1": 90, "x2": 100, "y2": 90})
                ref = json.loads(line.content[0].text)["reference"]
                await call("delete_object", {"reference": ref})
                await call("circle", {"x": 0, "y": 0, "radius": -1}, expect_error=True)
                path = str(OUT / "test.frw")
                await call("save_document", {"path": path})
                await call("save_document", {"path": path}, expect_error=True)
                await call("export_dxf", {"path": str(OUT / "test.dxf")})
                image = await call("screenshot")
                data = next(c.data for c in image.content if c.type == "image")
                (OUT / "screenshot.png").write_bytes(base64.b64decode(data))
                await call("execute_python_script", {"code": "print('script works'); result = {'active_reference': int(app7.ActiveDocument.Reference), 'api5_reference': int(doc2d.reference)}"})
            finally:
                # Close ONLY the document made by this test, even if another is active.
                await call("execute_python_script", {"code": f"for i in range(app7.Documents.Count):\n    d=app7.Documents.Item(i)\n    if int(d.Reference)=={docref}:\n        d.Close(False)\n        break\nresult=True"})
            reopened = await call("open_document", {"path": path})
            reopened_ref = json.loads(reopened.content[0].text)["reference"]
            await call("execute_python_script", {"code": f"d=app7.ActiveDocument\nassert int(d.Reference)=={reopened_ref}\nd.Close(False)\nresult=True"})
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("All live MCP checks passed. Artifacts:", OUT)


if __name__ == "__main__":
    asyncio.run(main())
