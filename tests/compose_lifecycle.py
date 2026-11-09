#!/usr/bin/env python3
"""Schema-10 lifecycle acceptance; owns only randomly named fictional installations."""
import argparse
import base64
import hashlib
import http.cookiejar
import json
import ipaddress
import os
from pathlib import Path
import platform
import secrets
import shlex
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent.parent
HELPER = str(ROOT / 'scripts/compose-lifecycle')
OVERRIDES = {}


def command(*args, env=None, expected=0, input=None):
    r = subprocess.run(args, cwd=ROOT, env=env, input=input, capture_output=True)
    if r.returncode != expected:
        diagnostic = os.environ.get('LIFECYCLE_DIAGNOSTICS')
        if diagnostic:
            Path(diagnostic).write_bytes(r.stderr)
        raise AssertionError(f'{shlex.join(args)}: exit {r.returncode}, expected {expected}; '
                             'inspect private fixture logs')
    return r.stdout


def environment(directory):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('COMMONS_', 'COMPOSE_'))}
    for line in (directory / 'config').read_text().splitlines():
        key, value = shlex.split(line)[1].split('=', 1)
        env[key] = value
    return env


def compose(directory, *args, expected=0):
    if args and args[0] == 'run':
        args = tuple(a for a in args if a != '--no-build')
    files = ['--file', str(ROOT / 'compose.yaml')]
    project = environment(directory)['COMPOSE_PROJECT_NAME']
    if project in OVERRIDES:
        files += ['--file', OVERRIDES[project]]
    return command('docker', 'compose', '--env-file', os.devnull, *files,
                   *args, env=environment(directory), expected=expected)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def configure(directory, **values):
    current = {k: v for k, v in environment(directory).items() if k.startswith(('COMMONS_', 'COMPOSE_'))}
    current.update(values)
    (directory / 'config').write_text(''.join(f'export {k}={shlex.quote(v)}\n' for k, v in current.items()))


class Client:
    def __init__(self, base, token=None):
        self.base, self.token = base, token
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, body=None, status=200, raw=False):
        headers = {'Content-Type': 'application/json', 'Origin': self.base}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        req = urllib.request.Request(self.base + '/api/' + path, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            response = self.opener.open(req, timeout=40)
        except urllib.error.HTTPError as e:
            response = e
        with response:
            data = response.read()
            assert response.code == status, (path, response.code, status)
        return data if raw else json.loads(data)

    def apply(self, operations, key=None, status=200):
        return self.request('apply', {'contract_version': 'commons/0.1',
            'idempotency_key': key or str(uuid.uuid4()), 'operations': operations}, status)


def login(directory):
    c = Client(environment(directory)['COMMONS_ORIGIN'])
    c.request('login', {'username': 'admin', 'password': (directory / 'secrets/admin_password').read_text()})
    return c


def create(kind='note', **kw):
    return {'op': 'create_object', 'local_ref': 'new', 'kind': kind,
            'title': 'Fictional workshop acceptance', 'description': 'A fictional record for lifecycle acceptance.',
            'body': 'The fictional workshop reviews suppliers before ordering.', 'fields': {}, **kw}


def indexed(c):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = c.request('retrieval/status')['index']
        if state['indexed'] > 0 and state['indexed'] == state['eligible'] and state['pending'] == state['failed'] == 0:
            return
        time.sleep(1)
    raise AssertionError('model/index did not become ready')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app-image', required=True)
    p.add_argument('--compatible-image', help='distinct reviewed schema-compatible image for populated upgrade/recovery')
    p.add_argument('--incompatible-image')
    p.add_argument('--explicit-ipam', action='store_true', help='test-only fixture Compose override in coordinator-approved 10.254.0.0/16; no daemon changes')
    p.add_argument('--verify-retrieval', action='store_true')
    p.add_argument('--verify-rich', action='store_true')
    p.add_argument('--verify-capture', action='store_true')
    p.add_argument('--metrics-output', type=Path, help='sanitized lifecycle result; no records or credentials')
    global HELPER
    args = p.parse_args()
    os.umask(0o077)
    def image(ref):
        return json.loads(command('docker', 'image', 'inspect', ref))[0]['Id']
    images = {'COMMONS_APP_IMAGE': image(args.app_image),
              'COMMONS_DB_IMAGE': image('commons-postgres:16.15-vector0.8.1'),
              'COMMONS_MODEL_IMAGE': image('commons-ollama:0.40.5')}
    compatible = image(args.compatible_image) if args.compatible_image else None
    if compatible:
        assert compatible != images['COMMONS_APP_IMAGE'], 'two tags on one image are not an upgrade'
    result = {'status': 'running', 'host': platform.platform(), 'machine': platform.machine(),
              'source_revision': command('git', 'rev-parse', 'HEAD').decode().strip(),
              'source_dirty': bool(command('git', 'status', '--porcelain').strip()),
              'images': images, 'compatible_image': compatible, 'checks': []}
    def passed(label):
        result['checks'].append(label)
        print('PASS: ' + label, flush=True)
    prefix = 'commons-lifecycle-' + uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix=prefix) as temp:
        root = Path(temp)
        first, second, restored = [root / n for n in ('first', 'demo', 'restored')]
        owned = [first, second, restored]
        if args.explicit_ipam:
            # Test-only Compose override, including helper subprocesses. No product
            # Compose/helper files, daemon pools or existing networks are changed.
            network_ids = command('docker', 'network', 'ls', '--quiet').decode().split()
            networks = json.loads(command('docker', 'network', 'inspect', *network_ids))
            occupied = [ipaddress.ip_network(c['Subnet']) for n in networks
                        for c in (n.get('IPAM', {}).get('Config') or []) if c.get('Subnet')]
            free = iter(n for n in ipaddress.ip_network('10.254.0.0/16').subnets(new_prefix=28)
                        if not any(n.overlaps(o) for o in occupied if o.version == 4))
            for directory in owned:
                override = root / (directory.name+'-networks.json')
                override.write_text(json.dumps({'networks': {name: {'ipam': {'config': [
                    {'subnet': str(next(free))}]}} for name in ('private','ingress','provision')}}))
                OVERRIDES[prefix+'-'+directory.name] = str(override)
            mapping = root/'overrides.json'
            mapping.write_text(json.dumps(OVERRIDES))
            wrapper = root/'compose-lifecycle-ipam'
            wrapper.write_text('#!/usr/bin/env python3\nimport runpy,json\n'
                + 'm=runpy.run_path('+repr(HELPER)+')\ng=m["main"].__globals__; original=g["run"]\n'
                + 'mapping=json.load(open('+repr(str(mapping))+'))\n'
                + 'def run(args, **kw):\n'
                + ' if args[:2]==["docker","compose"] and "--project-name" in args:\n'
                + '  project=args[args.index("--project-name")+1]\n'
                + '  if project not in mapping: raise ValueError("unowned project")\n'
                + '  at=args.index("--project-name");args=args[:at]+["--file",mapping[project]]+args[at:]\n'
                + ' return original(args,**kw)\n'
                + 'g["run"]=run\nm["main"]()\n')
            wrapper.chmod(0o700)
            HELPER = str(wrapper)
            result['network_override'] = 'isolated explicit /28 IPAM; private remains internal; loopback publication unchanged'
        try:
            for directory, host in [(first, 'localhost'), (second, '127.0.0.1')]:
                port = free_port()
                command(HELPER, 'init', '--config-dir', str(directory), '--project', prefix+'-'+directory.name,
                        '--port', str(port), '--origin', f'http://{host}:{port}')
                configure(directory, **images)
                original = {f.name: f.read_bytes() for f in (directory/'secrets').iterdir()}
                command(HELPER, 'init', '--config-dir', str(directory))
                assert original == {f.name: f.read_bytes() for f in (directory/'secrets').iterdir()}
                if args.verify_retrieval:
                    compose(directory, 'run', '--rm', '--no-build', 'model-provision')
                compose(directory, 'up', '-d', '--wait', '--no-build', '--pull', 'never', 'db', 'ollama')
                compose(directory, 'run', '--rm', '--no-build', 'migrate')
                compose(directory, 'run', '--rm', '--no-build', 'bootstrap')
                compose(directory, 'up', '-d', '--wait', '--no-build', '--pull', 'never', 'app')
            a, b = login(first), login(second)
            assert a.request('objects')['objects'] == b.request('objects')['objects'] == []
            assert a.request('health')['schema_version'] == 12
            assert a.request('me')['id'] != b.request('me')['id']
            assert len({v['table'] for v in a.request('schema')['columns']}) == 10
            passed('two empty schema10 installs; independent users/secrets, repeated init preserves secrets')
            # Fictional demo is explicit ordinary API writes in its own installation.
            demo_id = b.apply([create(title='Fictional demo workshop')])['local_refs']['new']
            assert a.request('objects')['objects'] == []
            a.request('objects/'+demo_id, status=404)
            password = secrets.token_urlsafe(24)
            user = a.request('users', {'username': 'workshop', 'title': 'Fictional Workshop Operator',
                'password': password, 'user_kind': 'human', 'role': 'member'})['id']
            member = Client(a.base)
            member.request('login', {'username': 'workshop', 'password': password})
            cred = member.request('tokens', {'label': 'Fictional lifecycle', 'write_kinds': ['note','source','entity','task','thread']})
            agent = Client(a.base, cred['token'])
            Client(b.base, cred['token']).request('me', status=401)
            passed('separate fictional demo; empty real base unaffected; cross-install token/read isolation')
            key = str(uuid.uuid4())
            op = create()
            receipt = agent.apply([op], key)
            oid = receipt['local_refs']['new']
            source = agent.apply([create('source', title='Fictional supplier policy', fields={'source_kind':'document'})])['local_refs']['new']
            body = 'Exact fictional evidence αβγ.\n' * (50000 if args.verify_rich else 10)
            art = agent.apply([{'op':'save_artifact','object_id':source,'expected_revision':1,
                'artifact':{'kind':'document','body':body,'media_type':'text/plain','semantic_indexing_enabled':False}}])['changes'][0]['artifact_id']
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAADUlEQVR4nGP4zwAE/wEHAAH/4iOeWQAAAABJRU5ErkJggg==')
            binary = agent.apply([{'op':'save_artifact','object_id':source,'expected_revision':2,
                'artifact':{'kind':'image','media_type':'image/png','image_base64':base64.b64encode(png).decode(),'semantic_indexing_enabled':False}}])['changes'][0]['artifact_id']
            agent.apply([{'op':'create_connection','from_id':oid,'to_id':source,'from_revision':1,'to_revision':3,
                          'kind':'derived_from','explanation':'The fictional rationale follows this fictional policy.'}])
            task = agent.apply([create('task', title='Fictional supplier review', fields={
                'status':'todo','priority':'medium','owner_object_id':user,'due_at':'2026-11-04T12:00:00+11:00',
                'work_kind':'general','project':'procurement'})])['local_refs']['new']
            supplier = agent.apply([create('entity', title='Fictional Castor Parts', fields={'entity_kind':'supplier'})])['local_refs']['new']
            configure(first, COMMONS_INSTALLATION_NAME='Fictional Harbour Workshop', COMMONS_THEME='blue-slate')
            compose(first, 'up', '-d', '--wait', '--no-build', '--pull', 'never', 'app')
            assert agent.request('health')['branding'] == {'name':'Fictional Harbour Workshop','theme':'blue-slate'}
            assert agent.request('objects/'+task)['object']['fields']['project'] == 'procurement'
            assert agent.request('objects/'+supplier)['object']['fields']['entity_kind'] == 'supplier'
            passed('supported branding and procurement mapping; exact evidence/binary and linked records created')
            gone_request = None
            if args.verify_capture:
                cid, tid = str(uuid.uuid4()), str(uuid.uuid4())
                gone_request = {'contract_version':'commons.capture/1','source':{'provider':'synthetic','namespace':prefix,'thread_id':cid},
                    'batch_id':'first','chat_id':cid,'title':'Fictional deleted thread',
                    'coverage':{'status':'partial','messages':'visible','tools':'none','attachments':'none','history':'current','gaps':[]},
                    'items':[{'id':str(uuid.uuid4()),'source_item_id':'one','position':0,'kind':'message','role':'human','body':'Fictional text removed before snapshot.'}],
                    'runs':[{'id':tid,'source_run_id':'request','kind':'request','status':'done','trace':[{'kind':'tool_call','name':'fictional'}]}]}
                r = agent.request('capture', gone_request)
                agent.request('threads/'+cid+'/delete', {'expected_revision':r['revision'],'acknowledge_managed_copy_deletion':True})
                agent.request('capture', gone_request, status=410)
            paths = ['objects/'+x for x in (oid,source,task,supplier)] + ['users/'+user,'artifacts/'+art,'artifacts/'+binary]
            snapshots = {path: agent.request(path) for path in paths}
            def exact(c):
                for path, value in snapshots.items():
                    assert c.request(path) == value, 'changed snapshot: '+path
                assert c.request('artifacts/'+art+'/content', raw=True) == body.encode()
                assert c.request('artifacts/'+binary+'/content', raw=True) == png
                assert c.apply([op], key) == receipt
                if gone_request:
                    c.request('capture', gone_request, status=410)
            compose(first, 'restart', 'app', 'db', 'ollama')
            compose(first, 'up', '-d', '--wait', '--no-build', 'app')
            exact(agent)
            compose(first, 'down')
            compose(first, 'up', '-d', '--wait', '--no-build', '--pull', 'never', 'app','ollama')
            exact(agent)
            passed('restart and container recreation preserve exact content/history/links/users/credentials/receipts')
            if compatible:
                for target in (compatible, images['COMMONS_APP_IMAGE']):
                    compose(first,'stop','app')
                    configure(first, COMMONS_APP_IMAGE=target)
                    compose(first,'run','--rm','--no-build','migrate')
                    compose(first,'up','-d','--wait','--no-build','--pull','never','app')
                    exact(agent)
                    assert agent.request('health')['branding']['name'] == 'Fictional Harbour Workshop'
                    agent.apply([create(title='Fictional new write after image update')])
                passed('distinct compatible image update and recovery preserve populated customisation and new writes')
            if args.incompatible_image:
                configure(first, COMMONS_APP_IMAGE=image(args.incompatible_image))
                compose(first,'up','-d','--no-build','--pull','never','app')
                time.sleep(4)
                # Readiness must reject the old schema; restore only the pinned candidate.
                assert json.loads(compose(first,'ps','--format','json','app'))['Health'] != 'healthy'
                configure(first, **images)
                compose(first,'up','-d','--wait','--no-build','--pull','never','app')
                exact(agent)
                passed('incompatible binary refusal and pinned candidate recovery')
            bundle = root/'backup'
            command(HELPER,'backup','--config-dir',str(first),'--output',str(bundle))
            command(HELPER,'backup','--config-dir',str(first),'--output',str(bundle),expected=1)
            manifest = json.loads((bundle/'manifest.json').read_text())
            assert manifest['images']['app']['id'] == images['COMMONS_APP_IMAGE']
            assert (bundle.stat().st_mode & 0o077) == 0
            restore = [HELPER,'restore','--bundle',str(bundle),'--config-dir',str(restored),
                       '--project',prefix+'-restored','--port',str(free_port())]
            command(*restore,expected=1)
            dump = bundle/'database.dump'
            original_dump = dump.read_bytes(); dump.write_bytes(original_dump+b'corrupt')
            command(*restore,'--accept-historical-state',expected=1)
            dump.write_bytes(original_dump)
            # Post-snapshot changes must stay out of historical restore.
            agent.apply([{'op':'update_object','object_id':task,'expected_revision':1,'body':'A later source-only fictional change.'}])
            member.request('tokens/'+cred['id']+'/revoke', {})
            agent.request('me',status=401)
            command(*restore,'--accept-historical-state')
            assert set(compose(restored,'ps','--services','--status','running').decode().split()) == {'db'}
            command(*restore,'--accept-historical-state',expected=1)
            compose(restored,'run','--rm','--no-build','bootstrap',expected=1)
            if args.verify_retrieval:
                compose(restored,'run','--rm','--no-build','model-provision')
            compose(restored,'up','-d','--wait','--no-build','--pull','never','ollama','app')
            recovered = Client(environment(restored)['COMMONS_ORIGIN'],cred['token'])
            exact(recovered)
            assert recovered.request('health')['branding'] == {'name':'Fictional Harbour Workshop','theme':'blue-slate'}
            recovered.apply([create(title='Fictional new write after restore')])
            assert member.request('objects/'+task)['object']['body'] == 'A later source-only fictional change.'
            assert b.request('objects/'+demo_id)['object']['title'] == 'Fictional demo workshop'
            passed('private snapshot, corruption/overwrite guards, DB-only isolated restore, exact bytes/identity/receipts and new write')
            passed('historical snapshot revives later-revoked token as warned; source and separate demo remain unchanged')
            if args.verify_capture:
                passed('pre-snapshot capture deletion barrier survives restore and refuses replay')
            if args.verify_retrieval:
                indexed(recovered)
                assert recovered.request('retrieve?q=fictional')['mode'] == 'hybrid'
                compose(restored,'stop','ollama')
                recovered.apply([create(title='Fictional outage recovery note')])
                assert recovered.request('retrieve?q=fictional')['mode'] == 'lexical_only'
                compose(restored,'up','-d','--wait','--no-build','ollama')
                indexed(recovered)
                assert recovered.request('retrieve?q=fictional')['mode'] == 'hybrid'
                passed('restore model reprovision, outage lexical fallback/write and model/index recovery')
            result['status'] = 'passed'
        except BaseException as e:
            result['status'], result['failure_type'] = 'failed', type(e).__name__
            raise
        finally:
            for directory in reversed(owned):
                if (directory/'config').exists():
                    compose(directory,'--profile','tools','down','--volumes','--remove-orphans')
                    project = environment(directory)['COMPOSE_PROJECT_NAME']
                    for resource in (['ps','--all'], ['network','ls'], ['volume','ls']):
                        assert not command('docker',*resource,'--quiet','--filter',
                            'label=com.docker.compose.project='+project).strip(), 'fixture resource remained after cleanup'
            result['owned_fixture_cleanup'] = True
            if args.metrics_output:
                args.metrics_output.parent.mkdir(parents=True,exist_ok=True)
                args.metrics_output.write_text(json.dumps(result,indent=2)+'\n')


if __name__ == '__main__':
    main()
