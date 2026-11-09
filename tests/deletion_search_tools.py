"""Real three-tool boundary against the disposable schema11 HTTP installation."""
import asyncio
import os
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'integrations/mcp'))
from atomic import Client
from commons_mcp.client import HttpClient,Config
from tools import commons_write,commons_search,commons_read

async def main():
    c=Client(os.environ['COMMONS_TEST_ORIGIN']);assert c.call('login',dict(username='alice',password=os.environ['COMMONS_TEST_PASSWORD']))[0]==200
    _,user=c.call('users',dict(username='tools-'+uuid.uuid4().hex[:12],title='Synthetic tool agent',user_kind='agent',role='member'))
    code,t=c.call('tokens',dict(account_id=user['id'],label='synthetic three-tool journey',write_kinds=['note','thread']));assert code==200,t
    async with HttpClient(Config(c.base,t['token'])) as client:
        await client.check_compatibility()
        key=str(uuid.uuid4())
        result=await commons_write.execute(dict(idempotency_key=key,execute=True,operations=[dict(op='create_object',local_ref='note',kind='note',title='Tool deletion fixture',description='Synthetic tool integration record.',body='Tooldeletionneedle',fields={})]),client)
        oid=result['local_refs']['note']
        deletion=dict(idempotency_key=str(uuid.uuid4()),operations=[dict(op='delete_object',object_id=oid,expected_revision=1,acknowledge_owned_content_deletion=True)])
        assert (await commons_write.execute(deletion,client))['validated_only']
        assert (await commons_read.execute(dict(resource='object',id=oid),client))['object']['body']=='Tooldeletionneedle'
        deletion['execute']=True
        saved=await commons_write.execute(deletion,client);assert saved['changes'][0]['deleted']
        assert await commons_write.execute(deletion,client)==saved
        result=await commons_search.execute(dict(query='Tooldeletionneedle',object_id=oid,scope='all'),client);assert result['primary_count']==0
        cid=str(uuid.uuid4())
        code,r=c.call('capture',dict(contract_version='commons.capture/1',source=dict(provider='Synthetic',namespace='tools',thread_id=cid),chat_id=cid,batch_id='first',title='Synthetic tool conversation',coverage=dict(status='partial',messages='visible',tools='visible',attachments='none',history='current',gaps=[]),items=[dict(id=str(uuid.uuid4()),source_item_id='message',position=0,kind='message',role='human',body='Toolconversationneedle')],runs=[]));assert code==200,r
        result=await commons_search.execute(dict(query='Toolconversationneedle',scope='threads',object_id=cid),client)
        read=result['context']['objects'][0]['match']['read'];assert read['resource']=='thread_text'
        assert 'Toolconversationneedle' in (await commons_read.execute(read,client))['text']
    print('Passed: real MCP module HTTP validation/execute/replay/deletion search and conversation search/window read')

asyncio.run(main())
