"""Exercise paired Codex MCP events through capture and the live relationship API."""
import copy
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from atomic import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integrations/capture'))
import auto_capture as auto
import commons_capture as outbox


def main():
    origin = os.environ['COMMONS_TEST_ORIGIN']
    client = Client(origin)
    assert client.call('login', {'username': 'alice', 'password': os.environ['COMMONS_TEST_PASSWORD']})[0] == 200

    def call(path, body=None):
        code, result = client.call(path, body)
        assert code == 200, (path, code, result)
        return result

    def create(ref, title, kind='entity'):
        return dict(op='create_object', local_ref=ref, kind=kind, title=title,
                    description='Synthetic captured Object relationship fixture.', fields={})

    read_id = client.apply([create('read', 'Object links read fixture')])[1]['local_refs']['read']
    read = call('objects/' + read_id)
    update = dict(op='update_object', object_id=read_id, expected_revision=1, body='Synthetic update.')
    operations = [create('note', 'Object links created Note', 'note'), update]
    dry = client.apply(operations, dry=True)[1]
    written = client.apply(operations)[1]
    note_id = written['local_refs']['note']

    when = '2026-11-09T01:00:00Z'
    cutoff = auto.timestamp(when) - 1
    turn = str(uuid4())
    config = dict(namespace='synthetic-relationship-test', codex_home='/synthetic', codex='codex',
                  amp='amp', token_file='/synthetic', domain_label='Synthetic',
                  commons_object_links={'server': 'commons_fixture', 'installation': 'fixture'})
    source = auto.source_for(config, 'codex', str(uuid4()))

    def event(tool, args, result, *, server='commons_fixture', installation='fixture', error=False):
        return dict(type='event_msg', timestamp=when, payload=dict(
            type='item_completed', item=dict(type='McpToolCall', id=str(uuid4()),
                server=server, tool=tool, arguments=args, status='completed',
                result={'isError': error, 'content': [{'type': 'text', 'text': json.dumps(
                    dict(installation=installation, result=result))}]})))

    rows = [dict(type='event_msg', timestamp=when, payload=dict(type='task_started', turn_id=turn))]
    rows += [event('read', {'id': read_id.upper(), 'resource': 'object'}, read),
             event('apply', {'execute': False, 'request': {'operations': operations}}, dry),
             event('apply', {'execute': True, 'request': {'operations': operations}}, written),
             event('read', {'id': read_id}, read, server='another_connector'),
             event('read', {'id': read_id}, read, installation='another_installation'),
             event('read', {'id': read_id}, read, error=True),
             event('search', {}, {'objects': [read['object']]})]
    turns = auto.codex_turns(rows, source, cutoff)
    with TemporaryDirectory() as temp, outbox.database(Path(temp) / 'capture') as db:
        auto.setup(db)
        outbox.initialize(db, origin, 'synthetic')
        auto.configure(db, config, cutoff)
        auto.route(db, source, turn, 'personal')
        assert auto.reconcile(db, source, turns) == 0
        # Use a separate, independently routed source for business.
        source = auto.source_for(config, 'codex', str(uuid4()))
        turns = auto.codex_turns(rows, source, cutoff)
        auto.route(db, source, turn, 'business')
        assert auto.reconcile(db, source, turns) == 14
        assert auto.reconcile(db, source, turns) == 0
        envelope = json.loads(db.execute('SELECT payload FROM batches').fetchone()[0])
    assert len(envelope['runs']) == 2, envelope['runs']
    receipt = call('capture', envelope)
    assert call('capture', envelope) == receipt
    thread = receipt['thread_id']
    read_trace, write_trace = receipt['trace_ids']

    def refs(path):
        return {(r['id'], r['relation']) for r in call(path)['references']}

    assert refs(f'traces/{read_trace}/relationships') == {(read_id, 'consulted')}
    assert refs(f'traces/{write_trace}/relationships') == {(note_id, 'created'), (read_id, 'updated')}
    assert refs(f'threads/{thread}/relationships') == {
        (read_id, 'consulted'), (read_id, 'updated'), (note_id, 'created'),
        (read_trace, 'trace'), (write_trace, 'trace')}
    page = call(f'threads/{thread}/relationships?limit=1')
    assert len(page['references']) == 1 and page['next_offset'] == 1
    assert read_trace not in {r['id'] for r in page['references']}
    relationships = call(f'traces/{read_trace}/relationships')['connections']
    assert len(relationships) == 1 and relationships[0]['provenance']['object_revision'] == 1

    # A delayed reference to an unavailable target must not fence the Thread.
    stale = copy.deepcopy(envelope)
    stale.update(batch_id='missing-object', items=[], runs=[{
        'id': str(uuid4()), 'source_run_id': 'missing-object', 'kind': 'commons-tool-call',
        'status': 'completed', 'object_effects': [{'id': str(uuid4()), 'revision': 1, 'operation': 'read'}],
    }])
    missing_trace = call('capture', stale)['trace_ids'][0]
    assert refs(f'traces/{missing_trace}/relationships') == set()

    result = dict(thread=thread, read_trace=read_trace, write_trace=write_trace, read_id=read_id, note_id=note_id)
    (Path(os.environ['COMMONS_ATOMIC_RESULTS']) / 'capture-object-links.json').write_text(json.dumps(result))
    print('Passed: opted-in Codex event pairing, read/create/update, failed and dry-run exclusion, replay, missing target and Thread rollup')


if __name__ == '__main__':
    main()
