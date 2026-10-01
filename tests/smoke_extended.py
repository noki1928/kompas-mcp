"""MCP-only end-to-end and native coverage checks. No execute_python_script.

Always creates its own documents/output paths; does not modify initial documents.
"""
import asyncio
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/datetime.now().strftime('extended-%Y%m%d-%H%M%S-%f')


async def main():
    OUT.mkdir(parents=True)
    report=[]; owned=set(); initial_active=None; initial=set()
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'server.py')],
                                env={**os.environ,'KOMPAS_ALLOW_SCRIPTS':'0'})
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tools=(await session.list_tools()).tools
            print('TOOLS',len(tools))

            async def call(name,args=None,expect_error=False):
                r=await session.call_tool(name,args or {})
                text=[c.text for c in r.content if c.type=='text']
                data=r.structuredContent or (json.loads(text[0]) if text else {})
                failure=bool(r.isError) or data.get('success') is False
                report.append({'tool':name,'arguments':args,'result':data,'is_error':failure})
                (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                if failure!=expect_error:
                    raise AssertionError(f'{name}: {data}')
                print('PASS',name,'expected error' if expect_error else '')
                return data

            async def create(kind):
                r=await call('create_document',{'kind':kind}); owned.add(r['reference']); return r

            try:
                state=await call('get_kompas_state')
                initial={d['reference'] for d in state['documents']}
                initial_active=state['active']['reference'] if state['active'] else None
                assert not state['scripts_enabled']
                await call('show_application')
                sdk=await call('sdk_catalog',{'interface':'IChamferDefinition','library':'kAPI3D5COM.tlb'})
                assert sdk['total']>=1
                await call('api_constants',{'names':['o3d_chamfer','o3d_bossRotated','format_STEP']})
                await call('kompas_api_call',{'target':'api7','operation':'get','member':'Documents'})
                await call('kompas_api_call',{'target':'api7','operation':'call','member':'Quit','allow_mutation':True},True)
                await call('kompas_api_call',{'target':'api7','operation':'get','member':'__dict__'},True)

                # Parametric plate, through hole, chamfer, editing, geometry, exports.
                part=await create('part')
                s=await call('sketch3d',{'rectangles':[[0,0,50,30]]})
                base=await call('extrude',{'sketch_id':s['sketch_id'],'depth':20})
                hole=await call('sketch3d',{'circles':[[25,15,5]]})
                await call('cut_extrude',{'sketch_id':hole['sketch_id'],'depth':20})
                props=await call('get_model_properties')
                assert math.isclose(props['volume_mm3'],30000-math.pi*25*20,rel_tol=1e-7),props
                faces=await call('find_faces',{'surface_type':'cylinder','radius':5})
                assert faces['total']>=1,faces
                edges=await call('find_edges',{'curve_type':'line'})
                assert edges['total']>=1,edges
                candidate=next(e for e in edges['edges'] if math.isclose(e['length_mm'],50,abs_tol=1e-6))
                chamfer=await call('edge_operation',{'edge_ids':[candidate['object_id']],'operation':'chamfer','size':1})
                await call('kompas_api_call',{'target':candidate['object_id'],'operation':'get','member':'name'},True)
                feature=await call('get_feature_parameters',{'feature_id':base['feature_id']})
                assert feature['type']==25
                await call('set_feature_parameters',{'feature_id':base['feature_id'],'parameters':{'depth':22}})
                await call('set_feature_parameters',{'feature_id':base['feature_id'],'parameters':{'depth':20}})
                tree=await call('get_model_tree')
                assert any(n['type']==33 for n in tree['nodes'])
                await call('rebuild_model')
                await call('validate_document')
                await call('set_standard_view',{'view':'isometric'})
                await call('capture_views',{'directory':str(OUT/'plate-views'),'views':['isometric','front','top','right']})
                await call('save_document',{'path':str(OUT/'plate.m3d')})
                await call('export_model',{'path':str(OUT/'plate.step'),'format':'step'})
                await call('export_model',{'path':str(OUT/'plate.stl'),'format':'stl'})
                checkpoint=await call('create_checkpoint')
                recovered=await call('restore_checkpoint',{'checkpoint_id':checkpoint['checkpoint_id']})
                owned.add(recovered['document']['reference'])
                await call('get_model_properties')
                await call('activate_document',{'document_reference':part['reference']})

                # True associative drawing, real dimension, native raster/PDF, reading.
                drawing=await create('drawing')
                await call('drawing_sheet',{'format':'A4','portrait':True,'stamp':{'1':'MCP test plate','2':'MCP.001','6':'1:1'}})
                front=await call('create_model_view',{'model_path':str(OUT/'plate.m3d'),'view':'front','x':65,'y':185,'scale':1})
                assert front['object_count']>0,front
                await call('create_model_view',{'model_path':str(OUT/'plate.m3d'),'view':'top','x':65,'y':135,'scale':1})
                await call('create_model_view',{'model_path':str(OUT/'plate.m3d'),'view':'right','x':145,'y':185,'scale':1})
                await call('add_dimension',{'view_id':front['view_id'],'points':[[0,0],[50,0]],'position':[25,-12]})
                structure=await call('get_document_structure')
                assert len(structure['views'])>=4
                assert any('X1' in o['properties'] for v in structure['views'] for o in v['objects']),structure
                dimensions=await call('find_drawing_objects',{'collection':'LineDimensions'})
                assert dimensions['total']==1 and dimensions['objects'][0]['properties']['NominalValue']==50
                await call('save_document',{'path':str(OUT/'plate.cdw')})
                await call('export_drawing_image',{'path':str(OUT/'plate.png'),'dpi':300})
                await call('export_drawing_pdf',{'path':str(OUT/'plate.pdf')})
                await call('capture_drawing_tiles',{'directory':str(OUT/'tiles'),'dpi':150})

                # Rotation with explicit axis, groove profile via cut-revolve.
                shaft=await create('part')
                sketch=await call('create_sketch',{'plane':'XY','name':'Shaft profile'})
                await call('begin_sketch_edit',{'sketch_id':sketch['sketch_id']})
                await call('create_sketch_entities',{'entities':[{'kind':'rectangle','x':0,'y':0,'width':15,'height':120},
                    {'kind':'line','x1':0,'y1':-10,'x2':0,'y2':130,'style':3}]})
                await call('end_sketch_edit')
                await call('revolve',{'sketch_id':sketch['sketch_id']})
                props=await call('get_model_properties')
                assert math.isclose(props['volume_mm3'],math.pi*225*120,rel_tol=1e-7),props
                await call('set_standard_view',{'view':'isometric'})
                await call('capture_viewport',{'path':str(OUT/'shaft.png')})
                await call('save_document',{'path':str(OUT/'shaft.m3d')})

                # Assembly contains linked copies; never save source component files.
                assembly=await create('assembly')
                a=await call('add_component',{'path':str(OUT/'plate.m3d'),'position':[0,0,0]})
                b=await call('add_component',{'path':str(OUT/'shaft.m3d'),'position':[80,0,0]})
                await call('set_component_placement',{'component_id':b['component_id'],'position':[100,0,0]})
                tree=await call('get_assembly_tree')
                assert len(tree['tree']['children'])==2,tree
                assert tree['tree']['children'][1]['origin_mm'][1:]==[100,0,0],tree
                await call('rebuild_model')
                await call('set_standard_view',{'view':'isometric'})
                await call('capture_viewport',{'path':str(OUT/'assembly.png')})
                await call('save_document',{'path':str(OUT/'fixture.a3d')})
            finally:
                # Include documents opened for native view lookup, but NEVER initial docs.
                docs=await call('list_documents')
                for doc in docs['documents']:
                    if doc['reference'] not in initial and (doc['reference'] in owned or str(OUT).lower() in doc['path'].lower()):
                        await call('close_document',{'document_reference':doc['reference'],'discard_changes':True})
                if initial_active is not None:
                    await call('activate_document',{'document_reference':initial_active})
    print('ALL EXTENDED CHECKS PASSED:',OUT)
    (OUT/'passed.json').write_text(json.dumps({'passed':True,'calls':len(report),'tools_tested':sorted({r['tool'] for r in report})}),encoding='utf-8')


if __name__=='__main__':
    asyncio.run(main())
