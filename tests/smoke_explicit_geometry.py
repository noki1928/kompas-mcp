"""MCP-only regression: explicit coordinates, bracket recipe, contracts, views."""
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
OUT=ROOT/'artifacts'/datetime.now().strftime('explicit-%Y%m%d-%H%M%S-%f')


def rectangle(x=0,y=0,w=10,h=5):
    p=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]]
    return [{'kind':'line','start':a,'end':b} for a,b in zip(p,p[1:]+p[:1])]


async def main():
    OUT.mkdir(parents=True); report=[]; owned=set(); initial=None
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'server.py')],env={**os.environ,'KOMPAS_ALLOW_SCRIPTS':'0'})
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            async def call(tool,error=False,**args):
                r=await session.call_tool(tool,args)
                if r.structuredContent: data=r.structuredContent
                else:
                    texts=[c.text for c in r.content if c.type=='text']
                    try: data=json.loads(texts[0])
                    except (json.JSONDecodeError,IndexError): data={'message':texts[0] if texts else ''}
                failed=r.isError or data.get('success') is False
                report.append({'tool':tool,'arguments':args,'result':data,'expected_error':error,'passed':bool(failed)==error})
                (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                assert bool(failed)==error,(tool,data)
                print('PASS',tool,'expected error' if error else '',flush=True)
                return data
            async def create(kind):
                d=await call('create_document',kind=kind); owned.add(d['reference']); return d
            async def profile(contours,plane='XY',x_axis=None,y_axis=None):
                args={'contours':contours,'plane':plane}
                if x_axis is not None: args.update(origin=[0,0,0],x_axis=x_axis,y_axis=y_axis)
                return (await call('create_closed_profile',**args))['sketch_id']
            try:
                initial=await call('status')
                # Explicit sketches must report native coordinates, not support UV.
                doc=await create('part')
                for plane in ('XY','XZ','YZ'):
                    s=await call('create_sketch',plane=plane)
                    f=await call('get_sketch_frame',sketch_id=s['sketch_id'])
                    p=await call('transform_sketch_points',sketch_id=s['sketch_id'],points=[[5,7]])
                    back=await call('transform_sketch_points',sketch_id=s['sketch_id'],points=p['points'],to='sketch')
                    assert all(math.isclose(a,b,abs_tol=1e-7) for a,b in zip(back['points'][0],[5,7]))
                    off=[f['origin_mm'][i]+f['normal'][i] for i in range(3)]
                    await call('transform_sketch_points',error=True,sketch_id=s['sketch_id'],points=[off],to='sketch')
                base=await profile([rectangle(0,0,20,20)])
                await call('extrude',sketch_id=base,depth=10,direction=[0,0,1],expected={'bounds_mm':[0,0,0,20,20,10],'volume_mm3':4000})
                before=await call('check_model_contract',expected={'body_count':1,'volume_mm3':4000})
                outside=await profile([rectangle(50,50,10,10)])
                rejected=await call('extrude',error=True,sketch_id=outside,depth=10,direction=[0,0,1])
                assert rejected['cleanup']['success'] and rejected['cleanup']['metrics_restored'],rejected
                await call('check_model_contract',expected={'body_count':1,'volume_mm3':4000})
                mismatch=await call('extrude',error=True,sketch_id=base,depth=20,expected={'volume_mm3':999})
                assert mismatch['cleanup']['success'],mismatch
                await call('check_model_contract',expected={'volume_mm3':4000})
                await call('cut_through_all',error=True,sketch_id=outside,direction=[0,0,1])
                await call('check_model_contract',expected={'volume_mm3':4000})
                await call('extrude',error=True,sketch_id=base,depth=10,direction=[1,0,0])
                await call('create_closed_profile',error=True,contours=[rectangle()[:-1]])
                # Force editing failure, verify only new sketch is removed.
                await call('create_closed_profile',error=True,contours=[rectangle()],plane='XY',origin=[0,0,1],x_axis=[1,0,0],y_axis=[0,1,0])
                await call('check_model_contract',expected={'volume_mm3':4000})
                await call('extrude',sketch_id=outside,depth=10,direction=[0,0,1],result_mode='new_body',expected={'body_count':2,'volume_mm3':5000})
                targeted=await profile([[{'kind':'circle','center':c,'radius':2}] for c in ([10,10],[55,55])])
                props=await call('get_model_properties')
                target=next(b['object_id'] for b in props['bodies'] if b['bounds_mm'][0]>40)
                await call('cut_through_all',sketch_id=targeted,direction=[0,0,1],target_body_ids=[target],expected={'body_count':2,'volume_mm3':5000-40*math.pi})
                await call('extrude',sketch_id=base,depth=10,direction=[0,0,-1],result_mode='auto',expected={'body_count':2,'volume_mm3':9000-40*math.pi})
                bilateral=await profile([[{'kind':'circle','center':[10,10],'radius':2}]])
                await call('cut_through_all',sketch_id=bilateral,direction=[0,0,1],both_sides=True,expected={'body_count':2,'volume_mm3':9000-120*math.pi})
                await call('close_document',document_reference=doc['reference'],discard_changes=True)

                # Recreate the supplied bracket, no sign guesses or repair operations.
                bracket=await create('part')
                s=await profile([rectangle(0,0,120,80)])
                await call('extrude',sketch_id=s,depth=35,direction=[0,0,1],expected={'volume_mm3':336000})
                ears=[]
                for c in (32.5,87.5):
                    ears.append([{'kind':'line','start':[c-20,35],'end':[c+20,35]},
                                 {'kind':'line','start':[c+20,35],'end':[c+20,50]},
                                 {'kind':'arc','center':[c,50],'radius':20,'start_angle':0,'end_angle':180},
                                 {'kind':'line','start':[c-20,50],'end':[c-20,35]}])
                s=await profile(ears,'XZ',[1,0,0],[0,0,1])
                ear_area=2*(40*15+math.pi*20**2/2)
                await call('extrude',sketch_id=s,depth=80,direction=[0,1,0],expected={'volume_mm3':336000+ear_area*80,'bounds_mm':[0,0,0,120,80,70]})
                s=await profile([rectangle(20,35,40,40)],'YZ',[0,1,0],[0,0,1])
                await call('cut_through_all',sketch_id=s,direction=[1,0,0],expected={'body_count':1,'volume_mm3':336000+ear_area*40})
                s=await profile([rectangle(45,0,30,20)],'XZ',[1,0,0],[0,0,1])
                await call('cut_through_all',sketch_id=s,direction=[0,1,0])
                s=await profile([rectangle(10,32.5,25,15),rectangle(85,32.5,25,15),[{'kind':'circle','center':[60,40],'radius':12.5}]])
                await call('cut_through_all',sketch_id=s,direction=[0,0,1])
                s=await profile([[{'kind':'circle','center':[c,50],'radius':10}] for c in (32.5,87.5)],'XZ',[1,0,0],[0,0,1])
                await call('cut_through_all',sketch_id=s,direction=[0,1,0])
                volume=336000+ear_area*40-30*80*20-2*25*15*35-math.pi*12.5**2*15-2*math.pi*10**2*40
                await call('check_model_contract',expected={'body_count':1,'bounds_mm':[0,0,0,120,80,70],'volume_mm3':volume})
                await call('create_model_projection',name='Bracket Front',origin=[0,0,0],x_axis=[1,0,0],y_axis=[0,0,1])
                await call('create_model_projection',error=True,name='Bracket Front',origin=[0,0,0],x_axis=[1,0,0],y_axis=[0,0,1])
                await call('set_camera',origin=[0,0,0],x_axis=[1,0,0],y_axis=[0,1,0])
                await call('set_camera',origin=[0,0,0],x_axis=[0,1,0],y_axis=[0,0,1])
                await call('save_document',path=str(OUT/'bracket.m3d'))

                drawing=await create('drawing')
                await call('drawing_sheet',format='A3',portrait=False,stamp={'1':'Кронштейн — проверка координат','3':''})
                front=await call('create_model_view',model_path=str(OUT/'bracket.m3d'),x=60,y=170,x_axis=[1,0,0],y_axis=[0,0,1])
                top=await call('create_model_view',model_path=str(OUT/'bracket.m3d'),x=60,y=55,x_axis=[1,0,0],y_axis=[0,1,0])
                sample_points=[[0,0,0],[120,0,0],[32.5,0,50],[0,80,0]]
                projected=await call('project_model_points',view_id=front['view_id'],points=sample_points)
                assert all(math.dist(a,b)<1e-6 for a,b in zip(projected['points'],[[0,0],[120,0],[32.5,50],[0,0]])),projected
                sheet=await call('project_model_points',view_id=front['view_id'],points=[[32.5,0,50]],to_sheet=True)
                assert math.dist(sheet['points'][0],[92.5,220])<1e-6,sheet
                for points,position,orientation,value in [([[0,0,0],[120,0,0]],[60,0,-15],'horizontal',120),
                         ([[32.5,0,50],[87.5,0,50]],[60,0,85],'horizontal',55),
                         ([[0,0,0],[0,0,35]],[-15,0,17.5],'vertical',35),
                         ([[0,0,0],[0,0,50]],[-30,0,25],'vertical',50)]:
                    d=await call('add_model_dimension',view_id=front['view_id'],points=points,position=position,orientation=orientation)
                    assert math.isclose(d['nominal_value'],value,abs_tol=1e-6),d
                await call('add_model_dimension',view_id=top['view_id'],points=[[0,0,0],[0,80,0]],position=[-15,40,0],orientation='vertical')
                await call('add_model_dimension',error=True,view_id=front['view_id'],points=[[0,0,0],[0,80,0]],position=[0,0,0])
                named=await call('create_model_view',model_path=str(OUT/'bracket.m3d'),projection_name='Bracket Front',x=260,y=180,scale=0.5)
                named_points=await call('project_model_points',view_id=named['view_id'],points=sample_points)
                assert all(math.dist(a,b)<1e-6 for a,b in zip(named_points['points'],projected['points'])),named_points
                await call('save_document',path=str(OUT/'bracket.cdw'))
                await call('export_drawing_image',path=str(OUT/'bracket.png'),dpi=130)
                await call('export_drawing_pdf',path=str(OUT/'bracket.pdf'))
                await call('close_document',document_reference=drawing['reference'])
                reopened=await call('open_document',path=str(OUT/'bracket.cdw')); owned.add(reopened['reference'])
                structure=await call('get_document_structure',include_objects=False)
                front_id=next(v['view_id'] for v in structure['views'] if v['number']==1)
                reopened_points=await call('project_model_points',view_id=front_id,points=sample_points)
                assert all(math.dist(a,b)<1e-6 for a,b in zip(reopened_points['points'],projected['points'])),reopened_points
            finally:
                docs=await call('list_documents')
                for d in sorted(docs['documents'],key=lambda d:d['type']!=1):
                    if d['reference'] in owned: await call('close_document',document_reference=d['reference'],discard_changes=True)
                if initial and initial['active']: await call('activate_document',document_reference=initial['active']['reference'])
    (OUT/'passed.json').write_text(json.dumps({'passed':True,'calls':len(report),'tools_tested':sorted({r['tool'] for r in report})}),encoding='utf-8')
    print('ALL EXPLICIT GEOMETRY CHECKS PASSED',OUT,flush=True)


if __name__=='__main__': asyncio.run(main())
