"""Live regression for previously untested branches and failure recovery.

MCP only. No application termination and no changes to initial documents/files.
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
OUT=ROOT/'artifacts'/datetime.now().strftime('stability-%Y%m%d-%H%M%S-%f')


async def main():
    OUT.mkdir(parents=True)
    report=[]; owned=set(); initial=None
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'server.py')],
                                env={**os.environ,'KOMPAS_ALLOW_SCRIPTS':'0'})
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            catalog=(await session.list_tools()).tools
            schema=next(t for t in catalog if t.name=='kompas_api_call').inputSchema
            assert 'type' not in schema['properties']['value'],schema

            async def call(name,error=False,**args):
                r=await session.call_tool(name,args)
                texts=[c.text for c in r.content if c.type=='text']
                if r.structuredContent:
                    data=r.structuredContent
                elif texts:
                    try: data=json.loads(texts[0])
                    except json.JSONDecodeError: data={'message':texts[0]}
                else:
                    data={'images':len(r.content)}
                failure=bool(r.isError) or data.get('success') is False
                report.append({'tool':name,'arguments':args,'result':data,'expected_error':error,'passed':failure==error})
                (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                assert failure==error,(name,data)
                print('PASS',name,'expected error' if error else '',flush=True)
                return data

            async def create(kind):
                r=await call('create_document',kind=kind); owned.add(r['reference']); return r

            async def profile(entities,plane='XY'):
                s=await call('create_sketch',plane=plane)
                await call('begin_sketch_edit',sketch_id=s['sketch_id'])
                try:
                    await call('create_sketch_entities',entities=entities)
                finally:
                    await call('end_sketch_edit')
                return s['sketch_id']

            try:
                initial=await call('status')
                await call('show_application')
                await call('execute_python_script',error=True,code='result=1')
                fragment=await create('fragment')
                line=await call('line',x1=0,y1=0,x2=30,y2=0)
                await call('rectangle',x=0,y=10,width=30,height=20)
                await call('circle',x=50,y=25,radius=8)
                await call('arc',x=70,y=25,radius=8,start_angle=0,end_angle=90)
                await call('polyline',points=[[0,40],[20,45],[30,40]])
                await call('text',x=0,y=55,text='Stability test',height=5)
                await call('set_layer',layer=0)
                await call('delete_object',reference=line['reference'])
                await call('delete_object',error=True,reference=line['reference'])
                await call('fit_view')
                await call('screenshot')
                await call('save_document',path=str(OUT/'primitives.frw'))
                await call('export_dxf',path=str(OUT/'primitives.dxf'))
                await call('export_drawing_image',path=str(OUT/'fragment.jpg'),dpi=100)
                await call('save_document',error=True,path=str(OUT/'primitives.frw'))
                await call('save_current_document',error=True)
                await call('save_current_document',confirm_overwrite=True)
                await call('close_document',document_reference=fragment['reference'])
                reopened=await call('open_document',path=str(OUT/'primitives.frw')); owned.add(reopened['reference'])
                await call('get_document_structure')
                await call('close_document',document_reference=reopened['reference'])

                # Fillet and parameter validation on an independent solid.
                part=await create('part')
                s=await call('sketch3d',rectangles=[[0,0,40,30]])
                boss=await call('extrude',sketch_id=s['sketch_id'],depth=20)
                await call('fit_view3d')
                await call('model_info')
                edge=(await call('find_edges',curve_type='line'))['edges'][0]
                fillet=await call('edge_operation',edge_ids=[edge['object_id']],operation='fillet',size=1)
                await call('get_feature_parameters',feature_id=fillet['feature_id'])
                await call('set_feature_parameters',feature_id=fillet['feature_id'],parameters={'radius':2})
                before=await call('get_feature_parameters',feature_id=boss['feature_id'])
                await call('set_feature_parameters',error=True,feature_id=boss['feature_id'],parameters={'reverse':True,'depth':-1})
                after=await call('get_feature_parameters',feature_id=boss['feature_id'])
                assert before['parameters']==after['parameters']
                await call('set_camera',origin=[0,0,0],x_axis=[1,0,0],y_axis=[0,1,0],scale=1)
                await call('set_camera',error=True,origin=[0,0,0],x_axis=[1,0,0],y_axis=[1,0,0])
                await call('set_standard_view',view='isometric')
                await call('export_model',path=str(OUT/'fillet.igs'),format='iges')
                await call('export_model',path=str(OUT/'fillet.x_t'),format='parasolid')
                faces=await call('find_faces',surface_type='plane',largest_first=True)
                sketch=await call('create_sketch',plane_object_id=faces['faces'][0]['object_id'])
                edit=await call('begin_sketch_edit',sketch_id=sketch['sketch_id'])
                await call('create_document',error=True,kind='part')
                await call('close_document',error=True,document_reference=part['reference'],discard_changes=True)
                await call('save_document',error=True,path=str(OUT/'editing.m3d'))
                partial=await call('create_sketch_entities',error=True,entities=[{'kind':'circle','x':5,'y':5,'radius':2},{'kind':'unknown'}])
                assert len(partial['created_references'])==1
                await call('end_sketch_edit')
                await call('kompas_api_call',error=True,target=edit['edit_context']['object_id'],member='reference')
                await call('save_document',path=str(OUT/'fillet.m3d'))
                await call('describe_object',target='api7')
                await call('get_object_properties',target='api7',members=['Visible','NotARealProperty'])
                d=await call('kompas_api_call',target='api7',member='ActiveDocument')
                assert d['result']['document_reference']==part['reference'],d
                await call('kompas_api_call',target='api7',operation='set',member='Visible',value=True,allow_mutation=True)
                await call('api_batch',calls=[{'target':'api7','operation':'get','member':'Visible'}])
                await call('release_objects',object_ids=[d['result']['object_id']])
                await call('kompas_api_call',error=True,target=d['result']['object_id'],member='Name')

                # Rotation edit must preserve angle when only reverse is supplied.
                rotation=await create('part')
                axis={'kind':'line','x1':0,'y1':-10,'x2':0,'y2':130,'style':3}
                sketch=await profile([{'kind':'rectangle','x':0,'y':0,'width':15,'height':120},axis])
                rotated=await call('revolve',sketch_id=sketch,angle=120)
                await call('set_feature_parameters',feature_id=rotated['feature_id'],parameters={'reverse':True})
                params=await call('get_feature_parameters',feature_id=rotated['feature_id'])
                assert math.isclose(params['parameters']['reverse_side'][1],120),params
                await call('set_feature_parameters',feature_id=rotated['feature_id'],parameters={'angle':360,'reverse':False})
                volume=(await call('get_model_properties'))['volume_mm3']
                groove=await profile([{'kind':'rectangle','x':10,'y':50,'width':6,'height':10},axis])
                await call('revolve',sketch_id=groove,cut=True)
                after=(await call('get_model_properties'))['volume_mm3']
                assert math.isclose(volume-after,math.pi*(225-100)*10,rel_tol=1e-6),(volume,after)
                await call('save_document',path=str(OUT/'rotation.m3d'))

                drawing=await create('drawing')
                await call('drawing_sheet',format='A4',portrait=True)
                before=set(d['reference'] for d in (await call('list_documents'))['documents'])
                view=await call('create_model_view',model_path=str(OUT/'fillet.m3d'),view='front',x=60,y=160)
                after=set(d['reference'] for d in (await call('list_documents'))['documents'])
                assert before==after,'Projection lookup leaked a document'
                await call('set_drawing_view',view_id=view['view_id'],x=65,y=165,scale=1,active=True)
                for args,expected in [({'points':[[0,0],[40,0]],'position':[20,-10]},40),
                                      ({'points':[[0,0],[0,30]],'position':[-10,15],'orientation':'vertical'},30),
                                      ({'points':[[0,0],[3,4]],'position':[8,8],'orientation':'parallel'},5),
                                      ({'kind':'diameter','center':[20,15],'radius':5},10),
                                      ({'kind':'radius','center':[20,15],'radius':5},5)]:
                    result=await call('add_dimension',view_id=view['view_id'],**args)
                    assert math.isclose(result['nominal_value'],expected),result
                await call('save_document',path=str(OUT/'dimensions.cdw'))
                sheet=await call('drawing_sheet')
                docs=await call('status'); assert not docs['active']['changed'],'Read-only sheet changed drawing'
                await call('export_drawing_pdf',path=str(OUT/'dimensions.pdf'))
                await call('export_drawing_image',path=str(OUT/'dimensions.png'),dpi=150)
                await call('get_document_structure')

                assembly=await create('assembly')
                component=await call('add_component',path=str(OUT/'fillet.m3d'))
                await call('set_component_placement',component_id=component['component_id'],position=[80,0,0],
                           x_axis=[0,1,0],y_axis=[-1,0,0],fixed=True)
                await call('selection',operation='select',object_ids=[component['component_id']])
                selected=await call('selection'); assert selected['selected'] is not None,selected
                await call('selection',operation='clear')
                tree=await call('get_assembly_tree')
                axes=tree['tree']['children'][0]['axes']
                assert axes['x'][1:]==[0,1,0] and axes['y'][1:]==[-1,0,0],axes
                await call('save_document',path=str(OUT/'rotated-component.a3d'))
                await call('rebuild_model')
                await call('validate_document')
                await call('close_document',document_reference=assembly['reference'],discard_changes=True)
                reopened=await call('open_document',path=str(OUT/'rotated-component.a3d')); owned.add(reopened['reference'])
                tree=await call('get_assembly_tree')
                assert tree['tree']['children'][0]['axes']==axes,tree
                await call('close_document',document_reference=reopened['reference'])
                for kind in ('specification','text','technology_assembly'):
                    doc=await create(kind)
                    await call('close_document',document_reference=doc['reference'],discard_changes=True)
            finally:
                # A native crash may make cleanup impossible. Record it without hiding the primary failure.
                try:
                    docs=await call('list_documents')
                    for doc in docs['documents']:
                        if doc['reference'] in owned:
                            await call('close_document',document_reference=doc['reference'],discard_changes=True)
                    if initial and initial['active']:
                        await call('activate_document',document_reference=initial['active']['reference'])
                except Exception as exc:
                    (OUT/'cleanup-error.txt').write_text(str(exc),encoding='utf-8')
    print('ALL STABILITY CHECKS PASSED',OUT,flush=True)
    (OUT/'passed.json').write_text(json.dumps({'passed':True,'calls':len(report),'tools_tested':sorted({r['tool'] for r in report})}),encoding='utf-8')


if __name__=='__main__':
    asyncio.run(main())
