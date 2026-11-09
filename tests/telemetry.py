"""Native span capture/export against the disposable authenticated API."""
import copy
import os
import unittest
import uuid
from atomic import Client

class TelemetryAcceptance(unittest.TestCase):
    def setUp(self):
        self.c=Client(os.environ['COMMONS_TEST_ORIGIN'])
        assert self.c.call('login',{'username':'alice','password':os.environ['COMMONS_TEST_PASSWORD']})[0]==200
        self.chat=str(uuid.uuid4());self.rid=str(uuid.uuid4());self.trace=uuid.uuid4().hex
        self.coverage={'status':'partial','messages':'visible text','tools':'visible calls/results','attachments':'none','history':'current','gaps':['Transcript gap retained']}
        self.env={'contract_version':'commons.capture/1','source':{'provider':'codex','namespace':'synthetic-otel','thread_id':self.chat},'batch_id':'thread','chat_id':self.chat,'title':'Synthetic native trace','coverage':self.coverage,'items':[]}
        assert self.c.call('capture',self.env)[0]==200
    def entry(self,sid='1'*16,parent='2'*16,name='run_turn',error=False):
        return {'resource':{'attributes':[{'key':'service.name','value':{'stringValue':'synthetic-codex'}}]},'scope':{'name':'synthetic-native'},'resourceSchemaUrl':'https://opentelemetry.io/schemas/1.30.0',
            'span':{'traceId':self.trace,'spanId':sid,'parentSpanId':parent,'name':name,'kind':1,
            'startTimeUnixNano':'1700000000000000000','endTimeUnixNano':'1700000000001000001',
            'status':{'code':2 if error else 0},'events':[{'name':'synthetic.error' if error else 'synthetic.event','timeUnixNano':'1700000000001000000'}],
            'links':[{'traceId':'a'*32,'spanId':'b'*16}],'attributes':[{'key':'turn.id','value':{'stringValue':'synthetic'}}]}}
    def envelope(self,entries,revision=None,batch='spans'):
        return {**self.env,'batch_id':batch,'coverage':{**self.coverage,'gaps':[]},'runs':[{'id':self.rid,'source_run_id':self.trace,'kind':'opentelemetry','status':'ended','expected_revision':revision,'trace':entries}]}
    def test_native_append_export_exact_and_retry(self):
        root=self.entry();child=self.entry('3'*16,'1'*16,'tool failed',True)
        first=self.envelope([root]);code,a=self.c.call('capture',first);self.assertEqual(code,200,a);self.assertEqual(self.c.call('capture',first)[1],a)
        code,r=self.c.call('capture',self.envelope([child],1,'late-child'));self.assertEqual(code,200,r)
        _,r=self.c.call('traces/'+self.rid);self.assertEqual(r['trace']['trace'],[root,child]);self.assertEqual(r['trace']['revision'],2)
        code,r=self.c.call('traces/'+self.rid+'/otlp');self.assertEqual(code,200,r)
        self.assertEqual([g['scopeSpans'][0]['spans'][0] for g in r['resourceSpans']],[root['span'],child['span']])
        self.assertEqual(r['resourceSpans'][0]['resource'],root['resource'])
        _,r=self.c.call('threads/'+self.chat);self.assertEqual(r['thread']['coverage'],self.coverage)
        self.assertEqual(Client(self.c.base).call('traces/'+self.rid+'/otlp')[0],401)
    def test_native_spans_remain_excluded_from_conversation_body_search(self):
        code,r=self.c.call('capture',self.envelope([self.entry(name='Nativespanonlyneedle')]));self.assertEqual(code,200,r)
        code,r=self.c.call('retrieve?q=Nativespanonlyneedle&scope=threads&object_id='+self.chat+'&neighbours=0');self.assertEqual(code,200,r)
        self.assertEqual(r['primary_count'],0);self.assertGreaterEqual(r['index']['excluded_native_trace_items'],1)
        self.assertIn('native_span_telemetry_excluded',r['index']['conversation_content'])

    def test_invalid_timing_ids_duplicate_and_source_rejected_atomically(self):
        for field,value in [('traceId','0'*32),('spanId','short'),('endTimeUnixNano','1'),('parentSpanId','1'*16),('status',{'code':9})]:
            e=self.entry();e['span'][field]=value
            code,r=self.c.call('capture',self.envelope([e],batch=field));self.assertEqual(code,422,r)
            self.assertEqual(self.c.call('traces/'+self.rid)[0],404)
        e=self.entry();self.assertEqual(self.c.call('capture',self.envelope([e,e]))[0],422)
    def test_stale_changed_span_and_foreign_thread_cannot_overwrite(self):
        e=self.entry();self.assertEqual(self.c.call('capture',self.envelope([e]))[0],200)
        changed=copy.deepcopy(e);changed['span']['name']='changed'
        self.assertEqual(self.c.call('capture',self.envelope([changed],1,'changed'))[0],409)
        self.assertEqual(self.c.call('capture',self.envelope([self.entry('3'*16)],None,'stale'))[0],409)
        foreign=self.envelope([self.entry('3'*16)],None,'foreign');foreign['chat_id']=str(uuid.uuid4());foreign['source']['thread_id']=foreign['chat_id']
        self.assertEqual(self.c.call('capture',foreign)[0],409)
    def test_scope_and_managed_deletion_export_and_late_span_fence(self):
        _,token=self.c.call('tokens',{'label':'Synthetic note-only telemetry denial','write_kinds':['note']})
        scoped=Client(self.c.base,token['token']);self.assertEqual(scoped.call('capture',self.envelope([self.entry()]))[0],403)
        first=self.envelope([self.entry()]);self.assertEqual(self.c.call('capture',first)[0],200)
        _,r=self.c.call('threads/'+self.chat)
        self.assertEqual(self.c.call('threads/'+self.chat+'/delete',{'expected_revision':r['object']['revision'],'acknowledge_managed_copy_deletion':True})[0],200)
        self.assertEqual(self.c.call('traces/'+self.rid+'/otlp')[0],404)
        self.assertEqual(self.c.call('capture',first)[0],410)
        self.assertEqual(self.c.call('capture',self.envelope([self.entry('3'*16)],1,'late-deleted'))[0],410)

    def test_concurrent_trace_id_collision_has_one_owner(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        requests=[]
        for index in range(8):
            code,token=self.c.call('tokens',{'label':'Synthetic collision '+str(index),'write_kinds':['thread']})
            self.assertEqual(code,200,token)
            env=copy.deepcopy(self.envelope([self.entry()]));env['chat_id']=str(uuid.uuid4());env['source']['thread_id']=env['chat_id']
            env['runs'][0]['input']={'collision_source':index}
            requests.append((Client(self.c.base,token['token']),env))
        barrier=threading.Barrier(len(requests))
        def submit(pair):
            client,envelope=pair;barrier.wait();code,result=client.call('capture',envelope)
            return code,envelope,result
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:results=list(pool.map(submit,requests))
        winners=[r for r in results if r[0]==200]
        self.assertEqual(len(winners),1,[(r[0],r[2]) for r in results])
        self.assertTrue(all(r[0] in (200,409) for r in results))
        _,saved=self.c.call('traces/'+self.rid)
        self.assertEqual(saved['trace']['chat_object_id'],winners[0][1]['chat_id'])
        self.assertEqual(saved['trace']['input'],winners[0][1]['runs'][0]['input'])

    def test_trace_collection_metadata_and_format_filters(self):
        self.assertEqual(self.c.call('capture',self.envelope([self.entry()]))[0],200)
        legacy=copy.deepcopy(self.env);legacy['batch_id']='legacy';oldid=str(uuid.uuid4());legacy['runs']=[{'id':oldid,'source_run_id':'legacy','kind':'request','status':'done','trace':[]}]
        self.assertEqual(self.c.call('capture',legacy)[0],200)
        code,result=self.c.call('traces?format=native&limit=200');self.assertEqual(code,200,result)
        row=next(r for r in result['traces'] if r['id']==self.rid);self.assertEqual(row['span_count'],1);self.assertEqual(row['provider'],'codex');self.assertEqual(row['thread_title'],'Synthetic native trace');self.assertFalse(any(r['id']==oldid for r in result['traces']))
        code,result=self.c.call('traces?format=history&limit=200');self.assertEqual(code,200,result);self.assertTrue(any(r['id']==oldid for r in result['traces']));self.assertFalse(any(r['id']==self.rid for r in result['traces']))
        self.assertEqual(self.c.call('traces?format=unknown')[0],422)
