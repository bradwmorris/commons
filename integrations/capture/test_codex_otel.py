import http.server
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

import codex_otel as otel
import commons_capture as outbox

THREAD='11111111-1111-4111-8111-111111111111'
TURN='22222222-2222-4222-8222-222222222222'
TRACE='a'*32
ROOT='b'*16
CHILD='c'*16

def span(sid=ROOT,parent='d'*16,name='run_turn',thread=THREAD,turn=TURN):
    attrs=[] if thread is None else [{'key':k,'value':{'stringValue':v}} for k,v in [('conversation.id',thread),('turn.id',turn)]]
    return {'traceId':TRACE,'spanId':sid,'parentSpanId':parent,'name':name,'startTimeUnixNano':'1700000000000000000','endTimeUnixNano':'1700000000001000000','attributes':attrs,'status':{'code':0}}

def payload(*spans):
    return {'resourceSpans':[{'resource':{'attributes':[]},'scopeSpans':[{'scope':{'name':'synthetic'},'spans':list(spans)}]}]}

class Gate:
    def delivery(self):
        from contextlib import nullcontext
        return nullcontext()
    allowed=True
    def resolve(self,*args): return self.info if self.allowed else None

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.state=Path(self.temp.name)/'state'
        self.saved={};self.receipts={};self.posts=[];self.fail=False;self.lost=False
        test=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def send(self,code,value):
                body=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):
                rid=self.path.rsplit('/',1)[-1]
                if rid not in test.saved:return self.send(404,{})
                self.send(200,{'trace':test.saved[rid]})
            def do_POST(self):
                env=json.loads(self.rfile.read(int(self.headers['Content-Length'])));test.posts.append(env)
                if test.fail:return self.send(503,{})
                if env['batch_id'] not in test.receipts:
                    run=env['runs'][0]; prior=test.saved.get(run['id']);actual=prior['revision'] if prior else None
                    if actual!=run['expected_revision']:return self.send(409,{})
                    entries={e['span']['spanId']:e for e in prior['trace']} if prior else {}
                    entries.update({e['span']['spanId']:e for e in run['trace']})
                    test.saved[run['id']]={**run,'trace':list(entries.values()),'revision':(actual or 0)+1}
                    test.receipts[env['batch_id']]={'chat_id':THREAD}
                if test.lost:test.lost=False;return self.send(503,{})
                self.send(200,test.receipts[env['batch_id']])
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
        self.gate=Gate();self.gate.info={'origin':f'http://127.0.0.1:{self.server.server_port}',
            'token':'s'*40,'source':{'provider':'codex','namespace':'synthetic','thread_id':THREAD},
            'chat_id':THREAD,'title':'Synthetic','coverage':{'status':'partial'},'installation':'synthetic'}
        self.bridge=otel.Bridge(self.state,self.gate)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.worker.join();self.temp.cleanup()
    def retry_ready(self):
        with outbox.database(self.state) as db:
            with db:db.execute('UPDATE batches SET available=0')
    def test_child_before_root_exact_export_append_and_duplicate(self):
        self.bridge.ingest(payload(span(CHILD,ROOT,'exec_command',None)));self.bridge.pump();self.assertFalse(self.posts)
        self.bridge.ingest(payload(span()));self.bridge.pump();self.assertEqual(len(self.saved),1)
        saved=next(iter(self.saved.values()));self.assertEqual(len(saved['trace']),2)
        self.assertEqual(saved['trace'][1]['span']['endTimeUnixNano'],'1700000000001000000')
        self.bridge.pump();self.assertEqual(len(self.posts),1)
        self.bridge.ingest(payload(span('e'*16,ROOT,'late span',None)));self.bridge.pump()
        saved=next(iter(self.saved.values()));self.assertEqual(len(saved['trace']),3);self.assertEqual(saved['revision'],2)
    def test_no_personal_mixed_unknown_or_conflicting_context_on_disk(self):
        self.gate.allowed=False;self.bridge.ingest(payload(span()));self.bridge.pump()
        with outbox.database(self.state) as db:self.assertEqual(db.execute('SELECT count(*) FROM batches').fetchone()[0],0)
        self.gate.allowed=True
        self.bridge.ingest(payload(span(CHILD,ROOT,'foreign',THREAD,'33333333-3333-4333-8333-333333333333')));self.bridge.pump()
        self.assertFalse(self.posts)

    def test_append_after_api_double_roundoff_keeps_saved_span_immutable(self):
        root = span()
        root['attributes'].append({'key': 'duration', 'value': {'doubleValue': 0.0011250000000000001}})
        self.bridge.ingest(payload(root))
        self.bridge.pump()
        saved = next(iter(self.saved.values()))
        saved_root = saved['trace'][0]['span']
        saved_root['attributes'][-1]['value']['doubleValue'] = 0.001125

        self.bridge.ingest(payload(span(CHILD, ROOT, 'tool', None)))
        self.bridge.pump()
        self.assertEqual(len(self.posts), 2)
        self.assertEqual([entry['span']['spanId'] for entry in self.posts[1]['runs'][0]['trace']], [CHILD])
        self.assertEqual(saved_root['attributes'][-1]['value']['doubleValue'], 0.001125)

        saved_root['attributes'][-1]['value']['doubleValue'] = 0.001126
        with self.assertRaisesRegex(ValueError, 'saved native span changed'):
            self.bridge.pump()
        saved_root['attributes'][-1]['value']['doubleValue'] = 0.001125

        saved_root['endTimeUnixNano'] = '1700000000001000001'
        with self.assertRaisesRegex(ValueError, 'saved native span changed'):
            self.bridge.pump()
        self.assertEqual(len(self.posts), 2)

    def test_lost_ack_restart_retry_keeps_same_body_and_no_duplicates(self):
        self.lost=True;self.bridge.ingest(payload(span(),span(CHILD,ROOT,'tool',None)));self.bridge.pump()
        self.assertEqual(len(self.saved),1)
        self.retry_ready();self.bridge=otel.Bridge(self.state,self.gate);self.bridge.pump()
        self.assertEqual(self.posts[0],self.posts[1]);self.assertEqual(next(iter(self.saved.values()))['revision'],1)
        with outbox.database(self.state) as db:self.assertEqual(db.execute("SELECT count(*) FROM batches WHERE state='acknowledged'").fetchone()[0],1)
    def test_denied_turn_cannot_be_flushed_by_later_approved_turn(self):
        self.fail=True;self.bridge.ingest(payload(span()));self.bridge.pump();self.retry_ready()
        self.fail=False;self.gate.allowed=False;self.bridge=otel.Bridge(self.state,self.gate);self.bridge.pump()
        self.assertEqual(len(self.posts),1);self.assertFalse(self.saved)
    def test_volatile_expiry_and_conflicting_span_fail_closed(self):
        clock=[0];b=otel.Bridge(self.state,self.gate,lambda:clock[0]);b.ingest(payload(span(CHILD,ROOT,'tool',None)))
        clock[0]=otel.TTL+1;b.expire();self.assertFalse(b.pending)
        b.ingest(payload(span()));other=span();other['name']='changed';b.ingest(payload(other));b.pump();self.assertFalse(self.posts)
    def test_credential_redaction_before_disk(self):
        root=span();root['events']=[{'name':'test','attributes':[{'key':'output','value':{'stringValue':'Bearer '+self.gate.info['token']}}]}]
        self.fail=True;self.bridge.ingest(payload(root));self.bridge.pump()
        with outbox.database(self.state) as db:
            body=db.execute('SELECT payload FROM batches').fetchone()[0]
            self.assertNotIn(self.gate.info['token'],body);self.assertIn('[credential redacted]',body)

    def test_status_reports_root_shape_without_unclassified_values(self):
        child=span(CHILD,ROOT,'private span name',None)
        root=span();root['attributes']=[{'key':'turn.id','value':{'stringValue':TURN}}]
        self.bridge.ingest(payload(child,root))
        status=self.bridge.status()
        self.assertEqual(status['counters'],{'spans_received':2,'run_turn_received':1,'run_turn_turn_id':1})
        self.assertEqual(status['buffered_root_counts'],{'none':1})
        self.assertNotIn(TURN,json.dumps(status));self.assertNotIn('private span name',json.dumps(status))
        other=span('e'*16);other['traceId']='f'*32
        self.bridge.ingest(payload(other))
        self.assertEqual(self.bridge.status()['buffered_root_counts'],{'none':1,'one':1})

    def task_root(self):
        root=span(name='session_task.turn',thread=None)
        root['attributes']=[{'key':'thread.id','value':{'intValue':'27'}},
                            {'key':'thread.id','value':{'stringValue':THREAD}},
                            {'key':'turn.id','value':{'stringValue':TURN}}]
        return root

    def test_desktop_task_root_with_os_thread_and_uncorrelated_run_turn(self):
        root=self.task_root();child=span(CHILD,ROOT,'run_turn',None)
        self.bridge.ingest(payload(child,root));self.bridge.pump()
        saved=next(iter(self.saved.values()))
        self.assertEqual(len(saved['trace']),2)
        self.assertEqual(saved['input']['thread_id'],THREAD)
        self.assertEqual(saved['input']['turn_id'],TURN)

    def test_task_root_does_not_bypass_business_gate(self):
        self.gate.allowed=False;self.bridge.ingest(payload(self.task_root()));self.bridge.pump()
        self.assertFalse(self.posts)
        self.assertEqual(self.bridge.counters['not_authorized_yet'],1)

    def test_ambiguous_task_thread_uuid_fails_closed(self):
        root=self.task_root()
        root['attributes'].append({'key':'thread.id','value':{'stringValue':'33333333-3333-4333-8333-333333333333'}})
        self.bridge.ingest(payload(root));self.bridge.pump();self.assertFalse(self.posts)

    def test_task_root_requires_uuid_and_unambiguous_turn(self):
        root=self.task_root();root['attributes'].pop(1)
        self.assertIsNone(otel.root_context(root))
        root=self.task_root();root['attributes'].append({'key':'turn.id','value':{'stringValue':'33333333-3333-4333-8333-333333333333'}})
        self.assertIsNone(otel.root_context(root))

    def test_both_correlated_root_names_require_same_context_and_parentage(self):
        task=self.task_root();legacy=span(CHILD,ROOT)
        self.bridge.ingest(payload(task,legacy));self.bridge.pump()
        self.assertEqual(len(next(iter(self.saved.values()))['trace']),2)
        self.assertEqual(next(iter(self.saved.values()))['started_at'],otel.iso(task['startTimeUnixNano']))

    def test_unrelated_or_conflicting_correlated_roots_fail_closed(self):
        for conflict in (False,True):
            with self.subTest(conflict=conflict):
                self.bridge=otel.Bridge(self.state,self.gate)
                task=self.task_root();legacy=span(CHILD,ROOT if conflict else 'd'*16)
                if conflict: legacy['attributes'][1]['value']['stringValue']='33333333-3333-4333-8333-333333333333'
                self.bridge.ingest(payload(task,legacy));self.bridge.pump();self.assertFalse(self.posts)


class RouteGateTests(unittest.TestCase):
    def test_real_routing_windows_source_lifecycle_and_readonly_state(self):
        import auto_capture as auto
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=root/'capture';home=root/'home';sessions=home/'sessions';sessions.mkdir(parents=True)
            token=root/'token';token.write_text('s'*40);token.chmod(0o600)
            config={'namespace':'synthetic','codex_home':str(home),'codex':'not-run','amp':'not-run',
                    'token_file':str(token),'domain_label':'synthetic'}
            source=auto.source_for(config,'codex',THREAD)
            path=sessions/('rollout-'+THREAD+'.jsonl')
            rows=[{'timestamp':'2023-11-14T22:13:20Z','type':'event_msg','payload':{'type':'task_started','turn_id':TURN}},
                  {'timestamp':'2023-11-14T22:13:20Z','type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'Synthetic business request'}]}}]
            path.write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
            with outbox.database(state) as db:
                auto.setup(db);outbox.initialize(db,'http://127.0.0.1:1','synthetic');auto.configure(db,config,1699999999)
                auto.route(db,source,TURN,'business');auto.reconcile(db,source,auto.codex_turns(rows,source,1699999999))
                auto.route(db,source,'44444444-4444-4444-8444-444444444444','personal')
                auto.route(db,source,'55555555-5555-4555-8555-555555555555','mixed')
                with db:db.execute("UPDATE batches SET chat_id=?,state='acknowledged',payload=NULL",(THREAD,))
            dbpath=state/'delivery.sqlite3';before=hashlib.sha256(dbpath.read_bytes()).hexdigest()
            detail={'thread':{**source,'coverage':{'status':'partial'}},'object':{'title':'Synthetic'}}
            gate=otel.RouteGate(state)
            with patch.object(otel,'request',return_value=detail):
                self.assertIsNotNone(gate.resolve(THREAD,TURN,1700000000))
                self.assertIsNone(gate.resolve(THREAD,'33333333-3333-4333-8333-333333333333',1700000000))
                self.assertIsNone(gate.resolve(THREAD,'44444444-4444-4444-8444-444444444444',1700000000))
                self.assertIsNone(gate.resolve(THREAD,'55555555-5555-4555-8555-555555555555',1700000000))
                self.assertIsNone(gate.resolve(THREAD,TURN,1600000000))
                path.rename(root/path.name)
                self.assertIsNone(gate.resolve(THREAD,TURN,1700000000))
            self.assertEqual(hashlib.sha256(dbpath.read_bytes()).hexdigest(),before)
            with outbox.database(state) as db:
                with self.assertRaises(ValueError):auto.route(db,source,TURN,'personal')
            with patch.object(otel,'request',side_effect=AssertionError('Stopped route must not reach network')):
                self.assertIsNone(gate.resolve(THREAD,TURN,1700000000))

    def test_checked_delivery_serializes_with_disable(self):
        import auto_capture as auto
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)/'capture'
            with auto.locked_state(state) as db:
                auto.configure(db,{'namespace':'synthetic','codex_home':'/synthetic','codex':'unused','amp':'unused','token_file':'/synthetic-token','domain_label':'synthetic'})
            started=threading.Event();finished=threading.Event()
            def disable():
                started.set()
                with auto.locked_state(state) as db:auto.set_active(db,False)
                finished.set()
            gate=otel.RouteGate(state)
            with gate.delivery():
                worker=threading.Thread(target=disable);worker.start()
                self.assertTrue(started.wait(1));self.assertFalse(finished.wait(.1))
            worker.join(2);self.assertTrue(finished.is_set())
            with outbox.database(state) as db:self.assertFalse(auto.settings(db)[2])

if __name__=='__main__':unittest.main()
