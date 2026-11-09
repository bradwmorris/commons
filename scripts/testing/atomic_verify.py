"""Atomic-schema acceptance in a disposable, least-privilege Compose installation."""
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import runpy
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import uuid
import unittest

ROOT = Path(__file__).resolve().parents[2]

def verify(args):
    lifecycle = runpy.run_path(str(ROOT / 'scripts/compose-lifecycle'))
    run_id = uuid.uuid4().hex
    results = ROOT / 'tests/e2e/results' / ('atomic-' + run_id)
    results.mkdir(parents=True)
    report = {'status': 'failed', 'checks': [], 'cleanup': False, 'schema': 12}
    image = args.app_image or 'commons:verify-' + run_id
    def command(argv, env=None):
        subprocess.run(list(map(str, argv)), cwd=ROOT, env=env, check=True)
    if not args.app_image:
        command(['docker', 'build', '-t', image, '.'])
    with tempfile.TemporaryDirectory(prefix='commons-atomic-') as directory:
        config = (Path(directory) / 'config').resolve()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        lifecycle['init'](SimpleNamespace(config_dir=config, project='commons-test-' + run_id[:12], port=port, origin=origin))
        values = lifecycle['read_config'](config)
        values.update(COMMONS_APP_IMAGE=image, COMMONS_ADMIN_USER='alice', COMMONS_ADMIN_NAME='Alice Synthetic')
        lifecycle['write_config'](config, values)
        network_ids = subprocess.check_output(['docker','network','ls','-q'], text=True).split()
        networks = json.loads(subprocess.check_output(['docker','network','inspect',*network_ids]))
        used = [ipaddress.ip_network(c['Subnet']) for n in networks for c in (n.get('IPAM',{}).get('Config') or []) if c.get('Subnet')]
        available = [n for n in ipaddress.ip_network('10.254.0.0/16').subnets(new_prefix=28) if not any(n.overlaps(u) for u in used if n.version == u.version)][:2]
        if len(available) != 2: raise RuntimeError('No unused synthetic network range')
        override = Path(directory)/'networks.json'
        override.write_text(json.dumps({'networks': {name:{'ipam':{'config':[{'subnet':str(subnet)}]}} for name,subnet in zip(['private','ingress'],available)}}))
        def compose(*argv):
            env = {k:v for k,v in os.environ.items() if not k.startswith(('COMMONS_', 'COMPOSE_'))}
            env.update(values)
            result = subprocess.run(['docker','compose','--env-file',os.devnull,'--project-directory',str(ROOT),'--file',str(ROOT/'compose.yaml'),'--file',str(override),'--project-name',values['COMPOSE_PROJECT_NAME'],*argv], env=env, capture_output=True)
            with (results/'commands.log').open('ab') as log:
                log.write(result.stderr)
            if result.returncode:
                raise RuntimeError('Compose failed: ' + ' '.join(argv) + '; inspect commands.log')
            return result.stdout
        spec = importlib.util.spec_from_file_location('atomic_http', ROOT / 'tests/atomic.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        client = module.Client(origin)
        password = (config / 'secrets/admin_password').read_text().strip()
        try:
            compose('up', '-d', 'db')
            compose('run', '--rm', 'migrate')
            compose('run', '--rm', 'bootstrap')
            # The model is deliberately absent: lexical/degraded behavior is honest.
            compose('up', '-d', '--no-deps', 'app')
            for _ in range(150):
                try:
                    if client.call('health')[0] == 200: break
                except OSError: pass
                time.sleep(.2)
            else: raise RuntimeError('packaged app readiness failed')
            assert client.call('login', {'username':'alice', 'password':password})[0] == 200
            env = dict(os.environ, COMMONS_TEST_ORIGIN=origin, COMMONS_TEST_PASSWORD=password)
            command([sys.executable, '-B', 'tests/atomic.py'], env)
            command(['uv', 'run', '--locked', 'python', '-B', 'tests/deletion_search_tools.py'], env)
            report['checks'].append('real three-tool deletion/retry and captured conversation window journey')
            report['checks'].append(str(unittest.TestLoader().loadTestsFromModule(module).countTestCases()) + ' authenticated schema-12 API cases under commons_app role')
            container = compose('ps', '-q', 'db').decode().strip()
            state = dict(origin=origin, password=password, container=container, database_url='synthetic/commons', postgres_user='postgres')
            state_path = Path(directory) / 'fixture.json'; state_path.write_text(json.dumps(state))
            env.update(COMMONS_ATOMIC_FIXTURE=str(state_path), COMMONS_ATOMIC_RESULTS=str(results))
            command([sys.executable, '-B', 'tests/atomic_faults.py'], env)
            report['checks'].append('historical Task and deletion-closure fault regressions')
            _, me = client.call('me')
            code, result = client.apply([dict(op='create_object',local_ref='task',kind='task',title='Synthetic task',description='A task for testing the compact task editor.',body='Supporting task detail.',fields=dict(status='todo',priority='high',owner_object_id=me['id'],due_at='2026-11-03T12:00:00Z',work_kind='general'))])
            assert code == 200, result
            command(['node', 'tests/e2e/atomic-check.mjs'], env)
            report['checks'].append('nine desktop/narrow Chromium checks plus native Trace journeys')
            sentinel = result['local_refs']['task']
            before = client.call('objects/' + sentinel)
            # Browser intentionally changed the body, so snapshot after that edit.
            compose('stop', 'app', 'db'); compose('up', '-d', 'db'); compose('up', '-d', '--no-deps', 'app')
            for _ in range(150):
                try:
                    if client.call('health')[0] == 200: break
                except OSError: pass
                time.sleep(.2)
            else: raise RuntimeError('restart readiness failed')
            assert client.call('objects/' + sentinel) == before
            report['checks'].append('whole PostgreSQL/API restart with exact public record readback')
            command(['cargo', 'test', '--locked'])
            command(['uv', 'run', '--locked', 'python', '-B', '-m', 'unittest', 'discover', '-s', 'integrations/mcp/tests', '-v'])
            command(['uv', 'run', '--locked', 'python', '-B', '-m', 'unittest', 'discover', '-s', 'tools/tests', '-v'])
            report['checks'].append('Rust, packaged MCP and three-tool boundary suites')
            report['status'] = 'passed'
        finally:
            (results / 'compose.log').write_bytes(compose('logs', '--no-color'))
            compose('down', '--volumes', '--remove-orphans')
            report['cleanup'] = True
            (results / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2), flush=True)
