"""Synthetic adapter and durable HTTP behavior; real-client evidence is separate."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import auto_capture as auto
import commons_capture as outbox
from test_capture import receiver

CONFIG = {'namespace': 'synthetic-host', 'codex_home': '/synthetic/codex', 'codex': 'codex',
          'amp': 'amp', 'token_file': '/synthetic/token', 'domain_label': 'Synthetic business'}
SOURCE = auto.source_for(CONFIG, 'amp', 'T-synthetic')
WHEN = '2026-10-25T03:00:00Z'
START = auto.timestamp(WHEN)


def amp(messages):
    return {'id': SOURCE['thread_id'], 'created': START * 1000, 'messages': messages}


def msg(mid, role, blocks, state='complete', when=WHEN):
    return {'protocolMessageID': mid, 'role': role, 'content': blocks, 'createdAt': when,
            'state': {'type': state}}


def text(value, **extra):
    return {'type': 'text', 'text': value, **extra}


def call(cid, name, args):
    return {'type': 'tool_use', 'id': cid, 'name': name, 'input': args, 'complete': True}


def result(cid, value, status='done'):
    return {'type': 'tool_result', 'toolUseID': cid, 'run': {'result': value, 'status': status}}


def exchange(domain='business'):
    return [msg('user1', 'user', [text('Synthetic human'), text('secret instructions', hidden=True)]),
            msg('route-call', 'assistant', [call('route1', auto.ROUTE_TOOL, {'domain': domain})]),
            msg('route-result', 'user', [result('route1', {'contract': 'commons.capture-route/1', 'domain': domain})]),
            msg('call', 'assistant', [text('Checking'), call('tool1', 'Bash', {'cmd': 'printf synthetic'})]),
            msg('result', 'user', [result('tool1', {'output': 'synthetic', 'exitCode': 0})]),
            msg('answer', 'assistant', [text('Synthetic final'), {'type': 'thinking', 'thinking': 'NEVER CAPTURE'}])]


def initialize(db, url='http://127.0.0.1:1'):
    auto.setup(db)
    outbox.initialize(db, url, 'synthetic')
    auto.configure(db, CONFIG, START - 1)


class AdapterTests(unittest.TestCase):
    def test_explicit_speaker_mapping_is_immutable_and_never_labels_tools(self):
        from uuid import uuid4
        human, agent = str(uuid4()), str(uuid4())
        with tempfile.TemporaryDirectory() as directory, outbox.database(Path(directory) / 'state') as db:
            auto.setup(db)
            outbox.initialize(db, 'http://127.0.0.1:1', 'synthetic')
            auto.configure(db, {**CONFIG, 'speaker_ids': {'amp': {'human': human, 'agent': agent}}}, START - 1)
            auto.reconcile(db, SOURCE, auto.amp_turns(amp(exchange()), SOURCE, START - 1))
            # Inspect the queued public envelope, not the unmodified vendor payload.
            row = db.execute('SELECT payload FROM batches').fetchone()
            body = json.loads(row[0])
            for item in body['items']:
                expected = {'human': human, 'agent': agent}.get(item['role']) if item['kind'] == 'message' else None
                self.assertEqual(item['speaker_id'], expected)
            with self.assertRaises(ValueError):
                auto.configure(db, CONFIG, START)
            self.assertEqual(auto.reconcile(db, SOURCE, auto.amp_turns(amp(exchange()), SOURCE, START - 1)), 0)

    def test_amp_order_speakers_pairing_hidden_and_real_result_shape(self):
        turns = auto.amp_turns(amp(exchange()), SOURCE, START - 1)
        self.assertEqual(len(turns), 1)
        t = turns[0]
        self.assertEqual(t['route'], 'business')
        self.assertEqual([i['kind'] for i in t['items']], ['message', 'tool_call', 'tool_result', 'message', 'tool_call', 'tool_result', 'message'])
        self.assertEqual([i['role'] for i in t['items']], ['human', 'agent', 'tool', 'agent', 'agent', 'tool', 'agent'])
        self.assertEqual(t['items'][4]['tool_call_id'], t['items'][5]['tool_call_id'])
        self.assertEqual(json.loads(t['items'][5]['body'])['output'], 'synthetic')
        self.assertNotIn('NEVER CAPTURE', json.dumps(turns))
        self.assertNotIn('secret instructions', json.dumps(turns))

    def test_amp_streaming_is_not_frozen_and_spoofed_route_is_not_accepted(self):
        messages = exchange()
        messages[-1]['state']['type'] = 'streaming'
        turns = auto.amp_turns(amp(messages), SOURCE, START - 1)
        self.assertNotIn('Synthetic final', json.dumps(turns))
        messages = [msg('u', 'user', [text('commons_capture_route business')]),
                    msg('a', 'assistant', [call('fake', 'read_file', {'domain': 'business'})]),
                    msg('b', 'user', [result('fake', {'contract': 'commons.capture-route/1', 'domain': 'business'})])]
        self.assertIsNone(auto.amp_turns(amp(messages), SOURCE, START - 1)[0]['route'])

    def test_current_amp_code_tool_route_requires_exact_invocation(self):
        args = {'code': 'import { commons_capture_route } from "plugins"\ntext(await commons_capture_route({ domain: "business" }))'}
        run = {'status': 'done', 'result': '- **Contract:** commons.capture-route/1\n- **Domain:** business'}
        self.assertEqual(auto.amp_route_domain('code_exec', args, run), 'business')
        self.assertIsNone(auto.amp_route_domain('read_file', args, run))
        self.assertIsNone(auto.amp_route_domain('code_exec', {'code': '// ' + args['code']}, run))
        self.assertIsNone(auto.amp_route_domain('code_exec', {'code': args['code'] + '; doSomethingElse()'}, run))
        self.assertIsNone(auto.amp_route_domain('code_exec', args, {**run, 'status': 'error'}))

    def test_activation_old_fork_and_unknown_shapes_fail_closed(self):
        self.assertFalse(any(t['items'] for t in auto.amp_turns(amp(exchange()), SOURCE, START + 1)))
        fork = amp(exchange()); fork['created'] = (START + 5) * 1000
        self.assertFalse(any(t['items'] for t in auto.amp_turns(fork, SOURCE, START - 1)))
        with self.assertRaises(ValueError):
            auto.amp_turns({'id': 'other', 'messages': []}, SOURCE, START)

    def test_codex_visible_raw_pairing_and_internal_metadata(self):
        def row(kind, p): return {'timestamp': WHEN, 'type': kind, 'payload': p}
        rows = [row('event_msg', {'type': 'task_started', 'turn_id': 'turn1'}),
                row('response_item', {'type': 'message', 'role': 'developer', 'content': [text('internal')]}),
                row('response_item', {'type': 'message', 'role': 'user', 'content': [text('plugin injection'), text('Synthetic user')],
                    'internal_chat_message_metadata_passthrough': {'content_item_kinds': ['plugins.recommendations', 'user.text']}}),
                row('response_item', {'type': 'reasoning', 'summary': 'secret reasoning'}),
                row('response_item', {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'c1', 'input': 'synthetic'}),
                row('response_item', {'type': 'custom_tool_call_output', 'call_id': 'c1', 'output': 'synthetic result'}),
                row('response_item', {'type': 'message', 'role': 'assistant', 'content': [text('answer')]}),
                row('event_msg', {'type': 'agent_message', 'message': 'answer'})]
        t = auto.codex_turns(rows, SOURCE, START - 1)[0]
        self.assertEqual([x['body'] for x in t['items']], ['Synthetic user', 'synthetic', 'synthetic result', 'answer'])
        self.assertEqual(t['items'][1]['tool_call_id'], t['items'][2]['tool_call_id'])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'session.jsonl'
            p.write_text(''.join(json.dumps(x)+'\n' for x in rows) + '{"partial":')
            self.assertEqual(auto.codex_rows(p), rows)

    def test_desktop_delegated_brief_remains_visible_without_invented_pair(self):
        rows = [{'timestamp': WHEN, 'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 't'}},
                {'timestamp': WHEN, 'type': 'response_item', 'payload': {'type': 'function_call_output', 'namespace': 'codex_app', 'name': 'create_thread', 'output': '<codex_delegation><input>Synthetic delegated brief</input></codex_delegation>'}}]
        turn = auto.codex_turns(rows, SOURCE, START - 1)[0]
        self.assertEqual(len(turn['items']), 1)
        self.assertIn('Synthetic delegated brief', turn['items'][0]['body'])
        self.assertIsNone(turn['items'][0]['tool_call_id'])
        self.assertEqual(turn['items'][0]['role'], 'tool')
        self.assertTrue(turn['gaps'])

    def test_nested_codex_completion_events_keep_distinct_tools(self):
        rows = [{'timestamp': WHEN, 'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 't'}},
                {'timestamp': WHEN, 'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'functions.exec', 'call_id': 'wrapper', 'input': 'two nested commands'}},
                {'timestamp': WHEN, 'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {'type': 'CommandExecution', 'id': 'nested', 'command': ['printf', 'synthetic'], 'aggregated_output': 'synthetic', 'exit_code': 0, 'status': 'completed'}}},
                {'timestamp': WHEN, 'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'wrapper', 'output': 'wrapper result'}}]
        items = auto.codex_turns(rows, SOURCE, START - 1)[0]['items']
        self.assertEqual([i['tool_call_id'] for i in items], ['wrapper', 'nested', 'nested', 'wrapper'])
        self.assertEqual([i['kind'] for i in items], ['tool_call', 'tool_call', 'tool_result', 'tool_result'])
        self.assertEqual([i['position'] for i in items], sorted(i['position'] for i in items))

    def test_redaction(self):
        for body in ['{"token":"very-secret-value"}', 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345',
                     'MY_API_KEY=abcdef012345', 'a sk-abcdefghijklmnopqrstuvwx b', 'the actualsecret123 value', json.dumps({'output': json.dumps({'token': 'nested-secret'})})]:
            cleaned, changed = auto.sanitize(body, ('actualsecret123',))
            self.assertTrue(changed, body)
            self.assertIn('redact', cleaned)


class ReconciliationTests(unittest.TestCase):
    def test_incremental_restart_outage_and_exactly_once(self):
        with tempfile.TemporaryDirectory() as d, receiver([503]) as (url, observed):
            state = Path(d) / 'state'
            initial = auto.amp_turns(amp(exchange()[:-1]), SOURCE, START - 1)
            final = auto.amp_turns(amp(exchange()), SOURCE, START - 1)
            with outbox.database(state) as db:
                initialize(db, url)
                self.assertEqual(auto.reconcile(db, SOURCE, initial), 6)
                outbox.flush(db, 'synthetic-token')
                self.assertEqual(len(observed), 1)
            with outbox.database(state) as db:
                auto.setup(db)
                self.assertEqual(auto.reconcile(db, SOURCE, final), 1)
                with patch.object(outbox.time, 'time', return_value=auto.time.time() + 600):
                    self.assertEqual(outbox.flush(db, 'synthetic-token')['delivered'], 2)
                self.assertEqual(observed[0], observed[1])
                delivered = observed[1:]
                self.assertEqual(len({i['id'] for batch in delivered for i in batch['items']}), 7)
                self.assertEqual(auto.reconcile(db, SOURCE, final), 0)
                self.assertEqual(outbox.flush(db, 'synthetic-token')['delivered'], 0)
                self.assertEqual(outbox.status(db)['pending_bytes'], 0)

    def test_personal_mixed_unclassified_and_repository_are_not_business(self):
        with tempfile.TemporaryDirectory() as d:
            with outbox.database(Path(d) / 'state') as db:
                initialize(db)
                for domain in ('personal', 'mixed'):
                    turns = auto.amp_turns(amp(exchange(domain)), SOURCE, START - 1)
                    self.assertEqual(auto.reconcile(db, SOURCE, turns), 0)
                    db.execute('DELETE FROM auto_routes'); db.commit()
                unclassified = auto.amp_turns(amp([exchange()[0], exchange()[-1]]), SOURCE, START - 1)
                self.assertEqual(auto.reconcile(db, SOURCE, unclassified), 0)
                self.assertEqual(outbox.status(db)['batches'], [])
                self.assertEqual(auto.reconcile(db, SOURCE, auto.amp_turns(amp(exchange()), SOURCE, START - 1)), 7)
                # A later personal turn in the same durable association is excluded.
                messages = exchange() + [msg('private-user', 'user', [text('PERSONAL SECRET')])]
                self.assertEqual(auto.reconcile(db, SOURCE, auto.amp_turns(amp(messages), SOURCE, START - 1)), 0)
                payloads = ''.join(x[0] or '' for x in db.execute('SELECT payload FROM batches'))
                self.assertNotIn('PERSONAL SECRET', payloads)

    def test_queue_pressure_keeps_cursor_retryable(self):
        with tempfile.TemporaryDirectory() as d:
            with outbox.database(Path(d) / 'state') as db:
                initialize(db)
                turns = auto.amp_turns(amp(exchange()), SOURCE, START - 1)
                with patch.object(outbox, 'MAX_BYTES', 1):
                    with self.assertRaisesRegex(ValueError, 'outbox full'):
                        auto.reconcile(db, SOURCE, turns)
                self.assertIsNone(db.execute('SELECT cursor FROM sources').fetchone()[0])
                self.assertEqual(auto.reconcile(db, SOURCE, turns), 7)

    def test_disable_interval_archive_and_delete_barriers(self):
        with tempfile.TemporaryDirectory() as d, receiver([410]) as (url, observed):
            with outbox.database(Path(d) / 'state') as db:
                initialize(db, url)
                turns = auto.amp_turns(amp(exchange()), SOURCE, START - 1)
                auto.set_active(db, False, START + 1)
                self.assertEqual(auto.reconcile(db, SOURCE, turns), 0)
                during = copy.deepcopy(turns); during[0]['started'] = START + 2
                auto.set_active(db, True, START + 3)
                self.assertEqual(auto.reconcile(db, SOURCE, during), 0)
                auto.reconcile(db, SOURCE, turns)
                outbox.flush(db, 'synthetic-token')
                self.assertEqual(auto.reconcile(db, SOURCE, turns), 0)
                self.assertEqual(outbox.status(db)['pending_bytes'], 0)
                self.assertTrue(outbox.status(db)['sources'][0]['deleted'])
        with tempfile.TemporaryDirectory() as d:
            with outbox.database(Path(d) / 'state') as db:
                initialize(db)
                auto.reconcile(db, SOURCE, turns)
                auto.stop(db, outbox.source_key(SOURCE), 'archived')
                self.assertEqual(auto.reconcile(db, SOURCE, turns), 0)
                self.assertFalse(outbox.status(db)['sources'][0]['enabled'])
                with self.assertRaises(ValueError): auto.route(db, SOURCE, 'new', 'business')

    def test_changed_or_missing_items_stop_and_oversize_is_honest(self):
        with tempfile.TemporaryDirectory() as d:
            with outbox.database(Path(d) / 'state') as db:
                initialize(db)
                turns = auto.amp_turns(amp(exchange()), SOURCE, START - 1)
                auto.reconcile(db, SOURCE, turns)
                changed = copy.deepcopy(turns); changed[0]['items'][0]['body'] = 'changed'
                with self.assertRaisesRegex(ValueError, 'changed'): auto.reconcile(db, SOURCE, changed)
                removed = copy.deepcopy(turns); removed[0]['items'].pop()
                with self.assertRaisesRegex(ValueError, 'disappeared'): auto.reconcile(db, SOURCE, removed)
        with tempfile.TemporaryDirectory() as d:
            with outbox.database(Path(d) / 'state') as db:
                initialize(db)
                turns[0]['items'][0]['body'] = 'x' * (auto.MAX_BODY + 1)
                auto.reconcile(db, SOURCE, turns)
                saved = json.loads(db.execute('SELECT payload FROM batches').fetchone()[0])
                self.assertIn('Oversized item unavailable', saved['items'][0]['body'])
                self.assertEqual(saved['coverage']['status'], 'partial')

    def test_exclusion_routes_can_be_repeated_without_stopping_source(self):
        with tempfile.TemporaryDirectory() as d:
            with outbox.database(Path(d) / 'state') as db:
                initialize(db)
                for first, second in (('mixed', 'personal'), ('personal', 'mixed')):
                    turn = first + '-turn'
                    auto.route(db, SOURCE, turn, first)
                    result = auto.route(db, SOURCE, turn, second)
                    self.assertTrue(result['associated'])
                    self.assertEqual(result['domain'], first)
                self.assertFalse(db.execute('SELECT stopped FROM auto_threads').fetchone()[0])
                self.assertEqual(outbox.status(db)['batches'], [])
                with self.assertRaisesRegex(ValueError, 'stopped'):
                    auto.route(db, SOURCE, 'mixed-turn', 'business')

    def test_conflicting_route_durably_fences_pending_business_delivery(self):
        with tempfile.TemporaryDirectory() as d, receiver([]) as (url, observed):
            with outbox.database(Path(d) / 'state') as db:
                initialize(db, url)
                auto.reconcile(db, SOURCE, auto.amp_turns(amp(exchange()), SOURCE, START - 1))
                with self.assertRaisesRegex(ValueError, 'stopped'):
                    auto.route(db, SOURCE, 'user1', 'personal')
                self.assertEqual(outbox.flush(db, 'synthetic-token')['delivered'], 0)
                self.assertEqual(observed, [])
                self.assertTrue(db.execute('SELECT stopped FROM auto_threads').fetchone()[0])

    def test_scan_observes_source_archive_before_flushing_pending(self):
        class EmptyCodex:
            def __init__(self, *args): pass
            def active(self): return {}
            def close(self): pass
        with tempfile.TemporaryDirectory() as d, receiver([]) as (url, observed):
            with outbox.database(Path(d) / 'state') as db:
                initialize(db, url)
                source = {**SOURCE, 'provider': 'codex'}
                turns = auto.amp_turns(amp(exchange()), source, START - 1)
                auto.reconcile(db, source, turns)
                with patch.object(auto, 'Codex', EmptyCodex), patch.object(auto, 'amp_active', return_value={}), patch.object(outbox, 'token_from', return_value='synthetic-token'):
                    result = auto.scan(db)
                self.assertEqual(result['delivered'], 0)
                self.assertEqual(observed, [])
                self.assertTrue(db.execute('SELECT stopped FROM auto_threads').fetchone()[0])

    def test_disable_excludes_items_written_inside_disabled_window(self):
        with tempfile.TemporaryDirectory() as d:
            with outbox.database(Path(d) / 'state') as db:
                initialize(db)
                turns = auto.amp_turns(amp(exchange()), SOURCE, START - 1)
                auto.set_active(db, False, START + 1)
                auto.set_active(db, True, START + 3)
                omitted = copy.deepcopy(turns[0]['items'][-1])
                omitted.update(source_item_id='during-disabled', id='26436fa3-b464-49b9-8c21-97d77b26dd58', source_created_at=auto.iso(START+2), body='DISABLED MUST STAY ABSENT', position=99999)
                turns[0]['items'].append(omitted)
                self.assertEqual(auto.reconcile(db, SOURCE, turns), 7)
                payload=db.execute('SELECT payload FROM batches').fetchone()[0]
                self.assertNotIn('DISABLED MUST STAY ABSENT', payload)

    def test_discovery_pagination(self):
        pages = [[{'id': f'T-{i}'} for i in range(100)], [{'id': 'T-last'}]]
        with patch.object(auto, 'amp_command', side_effect=pages) as command:
            self.assertEqual(len(auto.amp_active('amp')), 101)
            self.assertEqual(command.call_args_list[1].args[-1], '100')
        with patch.object(auto, 'amp_command', return_value=pages[0]):
            with self.assertRaisesRegex(ValueError, 'repeated'): auto.amp_active('amp')


if __name__ == '__main__':
    unittest.main()
