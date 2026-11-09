#!/usr/bin/env python3
"""Bounded synthetic long-Thread search/index scaling regression, never live storage."""
import argparse
import importlib.util
import ipaddress
import json
from pathlib import Path
import runpy
import secrets
import subprocess
import tempfile
import time
from types import SimpleNamespace
import uuid

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('lifecycle',ROOT/'tests/compose_lifecycle.py')
l=importlib.util.module_from_spec(spec);spec.loader.exec_module(l)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--app-image',required=True)
    args=parser.parse_args();helper=runpy.run_path(str(ROOT/'scripts/compose-lifecycle'))
    results=ROOT/'tests/e2e/results'/('retrieval-scale-'+uuid.uuid4().hex);results.mkdir(parents=True)
    report=dict(status='failed',cleanup=False,image=args.app_image)
    with tempfile.TemporaryDirectory(prefix='commons-scale-') as temp:
        directory=Path(temp)/'installation';project='commons-scale-test-'+uuid.uuid4().hex[:10]
        origin='http://127.0.0.1:'+str(l.free_port())
        helper['init'](SimpleNamespace(config_dir=directory,project=project,port=int(origin.rsplit(':',1)[1]),origin=origin))
        networks=json.loads(subprocess.check_output(['docker','network','inspect',*subprocess.check_output(['docker','network','ls','-q'],text=True).split()]))
        used=[ipaddress.ip_network(c['Subnet']) for n in networks for c in (n.get('IPAM',{}).get('Config') or []) if c.get('Subnet')]
        available=[n for n in ipaddress.ip_network('10.254.0.0/16').subnets(new_prefix=28) if not any(n.overlaps(o) for o in used if o.version==4)];secrets.SystemRandom().shuffle(available)
        override=Path(temp)/'networks.json';override.write_text(json.dumps({'networks':{name:{'ipam':{'config':[{'subnet':str(available.pop())}]}} for name in ['private','ingress']}}));l.OVERRIDES[project]=str(override)
        l.configure(directory,COMMONS_APP_IMAGE=args.app_image)
        def sql(query):
            return l.compose(directory,'exec','-T','db','psql','-XAt','-U','postgres','-d','commons','-v','ON_ERROR_STOP=1','-c',query).decode().strip()
        try:
            l.compose(directory,'up','-d','--wait','db');l.compose(directory,'run','--rm','migrate');l.compose(directory,'run','--rm','bootstrap');l.compose(directory,'up','-d','--wait','--no-deps','app')
            c=l.login(directory);threads=[]
            # Multiple long sources and many existing chunks are needed: tiny
            # fixtures hide correlated re-aggregation and source-hash work.
            for n in range(40):
                thread=str(uuid.uuid4());threads.append(thread)
                items=[dict(id=str(uuid.uuid4()),source_item_id=str(i),position=i,kind='message',role='human',body=('Fictional synthetic search and indexing scale evidence. '*110)+((' Scaleonlyneedle' if n==0 and i==9 else ''))) for i in range(10)]
                c.request('capture',dict(contract_version='commons.capture/1',source=dict(provider='Synthetic',namespace='scale',thread_id=thread),chat_id=thread,batch_id='initial',title='Synthetic scale discussion '+str(n),coverage=dict(status='partial',messages='visible',tools='visible',attachments='none',history='current',gaps=[]),items=items,runs=[]))
            # Index fault injection only, in this owned synthetic DB. Original
            # records/captures were all seeded through the authenticated API.
            ids=','.join("'"+x+"'::uuid" for x in threads)
            sql("BEGIN; SELECT pg_advisory_xact_lock(8138001); INSERT INTO chunks(id,object_id,ordinal,reference,body,input_hash,object_revision,space) SELECT md5(o::text||n::text)::uuid,o,100000+n,'synthetic-stale-'||n,repeat('Synthetic old derived content. ',30),'stale',1,'embeddinggemma2-c21dd30c-768-atomic500-artifact500-v2' FROM unnest(ARRAY["+ids+"]) o CROSS JOIN generate_series(1,150) n; COMMIT;")
            started=time.monotonic();result=c.request('retrieve?q=Scaleonlyneedle&scope=threads&neighbours=0');report['global_search_seconds']=time.monotonic()-started
            assert threads[0] in [o['id'] for o in result['context']['objects']]
            started=time.monotonic();remaining=6000
            while remaining and time.monotonic()-started<45:
                remaining=int(sql("SELECT count(*) FROM chunks WHERE reference LIKE 'synthetic-stale-%'"))
                if remaining:time.sleep(.2)
            report.update(stale_cleanup_seconds=time.monotonic()-started,stale_remaining=remaining,threads=40,visible_items=400,injected_stale_chunks=6000)
            assert remaining==0,'stale chunk reconciliation exceeded the bounded fixture deadline'
            report['status']='passed'
        finally:
            l.compose(directory,'down','--volumes','--remove-orphans');report['cleanup']=True
            (results/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({**report,'results':str(results)},indent=2))
if __name__=='__main__':main()
