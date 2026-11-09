#!/usr/bin/env python3
"""Populated schema10->12 upgrade and two-installation isolation, synthetic only."""
import argparse
import importlib.util
import ipaddress
import json
from pathlib import Path
import runpy
import secrets
import subprocess
import tempfile
from types import SimpleNamespace
import uuid

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('lifecycle',ROOT/'tests/compose_lifecycle.py')
l=importlib.util.module_from_spec(spec);spec.loader.exec_module(l)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-image',required=True)
    parser.add_argument('--app-image',required=True)
    args=parser.parse_args()
    helper=runpy.run_path(str(ROOT/'scripts/compose-lifecycle'))
    report={'status':'failed','checks':[],'cleanup':False}
    results=ROOT/'tests/e2e/results'/('deletion-search-lifecycle-'+uuid.uuid4().hex);results.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='commons-upgrade-isolation-') as temp:
        directories=[Path(temp)/name for name in ['upgrade','independent']]
        networks=json.loads(subprocess.check_output(['docker','network','inspect',*subprocess.check_output(['docker','network','ls','-q'],text=True).split()]))
        used=[ipaddress.ip_network(c['Subnet']) for n in networks for c in (n.get('IPAM',{}).get('Config') or []) if c.get('Subnet')]
        available=[n for n in ipaddress.ip_network('10.254.0.0/16').subnets(new_prefix=28) if not any(n.overlaps(o) for o in used if o.version==4)]
        secrets.SystemRandom().shuffle(available)
        try:
            for directory,image in zip(directories,[args.baseline_image,args.app_image]):
                project='commons-upgrade-test-'+uuid.uuid4().hex[:10]
                origin='http://127.0.0.1:'+str(l.free_port())
                helper['init'](SimpleNamespace(config_dir=directory,project=project,port=int(origin.rsplit(':',1)[1]),origin=origin))
                override=Path(temp)/(directory.name+'-networks.json')
                override.write_text(json.dumps({'networks':{name:{'ipam':{'config':[{'subnet':str(available.pop())}]}} for name in ['private','ingress']}}))
                l.OVERRIDES[project]=str(override)
                l.configure(directory,COMMONS_APP_IMAGE=image)
                l.compose(directory,'up','-d','--wait','db')
                l.compose(directory,'run','--rm','migrate');l.compose(directory,'run','--rm','bootstrap')
                l.compose(directory,'up','-d','--no-deps','--wait','app')
            first,second=directories
            a,b=l.login(first),l.login(second)
            assert a.request('health')['schema_version']==10 and b.request('health')['schema_version']==12
            note=a.apply([l.create(body='Independent synthetic upgrade knowledge.')])['local_refs']['new']
            thread,item=str(uuid.uuid4()),str(uuid.uuid4())
            envelope=dict(contract_version='commons.capture/1',source=dict(provider='Synthetic',namespace='upgrade',thread_id=thread),chat_id=thread,batch_id='initial',title='Synthetic upgrade conversation',coverage=dict(status='partial',messages='visible',tools='visible',attachments='none',history='current',gaps=[]),items=[dict(id=item,source_item_id='message',position=0,kind='message',role='human',body='Upgradeconversationneedle from original stored evidence.')],runs=[])
            a.request('capture',envelope)
            before=a.request('objects/'+note);captured=a.request('threads/'+thread)
            assert a.request('retrieve?q=Upgradeconversationneedle&scope=objects')['primary_count']==0
            token=a.request('tokens',dict(label='Synthetic upgrade isolation',write_kinds=['note']))['token']
            other=l.Client(b.base,token)
            other.request('me',status=401);other.request('retrieve?q=Upgradeconversationneedle&scope=threads',status=401)
            b.request('objects/'+note,status=404);b.request('threads/'+thread,status=404)
            assert b.request('retrieve?q=Upgradeconversationneedle&scope=all')['primary_count']==0
            report['checks'].append('independent credential, Object, Thread and search isolation across two real installations')
            l.compose(first,'stop','app');l.configure(first,COMMONS_APP_IMAGE=args.app_image)
            l.compose(first,'run','--rm','migrate');l.compose(first,'up','-d','--no-deps','--wait','app')
            assert a.request('health')['schema_version']==12
            assert a.request('objects/'+note)==before and a.request('threads/'+thread)==captured
            result=a.request('retrieve?q=Upgradeconversationneedle&scope=threads&neighbours=0')
            assert result['primary_count']==1 and result['context']['objects'][0]['id']==thread
            read=result['context']['objects'][0]['match']['read']
            from urllib.parse import urlencode
            assert 'Upgradeconversationneedle' in a.request('threads/'+thread+'/text?'+urlencode({k:v for k,v in read.items() if k not in ['id','resource']}))['text']
            report['checks'].append('populated schema10->12 explicit upgrade preserves exact independent Object and captured Thread content; existing message becomes searchable with exact window')
            l.Client(a.base,token).apply([dict(op='delete_object',object_id=note,expected_revision=before['object']['revision'],acknowledge_owned_content_deletion=True)])
            a.request('objects/'+note,status=410);assert a.request('threads/'+thread)==captured
            other.apply([dict(op='delete_object',object_id=note,expected_revision=1,acknowledge_owned_content_deletion=True)],status=401)
            report['checks'].append('existing scoped credential gains supported deletion after upgrade; independent conversation survives; other installation denies mutation')
            report['status']='passed'
        finally:
            for directory in directories:
                if (directory/'config').exists():l.compose(directory,'down','--volumes','--remove-orphans')
            report['cleanup']=True
            (results/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({**report,'results':str(results)},indent=2))

if __name__=='__main__':main()
