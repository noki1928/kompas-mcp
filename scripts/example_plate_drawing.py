"""MCP-only associative drawing for the earlier 100x60x30 model.

Creates a new drawing; source model is never saved/edited. No script-execution tool.
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'artifacts'/'plate-from-drawing-100x60x30.m3d'
OUT=ROOT/'artifacts'/datetime.now().strftime('original-plate-drawing-%Y%m%d-%H%M%S-%f')


async def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    OUT.mkdir(parents=True)
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'server.py')],
                                env={**os.environ,'KOMPAS_ALLOW_SCRIPTS':'0'})
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            report=[]
            async def call(name,**args):
                result=await session.call_tool(name,args)
                data=result.structuredContent or json.loads(next(c.text for c in result.content if c.type=='text'))
                report.append({'tool':name,'arguments':args,'result':data})
                (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                if result.isError or data.get('success') is False:
                    raise RuntimeError(f'{name}: {data}')
                return data
            initial=await call('get_kompas_state')
            drawing=await call('create_document',kind='drawing')
            try:
                await call('drawing_sheet',format='A3',portrait=False,stamp={'1':'Plate 100x60x30','2':'MCP.PLATE.001','6':'1:1'})
                front=await call('create_model_view',model_path=str(SOURCE),view='front',x=80,y=180,scale=1)
                await call('create_model_view',model_path=str(SOURCE),view='top',x=80,y=100,scale=1)
                right=await call('create_model_view',model_path=str(SOURCE),view='right',x=260,y=180,scale=1)
                for points,position,orientation in [([[0,0],[100,0]],[50,-15],'horizontal'),
                    ([[0,0],[0,60]],[-18,30],'vertical'),
                    ([[58,14],[90,14]],[74,-30],'horizontal'),
                    ([[0,0],[20,0]],[10,-45],'horizontal'),
                    ([[20,14],[20,46]],[40,30],'vertical')]:
                    dimension=await call('add_dimension',view_id=front['view_id'],points=points,position=position,orientation=orientation)
                    expected=abs(points[1][1]-points[0][1]) if orientation=='vertical' else abs(points[1][0]-points[0][0])
                    assert dimension['nominal_value']==expected,dimension
                dimension=await call('add_dimension',kind='diameter',view_id=front['view_id'],center=[20,14],radius=9,angle=135)
                assert dimension['nominal_value']==18,dimension
                dimension=await call('add_dimension',view_id=right['view_id'],points=[[-30,0],[0,0]],position=[-15,-15])
                assert dimension['nominal_value']==30,dimension
                structure=await call('get_document_structure')
                assert structure['objects_returned']>0
                await call('save_document',path=str(OUT/'plate-100x60x30.cdw'))
                await call('export_drawing_image',path=str(OUT/'plate-100x60x30.png'),dpi=300)
                await call('export_drawing_pdf',path=str(OUT/'plate-100x60x30.pdf'))
            finally:
                await call('close_document',document_reference=drawing['reference'],discard_changes=True)
                if initial['active']:
                    await call('activate_document',document_reference=initial['active']['reference'])
    print(OUT)


if __name__=='__main__':
    asyncio.run(main())
