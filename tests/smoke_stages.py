"""Live regression for mutation effects, change stages and stored assertions.

MCP only. Works in its own new documents and closes only those.
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
OUT=ROOT/'artifacts'/datetime.now().strftime('stages-%Y%m%d-%H%M%S-%f')


async def main():
    OUT.mkdir(parents=True)
    report=[]; owned=set(); initial=None
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'server.py')],
                                env={**os.environ,'KOMPAS_ALLOW_SCRIPTS':'0'})
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()

            async def call(tool,error=False,**args):
                r=await session.call_tool(tool,args)
                data=r.structuredContent or json.loads(r.content[0].text)
                failure=bool(r.isError) or data.get('success') is False
                report.append({'tool':tool,'arguments':args,'result':data,'expected_error':error,'passed':failure==error})
                (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                assert failure==error,(tool,data)
                print('PASS',tool,'expected error' if error else '',flush=True)
                return data

            async def create(kind):
                r=await call('create_document',kind=kind); owned.add(r['reference']); return r

            async def volume():
                return (await call('get_model_properties'))['volume_mm3']

            try:
                initial=await call('status')
                part=await create('part')
                s=await call('sketch3d',rectangles=[[0,0,40,30]])
                boss=await call('extrude',sketch_id=s['sketch_id'],depth=20)
                assert boss['effect']['verdict']=='ok' and math.isclose(boss['effect']['volume_delta_mm3'],24000,rel_tol=1e-6),boss
                assert 'bodies' not in boss['before'] and 'bodies' not in boss['after'],boss
                base=await volume()

                # Assertions: hold now, then reach the effect of a violating step.
                held=await call('assert_register',name='в габарите',kind='bounds_within',spec={'bounds_mm':[-1,-1,-1,41,31,30]})
                assert held['holds_now'],held
                await call('assert_register',error=True,name='bad',kind='volume_range',spec={'min_mm3':5,'max_mm3':1})
                assert len((await call('assert_list'))['assertions'])==1

                # Stage 1: cut + parameter edit of a pre-existing feature, then abort restores both.
                stage=await call('change_begin',label='карман и глубина',intent='abort test')
                assert stage['assertions']==1,stage
                profile=await call('create_closed_profile',plane='XY',origin=[0,0,0],x_axis=[1,0,0],y_axis=[0,1,0],
                                   contours=[[{'kind':'circle','center':[20,15],'radius':5}]])
                cut=await call('cut_extrude',sketch_id=profile['sketch_id'],depth=5,direction=[0,0,1],name='Карман')
                assert cut['effect']['verdict']=='ok' and cut['effect']['volume_delta_mm3']<0,cut
                edited=await call('set_feature_parameters',feature_id=boss['feature_id'],parameters={'depth':25})
                assert edited['effect']['verdict']=='ok' and math.isclose(edited['effect']['volume_delta_mm3'],6000,rel_tol=1e-6),edited
                status=await call('change_status')
                assert status['open'] and 'Карман' in status['added_features'] and status['operations']==3,status
                assert status['effect']['verdict']=='ok',status
                aborted=await call('change_abort')
                assert 'Карман' in aborted['deleted_features'] and aborted['restored_parameters'],aborted
                assert math.isclose(await volume(),base,rel_tol=1e-9)
                assert (await call('get_feature_parameters',feature_id=boss['feature_id']))['parameters']['normal_side'][2]==20
                assert not (await call('change_status'))['open']

                # Stage 2: assertion failure blocks change_end until forced; guard pins the document.
                await call('change_begin',label='рост за габарит')
                tall=await call('create_closed_profile',plane='XY',origin=[0,0,0],x_axis=[1,0,0],y_axis=[0,1,0],
                                contours=[[{'kind':'circle','center':[10,10],'radius':3}]])
                grown=await call('extrude',sketch_id=tall['sketch_id'],depth=35)
                assert grown['effect']['verdict']=='assertion_failed',grown
                other=await create('part')
                o=await call('sketch3d',error=True,rectangles=[[0,0,5,5]])
                assert 'open in document' in o['message'],o
                await call('close_document',error=True,document_reference=part['reference'],discard_changes=True)
                await call('close_document',document_reference=other['reference'],discard_changes=True)
                owned.discard(other['reference'])
                await call('activate_document',document_reference=part['reference'])
                refused=await call('change_end',error=True)
                assert refused['stage_open'] and refused['effect']['verdict']=='assertion_failed',refused
                forced=await call('change_end',force=True)
                assert forced['forced'] and forced['added_features'],forced
                checked=await call('assert_check',error=True)
                assert checked['failures'][0]['assertion']=='в габарите',checked
                await call('assert_remove',name='в габарите')
                assert (await call('assert_check'))['checked']==0

                # Stage 3: normal end; deleted feature effect is reported without no_effect.
                await call('change_begin',label='удаление')
                removed=await call('delete_feature',name=grown['name'])
                assert removed['effect']['verdict']=='ok' and removed['effect']['volume_delta_mm3']<0,removed
                ended=await call('change_end')
                assert ended['closed'] and grown['name'] in ended['removed_features'],ended
                assert math.isclose(await volume(),base,rel_tol=1e-9)
            finally:
                try:
                    if any(r['tool']=='change_begin' for r in report):
                        st=await session.call_tool('change_status',{})
                        if (st.structuredContent or {}).get('open'):
                            await session.call_tool('change_end',{'force':True})
                    docs=await call('list_documents')
                    for doc in docs['documents']:
                        if doc['reference'] in owned:
                            await call('close_document',document_reference=doc['reference'],discard_changes=True)
                    if initial and initial['active']:
                        await call('activate_document',document_reference=initial['active']['reference'])
                except Exception as exc:
                    (OUT/'cleanup-error.txt').write_text(str(exc),encoding='utf-8')
    print('ALL STAGE CHECKS PASSED',OUT,flush=True)
    (OUT/'passed.json').write_text(json.dumps({'passed':True,'calls':len(report),'tools_tested':sorted({r['tool'] for r in report})}),encoding='utf-8')


if __name__=='__main__':
    asyncio.run(main())
