"""Schema-10 API acceptance against an explicitly supplied synthetic installation."""
import http.cookiejar
import json
import os
import unittest
import urllib.error
import urllib.request
import uuid

class Client:
    def __init__(self, base, token=None):
        self.base,self.token=base,token
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(self,path,body=None):
        headers={'Content-Type':'application/json','Origin':self.base}
        if self.token:headers['Authorization']='Bearer '+self.token
        req=urllib.request.Request(self.base+'/api/'+path,headers=headers,data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(req,timeout=20) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:
            with e:return e.code,json.load(e)
    def apply(self,operations,key=None,dry=False):
        return self.call('apply',{'contract_version':'commons/0.1','idempotency_key':key or str(uuid.uuid4()),'validate_only':dry,'operations':operations})

class AtomicAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=Client(os.environ['COMMONS_TEST_ORIGIN'])
        code,_=cls.c.call('login',{'username':'alice','password':os.environ['COMMONS_TEST_PASSWORD']});assert code==200
    def create(self,kind='note',**overrides):
        op={'op':'create_object','local_ref':'new','kind':kind,'title':'Synthetic atomic record','description':'A synthetic note about the atomic schema migration.','body':'Supporting detail.','fields':{'intent':'idea','content_format':'markdown'}}
        op.update(overrides);code,r=self.c.apply([op]);self.assertEqual(code,200,r);return r['local_refs']['new']
    def test_ordinary_deletion_scope_retry_history_and_independent_knowledge(self):
        _,me=self.c.call('me')
        survivor=self.create(body='Independent surviving record.')
        for kind,fields in [('note',{}),('task',dict(status='todo',priority='medium',owner_object_id=me['id'],due_at='2026-11-08T12:00:00Z',work_kind='general')),('source',dict(source_kind='document')),('entity',{}),('theme',dict(slug='delete-'+uuid.uuid4().hex)),('event',{})]:
            oid=self.create(kind,fields=fields,body='Syntheticdeletionneedle')
            code,r=self.c.apply([dict(op='append_artifact',object_id=oid,expected_revision=1,body='Owneddeletionneedle')]);self.assertEqual(code,200,r);aid=r['changes'][0]['artifact_id']
            _,v=self.c.call('objects/'+survivor)
            code,r=self.c.apply([dict(op='create_connection',from_id=oid,to_id=survivor,from_revision=2,to_revision=v['object']['revision'],kind='related_to',explanation='Synthetic removed relationship text.')]);self.assertEqual(code,200,r)
            _,v=self.c.call('objects/'+oid);history=v['history'];rev=v['object']['revision']
            op=dict(op='delete_object',object_id=oid,expected_revision=rev,acknowledge_owned_content_deletion=True)
            self.assertEqual(self.c.apply([dict(op,expected_revision=rev-1)])[0],409)
            self.assertEqual(self.c.apply([dict(op,acknowledge_owned_content_deletion=False)])[0],422)
            code,r=self.c.apply([op],dry=True);self.assertEqual(code,200,r);self.assertEqual(self.c.call('objects/'+oid)[0],200)
            self.assertEqual(self.c.apply([op,dict(op='unsupported')])[0],422);self.assertEqual(self.c.call('objects/'+oid)[0],200);self.assertEqual(self.c.call('artifacts/'+aid+'/text')[0],200)
            # A credential with another kind's scope cannot delete this Object.
            code,u=self.c.call('users',dict(username='delete-'+uuid.uuid4().hex[:12],title='Deletion scope fixture',user_kind='agent',role='member'));self.assertEqual(code,200,u)
            code,t=self.c.call('tokens',dict(account_id=u['id'],label='scope denial',write_kinds=['event' if kind!='event' else 'note']));self.assertEqual(code,200,t)
            self.assertEqual(Client(self.c.base,t['token']).apply([op])[0],403)
            key=str(uuid.uuid4());code,r=self.c.apply([op],key);self.assertEqual(code,200,r);self.assertEqual(self.c.apply([op],key),(code,r))
            self.assertEqual(self.c.apply([dict(op,expected_revision=rev+1)],key)[0],409)
            self.assertEqual(self.c.call('objects/'+oid)[0],410);self.assertEqual(self.c.call('artifacts/'+aid+'/text')[0],410)
            for h in history:
                _,h=self.c.call('history/'+h['id']);self.assertNotIn('Syntheticdeletionneedle',json.dumps(h));self.assertNotIn('Owneddeletionneedle',json.dumps(h))
            _,v=self.c.call('retrieve?q=Syntheticdeletionneedle&scope=all&neighbours=0');self.assertNotIn(oid,[o['id'] for o in v['context']['objects']])
            _,v=self.c.call('objects/'+survivor);self.assertEqual(v['object']['body'],'Independent surviving record.')

    def test_captured_body_search_exact_windows_append_correction_and_delete(self):
        scope_fixture=self.create(title='Exactscopeisolationneedle')
        _,isolated=self.c.call('retrieve?q=Exactscopeisolationneedle&scope=threads&neighbours=0');self.assertEqual(isolated['primary_count'],0)
        cid=str(uuid.uuid4());iid=str(uuid.uuid4())
        # Near the per-item capture bound: a monolithic PostgreSQL tsvector
        # would exceed its size limit, and the match is in the final window.
        body='Padding visible content. '*40000+'Messageonlyneedle 東京 🌿 exact phrase.'
        payload=dict(contract_version='commons.capture/1',source=dict(provider='Synthetic',namespace='thread-search',thread_id=cid),batch_id='first',chat_id=cid,title='Synthetic conversation',coverage=dict(status='partial',messages='visible',tools='visible',attachments='none',history='current',gaps=['Synthetic partial capture']),items=[dict(id=iid,source_item_id='message',position=0,kind='message',role='human',body=body)],runs=[])
        code,r=self.c.call('capture',payload);self.assertEqual(code,200,r)
        self.assertEqual(self.c.apply([dict(op='correct_evidence',object_id=scope_fixture,expected_revision=1,target_type='message',target_id=iid,reason='Rejected foreign message correction',representation=dict(body='Forged visible content'))])[0],422)
        unrelated=self.create('source',title='Unrelated incomplete evidence',description='A source with deliberately incomplete synthetic evidence.',fields=dict(source_kind='document'))
        self.assertEqual(self.c.apply([dict(op='save_artifact',object_id=unrelated,expected_revision=1,artifact=dict(body='Unrelated partial evidence.',capture_outcome='incomplete',capture_reason='Synthetic unverified remainder'))])[0],200)
        _,scoped=self.c.call('retrieve?q=Messageonlyneedle&scope=threads&neighbours=0')
        self.assertEqual(scoped['primary_count'],1);self.assertEqual(scoped['index']['excluded_incomplete_artifacts'],0)
        _,thread=self.c.call('threads/'+cid);projection='title: '+thread['object']['title']+' | text: '+thread['object']['description']+'\n\n'+body
        for scope in ['objects','threads','all']:
            code,r=self.c.call('retrieve?q=Messageonlyneedle&scope='+scope+'&neighbours=0&object_id='+cid);self.assertEqual(code,200,r)
            self.assertEqual(r['primary_count'],1,r);match=r['context']['objects'][0]['match'];read=match['read'];self.assertEqual(read['resource'],'thread_text');self.assertGreater(read['offset'],0)
            if scope=='threads':self.assertEqual(r['index']['eligible'],1);self.assertEqual(r['index']['thread_sources'],1)
            code,window=self.c.call('threads/'+cid+'/text?'+__import__('urllib.parse',fromlist=['urlencode']).urlencode({k:v for k,v in read.items() if k not in ['resource','id']}));self.assertEqual(code,200,window)
            self.assertIn('Messageonlyneedle 東京 🌿 exact phrase.',window['text']);self.assertEqual(window['text'],projection[read['offset']:read['offset']+read['limit']]);self.assertEqual(window['coverage']['status'],'partial')
        _,r=self.c.call('retrieve?q=Messageonlyneedle&scope=artifacts&object_id='+cid);self.assertEqual(r['primary_count'],0)
        payload.update(batch_id='second',items=[dict(id=str(uuid.uuid4()),source_item_id='empty',position=1,kind='message',role='human',body=''),dict(id=str(uuid.uuid4()),source_item_id='tool',position=2,kind='tool_result',role='tool',body='Toolonlyneedle')])
        self.assertEqual(self.c.call('capture',payload)[0],200)
        self.assertEqual(self.c.call('threads/'+cid+'/text?expected_revision='+str(read['expected_revision'])+'&offset=0&limit=100')[0],409)
        _,v=self.c.call('threads/'+cid)
        code,r=self.c.apply([dict(op='correct_evidence',object_id=cid,expected_revision=v['object']['revision'],target_type='message',target_id=iid,reason='Synthetic correction',representation=dict(body='Replacementonlyneedle'))]);self.assertEqual(code,200,r)
        for query,count in [('Messageonlyneedle',0),('Replacementonlyneedle',1),('Toolonlyneedle',1),('Synthetic%20Replacementonlyneedle',1),('conversation%20Toolonlyneedle',1)]:
            _,r=self.c.call('retrieve?q='+query+'&scope=threads&object_id='+cid);self.assertEqual(r['primary_count'],count,r)
            if query=='Toolonlyneedle':
                read=r['context']['objects'][0]['match']['read'];_,window=self.c.call('threads/'+cid+'/text?'+__import__('urllib.parse',fromlist=['urlencode']).urlencode({k:v for k,v in read.items() if k not in ['resource','id']}));self.assertEqual(window['text'],'Toolonlyneedle')
        _,v=self.c.call('threads/'+cid)
        self.assertEqual(self.c.apply([dict(op='delete_object',object_id=cid,expected_revision=v['object']['revision'],acknowledge_owned_content_deletion=True)])[0],422)
        self.assertEqual(self.c.call('threads/'+cid+'/delete',dict(expected_revision=v['object']['revision'],acknowledge_managed_copy_deletion=True))[0],200)
        _,r=self.c.call('retrieve?q=Toolonlyneedle&scope=all&object_id='+cid);self.assertEqual(r['primary_count'],0)
        self.assertEqual(self.c.call('capture',payload)[0],410)

    def test_schema_and_user_separation(self):
        code,s=self.c.call('schema');self.assertEqual(code,200,s)
        tables={c['table'] for c in s['columns']};self.assertEqual(tables,{'objects','users','credentials','artifacts','changes','connections','request_receipts','traces','trace_items','chunks'})
        self.assertEqual(len([c for c in s['columns'] if c['table']=='objects']),9)
        _,u=self.c.call('users');self.assertTrue(u['users']);self.assertNotIn('password_hash',json.dumps(u));self.assertNotIn('avatar_image',json.dumps(u))
        uid=u['users'][0]['id'];self.assertEqual(self.c.call('users/'+uid)[0],200);self.assertEqual(self.c.call('objects/'+uid)[0],404)
    def test_packet_body_partial_updates_and_conflicts(self):
        oid=self.create();_,r=self.c.call('objects/'+oid);o=r['object'];self.assertEqual(o['body'],'Supporting detail.');self.assertNotIn('created_by',o);self.assertIn('created_by',o['metadata'])
        code,r=self.c.apply([{'op':'update_object','object_id':oid,'expected_revision':1,'title':'Changed title'}]);self.assertEqual(code,200,r)
        _,r=self.c.call('objects/'+oid);self.assertEqual(r['object']['body'],'Supporting detail.');self.assertEqual(r['object']['fields']['intent'],'idea')
        self.assertEqual(self.c.apply([{'op':'update_object','object_id':oid,'expected_revision':1,'body':'Stale'}])[0],409)
    def test_exact_token_rejection_is_atomic(self):
        oid=self.create();code,r=self.c.apply([{'op':'update_object','object_id':oid,'expected_revision':1,'body':'Long supporting detail. '*1000}]);self.assertEqual(code,422,r);self.assertIn('500',r['error']);_,r=self.c.call('objects/'+oid);self.assertEqual(r['object']['revision'],1)
    def test_deprecated_fields_and_kinds_reject(self):
        for kind in ['memory','user','category','chat','trace']:
            code,_=self.c.apply([{'op':'create_object','local_ref':'bad','kind':kind,'title':'Bad','description':'A rejected old kind.','fields':{}}]);self.assertIn(code,[403,422])
        self.assertEqual(self.c.apply([{'op':'create_object','local_ref':'bad','kind':'note','title':'Bad','description':'A rejected duplicate body field.','fields':{'content':'wrong location'}}])[0],422)
    def test_receipt_replay_and_body_conflict(self):
        key=str(uuid.uuid4());ops=[{'op':'create_object','local_ref':'new','kind':'note','title':'Replay','description':'A synthetic note testing retry behavior.','body':'Exactly once.','fields':{}}]
        c,a=self.c.apply(ops,key);self.assertEqual(c,200,a);c,b=self.c.apply(ops,key);self.assertEqual(a,b)
        ops[0]['title']='Different';self.assertEqual(self.c.apply(ops,key)[0],409)
    def test_dry_run_and_transaction_rollback(self):
        ops=[{'op':'create_object','local_ref':'new','kind':'note','title':'Dry run','description':'A synthetic note testing validation.','fields':{}}]
        c,r=self.c.apply(ops,dry=True);self.assertEqual(c,200,r);self.assertEqual(self.c.call('objects/'+r['local_refs']['new'])[0],404)
        ops.append({'op':'create_object','local_ref':'bad','kind':'note','title':'','description':'Bad','fields':{}});self.assertEqual(self.c.apply(ops)[0],422)
    def test_connections_history_and_unlink(self):
        left=self.create();right=self.create();c,r=self.c.apply([{'op':'create_connection','from_id':left,'to_id':right,'from_revision':1,'to_revision':1,'kind':'depends_on','explanation':'The left record requires the right record.'}]);self.assertEqual(c,200,r)
        cid=r['changes'][0]['connection_id'];self.assertEqual(self.c.apply([{'op':'update_connection','connection_id':cid,'expected_revision':1,'from_revision':1,'to_revision':1,'explanation':'A stale endpoint edit.'}])[0],409);_,v=self.c.call('connections/'+cid);self.assertIn('metadata',v['connection']);self.assertEqual(v['connection']['from_object']['id'],left)
        c,r=self.c.apply([{'op':'delete_connection','connection_id':cid,'expected_revision':1}]);self.assertEqual(c,200,r);self.assertEqual(self.c.call('connections/'+cid)[0],404)
    def test_artifact_original_and_correction(self):
        oid=self.create();body='Original immutable source text.';c,r=self.c.apply([{'op':'save_artifact','object_id':oid,'expected_revision':1,'artifact':{'kind':'document','body':body,'media_type':'text/plain'}}]);self.assertEqual(c,200,r);aid=r['changes'][0]['artifact_id'];_,v=self.c.call('artifacts/'+aid);self.assertEqual(v['artifact']['body'],body);self.assertNotIn('bytes',v['artifact'])
        c,r=self.c.apply([{'op':'correct_evidence','object_id':oid,'expected_revision':2,'target_type':'artifact','target_id':aid,'reason':'Correct a transcription error.','representation':{'body':'Corrected representation.'}}]);self.assertEqual(c,200,r);_,v=self.c.call('artifacts/'+aid);self.assertEqual(v['artifact']['body'],body)
        _,v=self.c.call('objects/'+oid)
        corrected='Préface 東京 🌿. Exactcorrectionneedle corrected shelter.'
        code,r=self.c.apply([{'op':'correct_evidence','object_id':oid,'expected_revision':v['object']['revision'],'target_type':'artifact','target_id':aid,'reason':'Verify exact corrected search locator.','representation':{'body':corrected}}]);self.assertEqual(code,200,r)
        code,r=self.c.call('retrieve?q=Exactcorrectionneedle&scope=artifacts&neighbours=0');self.assertEqual(code,200,r)
        match=next(o['match'] for o in r['context']['objects'] if o['id']==oid)
        self.assertEqual(match['read']['resource'],'correction');self.assertEqual(match['field'],'representation.body')
        _,r=self.c.call('corrections/'+match['read']['id']);self.assertEqual(r['correction']['representation']['body'],corrected)
        self.assertTrue(match['reference'].startswith('correction:'+match['read']['id']+':'))
    def test_event_precision_and_legacy_plain_note(self):
        for value,precision in [('2024','year'),('2024-06','month'),('2024-06-15','day'),('2024-06-15T12:00:00Z','instant')]:
            oid=self.create('event',description='An event that occurred at the recorded date.',fields={'starts_at':value,'starts_at_precision':precision})
            _,o=self.c.call('objects/'+oid);self.assertEqual(o['object']['fields']['starts_at'],value)
            code,r=self.c.apply([{'op':'update_object','object_id':oid,'expected_revision':1,'title':'Updated event title'}]);self.assertEqual(code,200,r)
        for fields in [{'starts_at':'2024-02-30','starts_at_precision':'day'},{'starts_at':'2024','starts_at_precision':'day'},{'starts_at':'2025','starts_at_precision':'year','ends_at':'2024','ends_at_precision':'year'},{'starts_at':'2024-06-15T12:00:00Z','starts_at_precision':'instant','timezone':'Australia/Sydney'}]:
            code,r=self.c.apply([{'op':'create_object','local_ref':'bad','kind':'event','title':'Invalid event','description':'An invalid event date fixture.','fields':fields}]);self.assertEqual(code,422,r)
        self.create('event',description='An event whose exact date is unknown.',fields={})
        oid=self.create(fields={'intent':'idea','content_format':'plain'});code,r=self.c.apply([{'op':'update_object','object_id':oid,'expected_revision':1,'body':'Legacy plain text stays editable.'}]);self.assertEqual(code,200,r)
    def test_source_pointer_and_excerpt_locators(self):
        source=self.create('source',fields={'source_kind':'document'})
        text='Préface 東京. Exact source quote.'
        code,r=self.c.apply([{'op':'save_artifact','object_id':source,'expected_revision':1,'artifact':{'kind':'document','body':text,'media_type':'text/plain'}}]);self.assertEqual(code,200,r);aid=r['changes'][0]['artifact_id']
        code,r=self.c.apply([{'op':'update_object','object_id':source,'expected_revision':2,'fields':{'current_artifact_id':aid}}]);self.assertEqual(code,200,r)
        other=self.create('source',fields={'source_kind':'document'})
        for patch in [{'current_artifact_id':aid},{'current_artifact_id':'invalid'},{'published_at':'2024-01-01T00:00:00Z'}]:
            code,r=self.c.apply([{'op':'update_object','object_id':other,'expected_revision':1,'fields':patch}]);self.assertEqual(code,422,r)
        self.create(body='Exact source quote.',fields={'intent':'excerpt','content_format':'markdown','source_artifact_id':aid,'source_locator':{'kind':'section','label':'Original evidence'}})
        for locator in [{'kind':'section'},{'kind':'page','page':0},{'kind':'timestamp','start_ms':-1,'end_ms':3},{'kind':'text_offset','start':0,'end':2}]:
            code,r=self.c.apply([{'op':'create_object','local_ref':'bad','kind':'note','title':'Invalid excerpt','description':'An excerpt locator validation fixture.','body':'Exact source quote.','fields':{'intent':'excerpt','source_artifact_id':aid,'source_locator':locator}}]);self.assertEqual(code,422,r)
    def test_task_project_and_optional_issue(self):
        _,me=self.c.call('me');oid=self.create('task',title='Synthetic task',description='A task to verify structured project information.',body='Verify the new schema.',fields={'status':'todo','priority':'high','owner_object_id':me['id'],'due_at':'2026-11-03T12:00:00+11:00','work_kind':'code','project':'dev'})
        _,v=self.c.call('objects/'+oid);self.assertEqual(v['object']['fields']['project'],'dev');self.assertNotIn('brief_markdown',v['object']['fields'])
    def test_capture_trace_and_deletion_fence(self):
        cid=str(uuid.uuid4());itemid=str(uuid.uuid4());traceid=str(uuid.uuid4());_,me=self.c.call('me')
        payload={'contract_version':'commons.capture/1','source':{'provider':'Synthetic','namespace':'atomic-test','thread_id':cid},'batch_id':'first','chat_id':cid,'title':'Synthetic thread','coverage':{'status':'partial','messages':'visible','tools':'visible','attachments':'none','history':'current','gaps':['Synthetic acceptance only']},'items':[{'id':itemid,'source_item_id':'item1','position':0,'kind':'message','role':'human','body':'A visible synthetic request.'}],'runs':[{'id':traceid,'source_run_id':'request1','kind':'request','status':'done','actor_id':me['id'],'trace':[{'kind':'tool_call','name':'read'}]}]}
        code,r=self.c.call('capture',payload);self.assertEqual(code,200,r);_,v=self.c.call('threads/'+cid);self.assertEqual(v['items'][0]['body'],'A visible synthetic request.');_,t=self.c.call('traces/'+traceid);self.assertEqual(len(t['trace']['trace']),1)
        code,r=self.c.call('threads/'+cid+'/delete',{'expected_revision':v['object']['revision'],'acknowledge_managed_copy_deletion':True});self.assertEqual(code,200,r);self.assertEqual(self.c.call('capture',payload)[0],410)

    def test_contribution_identity_context_and_correction(self):
        _,me=self.c.call('me');owner=me['id']
        agents=[]
        for name in ['Writer Alpha','Writer Beta']:
            code,u=self.c.call('users',{'username':str(uuid.uuid4()),'title':name,'user_kind':'agent','role':'member'});self.assertEqual(code,200,u)
            code,t=self.c.call('tokens',{'account_id':u['id'],'label':'synthetic attribution','write_kinds':['note','task','thread']});self.assertEqual(code,200,t)
            agents.append((u['id'],Client(self.c.base,t['token'])))
        alpha,a=agents[0];beta,b=agents[1]
        code,h=self.c.call('users',{'username':str(uuid.uuid4()),'title':'Human Context','user_kind':'human','role':'member','password':'synthetic-human-context-password'});self.assertEqual(code,200,h);human=h['id']
        op={'op':'create_object','local_ref':'new','kind':'task','title':'Attribution task','description':'Synthetic identity and assignment acceptance.','fields':{'status':'todo','priority':'low','owner_object_id':owner,'due_at':'2026-11-05T00:00:00Z','work_kind':'general'}}
        body={'contract_version':'commons/0.1','idempotency_key':str(uuid.uuid4()),'on_behalf_of':human,'operations':[op]}
        self.assertEqual(a.call('apply',{**body,'validate_only':True})[0],200)
        code,r=a.call('apply',body);self.assertEqual(code,200,r);self.assertEqual(a.call('apply',body)[1],r);oid=r['local_refs']['new']
        self.assertEqual(a.call('apply',{**body,'on_behalf_of':owner})[0],409)
        _,v=a.call('objects/'+oid);self.assertEqual(v['object']['metadata']['created_by'],alpha);self.assertEqual(v['object']['metadata']['on_behalf_of'],human);self.assertEqual(v['object']['fields']['owner_object_id'],owner)
        def participants(oid):
            code,p=self.c.call('participants?object_ids='+oid);self.assertEqual(code,200,p);return {r['user']['id'] for r in p['participants']}
        self.assertEqual(participants(oid),{alpha,human})
        for _ in range(2): b.call('objects/'+oid);b.call('objects?q=Attribution')
        self.assertEqual(participants(oid),{alpha,human})
        code,r=b.apply([{'op':'update_object','object_id':oid,'expected_revision':1,'body':'Beta contributed.'}]);self.assertEqual(code,200,r)
        _,v=b.call('objects/'+oid);self.assertEqual(v['object']['metadata']['created_by'],alpha);self.assertEqual(v['object']['metadata']['updated_by'],beta);self.assertEqual(participants(oid),{alpha,beta,human})
        code,r=b.apply([{'op':'save_artifact','object_id':oid,'expected_revision':2,'artifact':{'kind':'document','body':'Evidence contributed by Beta.','media_type':'text/plain'}}]);self.assertEqual(code,200,r)
        _,e=b.call('artifacts/'+r['changes'][0]['artifact_id']);self.assertEqual(e['artifact']['created_by'],beta);self.assertIsNone(e['artifact']['metadata']['attribution']['on_behalf_of'])
        op.update(kind='note',fields={},title='Agent only')
        code,r=a.apply([op]);self.assertEqual(code,200,r);unknown=r['local_refs']['new'];_,v=a.call('objects/'+unknown);self.assertIsNone(v['object']['metadata']['on_behalf_of']);self.assertEqual(participants(unknown),{alpha})
        self.assertEqual(a.call('apply',{**body,'idempotency_key':str(uuid.uuid4()),'on_behalf_of':alpha})[0],422)
        self.assertEqual(a.call('apply',{**body,'idempotency_key':str(uuid.uuid4()),'on_behalf_of':str(uuid.uuid4())})[0],422)
        # Correction keeps original action and supplies a separate auditable resolution.
        change=v['history'][0]['id'];original=self.c.call('history/'+change)[1]
        corrections=[{'op':'correct_attribution','object_id':unknown,'expected_revision':1,'target_type':'object','target_id':unknown,'user_id':beta,'reason':'Synthetic evidence identifies Beta.','evidence':['synthetic:verified-client']}, {'op':'correct_attribution','object_id':unknown,'expected_revision':2,'target_type':'change','target_id':change,'user_id':beta,'reason':'Synthetic creation action correction.','evidence':['synthetic:verified-client']}]
        self.assertEqual(a.apply(corrections)[0],403)
        self.assertEqual(self.c.apply(corrections,dry=True)[0],200)
        code,r=self.c.apply(corrections);self.assertEqual(code,200,r)
        self.assertEqual(self.c.call('history/'+change)[1],original)
        _,v=self.c.call('objects/'+unknown);self.assertEqual(v['object']['metadata']['created_by'],beta);self.assertNotIn(alpha,participants(unknown));self.assertIn(beta,participants(unknown));self.assertEqual(len([x for x in v['history'] if x['action']=='attribution_correction']),2)
        direct=self.create();self.assertIn(owner,participants(direct))
        # Evidence and connection attribution corrections preserve evidence bytes.
        _,v=b.call('objects/'+oid);rev=v['object']['revision'];aid=v['artifacts'][0]['id']
        before_e=self.c.call('artifacts/'+aid)[1]['artifact']['body']
        code,r=self.c.apply([{'op':'correct_attribution','object_id':oid,'expected_revision':rev,'target_type':'artifact','target_id':aid,'user_id':alpha,'on_behalf_of':human,'reason':'Synthetic evidence creator correction.','evidence':['synthetic:artifact-receipt']}]);self.assertEqual(code,200,r)
        _,e=self.c.call('artifacts/'+aid);self.assertEqual(e['artifact']['body'],before_e);self.assertEqual(e['artifact']['created_by'],alpha);self.assertEqual(e['artifact']['metadata']['attribution']['on_behalf_of'],human)
        _,v=self.c.call('objects/'+oid);_,d=self.c.call('objects/'+direct)
        code,r=self.c.apply([{'op':'create_connection','from_id':oid,'to_id':direct,'from_revision':v['object']['revision'],'to_revision':d['object']['revision'],'kind':'about','explanation':'Synthetic attribution fixture.'}]);self.assertEqual(code,200,r)
        connection=r['changes'][0]['connection_id'];_,v=self.c.call('objects/'+oid)
        code,r=self.c.apply([{'op':'correct_attribution','object_id':oid,'expected_revision':v['object']['revision'],'target_type':'connection','target_id':connection,'user_id':alpha,'on_behalf_of':human,'reason':'Synthetic connection creator correction.','evidence':['synthetic:connection-receipt']}]);self.assertEqual(code,200,r)
        _,c=self.c.call('connections/'+connection);self.assertEqual(c['connection']['metadata']['created_by'],alpha)


    def test_evidence_correction_keeps_per_action_human_context(self):
        oid=self.create();_,me=self.c.call('me')
        code,r=self.c.call('apply',{'contract_version':'commons/0.1','idempotency_key':str(uuid.uuid4()),'on_behalf_of':me['id'],'operations':[{'op':'correct_evidence','object_id':oid,'expected_revision':1,'target_type':'object','target_id':oid,'reason':'Synthetic correction context.','representation':{'body':'Corrected contribution.'}}]});self.assertEqual(code,200,r)
        _,r=self.c.call('corrections/'+r['changes'][0]['correction_id']);self.assertEqual(r['correction']['attribution']['on_behalf_of'],me['id'])

    def test_capture_users_logs_models_and_read_noncontribution(self):
        _,me=self.c.call('me');cid=str(uuid.uuid4());traceid=str(uuid.uuid4());itemid=str(uuid.uuid4())
        code,u=self.c.call('users',{'username':str(uuid.uuid4()),'title':'Capture Agent','user_kind':'agent','role':'member'});self.assertEqual(code,200,u)
        _,t=self.c.call('tokens',{'account_id':u['id'],'label':'capture context','write_kinds':['thread']});a=Client(self.c.base,t['token'])
        payload={'contract_version':'commons.capture/1','source':{'provider':'Synthetic','namespace':'identity-test','thread_id':cid},'batch_id':'first','chat_id':cid,'title':'Identity capture','on_behalf_of':me['id'],'coverage':{'status':'partial','messages':'visible','tools':'visible','attachments':'none','history':'current','gaps':[]},'items':[{'id':itemid,'source_item_id':'log1','position':0,'kind':'log','role':'agent','body':'Observed log.','speaker_id':u['id'],'model':{'provider':'synthetic','id':'model-one'}},{'id':str(uuid.uuid4()),'source_item_id':'message2','position':1,'kind':'message','role':'agent','body':'Model changed.','speaker_id':u['id'],'model':{'provider':'synthetic','id':'model-two'}},{'id':str(uuid.uuid4()),'source_item_id':'message3','position':2,'kind':'message','role':'agent','body':'Unknown model.','speaker_id':u['id']}],'runs':[{'id':traceid,'source_run_id':'execution','kind':'pi-events','status':'done','trace':[{'event':'model_select','provider':'synthetic','id':'model-two'}]}]}
        code,r=a.call('capture',payload);self.assertEqual(code,200,r);self.assertEqual(a.call('capture',payload)[1],r)
        _,thread=self.c.call('threads/'+cid);self.assertEqual(thread['object']['metadata']['created_by'],u['id']);self.assertEqual(thread['items'][0]['model']['id'],'model-one');self.assertEqual(thread['items'][1]['model']['id'],'model-two');self.assertNotIn('model',thread['items'][2]);self.assertEqual({p['user_object_id'] for p in thread['items'][0]['participants']},{u['id'],me['id']})
        _,trace=self.c.call('traces/'+traceid);self.assertEqual(trace['trace']['actor_id'],u['id']);self.assertEqual(trace['trace']['attribution']['on_behalf_of'],me['id']);self.assertEqual({p['user_object_id'] for p in trace['trace']['participants']},{u['id'],me['id']})
        # Consulted records do not gain the capture writer as a contributor.
        consulted=self.create();payload['batch_id']='second';payload['items']=[];payload['runs'][0].update(expected_revision=1,consulted_object_ids=[consulted]);self.assertEqual(a.call('capture',payload)[0],200)
        _,p=self.c.call('participants?object_ids='+consulted);self.assertNotIn(u['id'],{r['user']['id'] for r in p['participants']})
        _,current=self.c.call('objects/'+cid)
        correction={'op':'correct_attribution','object_id':cid,'expected_revision':current['object']['revision'],'target_type':'capture_owner','target_id':cid,'user_id':me['id'],'reason':'Synthetic submitter transfer with evidence.','evidence':['synthetic:verified-owner']}
        self.assertEqual(self.c.apply([correction],dry=True)[0],200);self.assertEqual(self.c.apply([correction])[0],200)
        payload.update(batch_id='new-owner',items=[{'id':str(uuid.uuid4()),'source_item_id':'new-owner','position':3,'kind':'message','role':'human','speaker_id':me['id'],'body':'Continued with the corrected submitter.'}],runs=[])
        self.assertEqual(a.call('capture',payload)[0],403)
        code,r=self.c.call('capture',payload);self.assertEqual(code,200,r)
        _,current=self.c.call('threads/'+cid);self.assertEqual(current['object']['metadata']['created_by'],u['id']);self.assertEqual(current['chat']['owner_id'],me['id'])


if __name__=='__main__':
    from telemetry import TelemetryAcceptance
    unittest.main(verbosity=2)
