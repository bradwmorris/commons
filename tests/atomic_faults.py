"""Focused schema-10 regression/fault checks. Synthetic installation ONLY."""
import importlib.util,json,os,subprocess,uuid
from pathlib import Path
sp=importlib.util.spec_from_file_location('atomic_acceptance',Path(__file__).with_name('atomic.py'));m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
s=json.loads(Path(os.environ['COMMONS_ATOMIC_FIXTURE']).read_text());c=m.Client(s['origin']);assert c.call('login',{'username':'alice','password':s['password']})[0]==200
_,me=c.call('me')
def sql(statement):
    r=subprocess.run(['docker','exec','-i',s['container'],'psql','-U',s.get('postgres_user','atomic'),'-d',s['database_url'].rsplit('/',1)[1],'-X','-v','ON_ERROR_STOP=1','-tA'],input=statement,text=True,capture_output=True)
    assert r.returncode==0,r.stderr
    return r.stdout.strip()
def create(kind='note',**kw):
    op={'op':'create_object','local_ref':'n','kind':kind,'title':'Synthetic fault fixture','description':'A synthetic note for regression checks.','body':'Independent authored knowledge must survive.','fields':{}};op.update(kw);code,r=c.apply([op]);assert code==200,r;return r['local_refs']['n']
def capture(cid,batch='first',runs=None,items=None):
    return {'contract_version':'commons.capture/1','source':{'provider':'Synthetic','namespace':'faults','thread_id':cid},'batch_id':batch,'chat_id':cid,'title':'Synthetic captured thread','coverage':{'status':'partial','messages':'visible','tools':'visible','attachments':'none','history':'current','gaps':[]},'items':items or [],'runs':runs or []}
# Original imports may retain missing dates/inactive historical owners on unrelated edits.
code,u=c.call('users',{'username':'historic-'+uuid.uuid4().hex[:8],'title':'Historical Agent','user_kind':'agent','role':'member'});assert code==200,u
owner=u['id'];task=create('task',fields={'status':'todo','priority':'high','owner_object_id':owner,'due_at':'2026-11-03T12:00:00Z','work_kind':'general'})
change=str(uuid.uuid4());sql(f"UPDATE users SET active=false WHERE id='{owner}'; UPDATE objects SET fields=fields-'due_at',provenance=jsonb_build_object('original_change_id','{change}') WHERE id='{task}'; INSERT INTO changes(id,kind,object_id,target_type,target_id,payload) VALUES('{change}','migration_original','{task}','object','{task}',jsonb_build_object('fields',jsonb_build_object('owner_object_id','{owner}'),'import_provenance',jsonb_build_object('import','synthetic')));")
code,r=c.apply([{'op':'update_object','object_id':task,'expected_revision':1,'title':'Historical Task remains editable'}]);assert code==200,r
_,r=c.call('objects/'+task);assert 'due_at' not in r['object']['fields'];assert r['object']['fields']['owner_object_id']==owner
bad={'op':'create_object','local_ref':'bad','kind':'task','title':'New Task','description':'A task with no date.','body':'Required detail.','fields':{'status':'todo','priority':'high','owner_object_id':me['id'],'work_kind':'general'}};assert c.apply([bad])[0]==422
# Historical-only reads remain available but listings/retrieval exclude the row.
historical=create(title='Historical excluded fixture');sql(f"UPDATE objects SET provenance=provenance||jsonb_build_object('historical_only',true) WHERE id='{historical}';")
assert c.call('objects/'+historical)[0]==200
_,r=c.call('objects?q=Historical+excluded+fixture');assert all(o['id']!=historical for o in r['objects'])
# Deletion includes NULL-owner trace/connection changes, dependent traces, copies;
# an independently authored Note linked to the Thread must remain intact.
root=str(uuid.uuid4());other=str(uuid.uuid4());direct=str(uuid.uuid4());dependent=str(uuid.uuid4());marker='SYNTHETIC_RAW_DELETE_MARKER'
run={'id':direct,'source_run_id':'direct','kind':'request','status':'done','input':{'body':marker},'trace':[{'body':marker}]}
code,r=c.call('capture',capture(root,runs=[run],items=[{'id':str(uuid.uuid4()),'source_item_id':'raw1','position':0,'kind':'message','role':'human','body':marker}]));assert code==200,r
run2={'id':dependent,'source_run_id':'dependent','kind':'request','status':'done','input':{'body':marker},'trace':[{'body':marker}],'consulted_object_ids':[root]}
assert c.call('capture',capture(other,runs=[run2]))[0]==200
note=create();code,r=c.apply([{'op':'create_connection','from_id':note,'to_id':root,'from_revision':1,'to_revision':2,'kind':'derived_from','explanation':marker}]);assert code==200,r
cid=r['changes'][0]['connection_id'];nullhistory=str(uuid.uuid4());connhistory=str(uuid.uuid4())
sql(f"INSERT INTO changes(id,kind,target_type,target_id,payload) VALUES('{nullhistory}','history','run','{dependent}',jsonb_build_object('after_state','{marker}')),('{connhistory}','connection_original','connection','{cid}',jsonb_build_object('explanation','{marker}'));")
_,v=c.call('threads/'+root);code,r=c.call('threads/'+root+'/delete',{'expected_revision':v['object']['revision'],'acknowledge_managed_copy_deletion':True});assert code==200,r
for hid in [nullhistory,connhistory]:
    code,r=c.call('history/'+hid);assert code==200,r;assert marker not in json.dumps(r)
_,r=c.call('objects/'+note);assert r['object']['body']=='Independent authored knowledge must survive.'
_,r=c.call('connections/'+cid);assert marker not in json.dumps(r)
assert c.call('traces/'+dependent)[0]==404
assert c.call('capture',capture(other,batch='resurrect',runs=[dict(run2,expected_revision=1)]))[0]==410
assert sql(f"SELECT count(*) FROM trace_items WHERE trace_id IN('{direct}','{dependent}')")=='0'
print('Passed: imported Task missing-date/owner allowance, strict new Task date, historical-only read/list, deletion NULL-owner changes/dependent trace/connection closure, independent authored Note preservation, trace replay fence')

# Ordinary deletion removes owned bytes and derived entries, retaining only a tombstone/audit.
ordinary=create(title='Ordinary erasure fixture',body=marker)
code,r=c.apply([dict(op='save_artifact',object_id=ordinary,expected_revision=1,artifact=dict(body=marker,title=marker,capture_outcome='incomplete',capture_reason=marker,metadata=dict(filename=marker)))]);assert code==200,r
owned_artifact=r['changes'][0]['artifact_id']
sql(f"BEGIN; SELECT pg_advisory_xact_lock(8138001); DELETE FROM chunks WHERE object_id='{ordinary}'; INSERT INTO chunks(id,object_id,ordinal,reference,body,input_hash,object_revision,space) VALUES('{uuid.uuid4()}','{ordinary}',0,'synthetic','{marker}','synthetic',2,'synthetic'); COMMIT;")
assert c.apply([dict(op='delete_object',object_id=ordinary,expected_revision=2,acknowledge_owned_content_deletion=True)])[0]==200
assert sql(f"SELECT count(*) FROM chunks WHERE object_id='{ordinary}'")=='0'
assert sql(f"SELECT count(*) FROM artifacts WHERE id='{owned_artifact}' AND body IS NULL AND bytes IS NULL AND title IS NULL AND capture_reason IS NULL AND metadata='{{}}'::jsonb AND deleted_at IS NOT NULL")=='1'
assert marker not in sql(f"SELECT payload FROM changes WHERE object_id='{ordinary}'")
assert c.call('objects/'+ordinary)[0]==410
print('Passed: ordinary deletion erases owned artifact metadata/content, derived chunks and prior content history; tombstone remains inaccessible')
# Force the worker/deletion interleaving that previously deadlocked: the worker
# holds its admission lock before inserting a child row with an Object FK lock.
racing=create(title='Synthetic concurrent erasure fixture')
worker_sql=f"BEGIN; SELECT pg_advisory_xact_lock(8138001); SELECT 'SYNTHETIC_WORKER_READY'; SELECT pg_sleep(1); DELETE FROM chunks WHERE object_id='{racing}'; INSERT INTO chunks(id,object_id,ordinal,reference,body,input_hash,object_revision,space) VALUES('{uuid.uuid4()}','{racing}',0,'synthetic','synthetic worker content','synthetic',1,'synthetic'); COMMIT;"
worker=subprocess.Popen(['docker','exec','-i',s['container'],'psql','-U',s.get('postgres_user','atomic'),'-d',s['database_url'].rsplit('/',1)[1],'-X','-v','ON_ERROR_STOP=1','-tA'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
worker.stdin.write(worker_sql+'\n');worker.stdin.close()
try:
    for line in worker.stdout:
        if line.strip()=='SYNTHETIC_WORKER_READY':break
    else:raise AssertionError('synthetic worker did not acquire its lock')
    race_delete=dict(op='delete_object',object_id=racing,expected_revision=1,acknowledge_owned_content_deletion=True);race_key=str(uuid.uuid4())
    code,r=c.apply([race_delete],key=race_key);assert code==200,r
    race_receipt=r
    assert worker.wait(timeout=15)==0,worker.stderr.read()
    assert sql(f"SELECT count(*) FROM chunks WHERE object_id='{racing}'")=='0'
    assert c.call('objects/'+racing)[0]==410
finally:
    if worker.poll() is None:worker.terminate();worker.wait(timeout=5)
    worker.stdout.close();worker.stderr.close()
print('Passed: forced worker-FK/deletion concurrency completes without deadlock or stale chunk resurrection')

# A completed request's receipt does not need the worker lock. Keep that lock
# held until the HTTP replay returns: a regression fails at the client's timeout.
worker=subprocess.Popen(['docker','exec','-i',s['container'],'psql','-U',s.get('postgres_user','atomic'),'-d',s['database_url'].rsplit('/',1)[1],'-X','-v','ON_ERROR_STOP=1','-tA'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
worker.stdin.write("BEGIN; SELECT pg_advisory_xact_lock(8138001); SELECT 'SYNTHETIC_RECEIPT_READY';\n");worker.stdin.flush()
try:
    for line in worker.stdout:
        if line.strip()=='SYNTHETIC_RECEIPT_READY':break
    else:raise AssertionError('synthetic receipt blocker did not acquire its lock')
    code,replayed=c.apply([race_delete],key=race_key);assert code==200 and replayed==race_receipt,replayed
finally:
    worker.stdin.write('COMMIT;\n');worker.stdin.close()
    assert worker.wait(timeout=15)==0,worker.stderr.read()
    worker.stdout.close();worker.stderr.close()
print('Passed: completed deletion replay returns its exact receipt while the indexing lock remains held')
