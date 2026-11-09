"""Synthetic scheduled-scan delivery regression; no vendor processes or live state."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import auto_capture as auto
import commons_capture as outbox
from test_auto_capture import CONFIG, SOURCE, START, WHEN, amp, exchange, initialize, msg, text
from test_capture import receiver


class EmptyCodex:
    def __init__(self, *args): pass
    def active(self): return {}
    def close(self): pass


class DeliveryPressureTests(unittest.TestCase):
    def test_large_waiting_batch_reserves_space_from_small_refillers(self):
        sources = sorted([{**SOURCE, 'provider': 'codex', 'thread_id': 'reserve-' + str(i)} for i in range(3)], key=outbox.source_key)
        old, large, small = sources
        def rows(body):
            return [{'timestamp': WHEN, 'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'reserve-turn'}},
                    {'timestamp': WHEN, 'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [text(body)]}}]
        by_thread = {old['thread_id']: rows('x' * 10000), large['thread_id']: rows('x' * 5000), small['thread_id']: rows('tiny')}
        class Codex:
            def __init__(self, *args): pass
            def active(self): return {s['thread_id']: {} for s in sources}
            def call(self, method, args): return {'thread': {'fixture_thread': args['threadId']}}
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory, receiver([]) as (url, observed):
            with outbox.database(Path(directory) / 'state') as db:
                initialize(db, url)
                for source in sources: auto.route(db, source, 'reserve-turn', 'business')
                auto.reconcile(db, old, auto.codex_turns(by_thread[old['thread_id']], old, START - 1))
                capacity = outbox.status(db)['pending_bytes'] + 2000
                with patch.object(auto, 'Codex', Codex), \
                     patch.object(auto, 'codex_path', side_effect=lambda config, meta: Path(meta['fixture_thread'])), \
                     patch.object(auto, 'codex_rows', side_effect=lambda path: by_thread[path.name]), \
                     patch.object(auto, 'check_destination', return_value=None), \
                     patch.object(outbox, 'token_from', return_value='synthetic-token'), \
                     patch.object(outbox, 'MAX_BYTES', capacity):
                    first = auto.scan(db, providers=('codex',))
                    self.assertEqual(first['delivered'], 1)
                    # The tiny source must not consume the larger source's reservation.
                    self.assertEqual(len(outbox.status(db)['batches']), 1)
                    second = auto.scan(db, providers=('codex',))
                    self.assertEqual(second['delivered'], 2)
                self.assertEqual([b['source']['thread_id'] for b in observed], [s['thread_id'] for s in sources])

    def test_busy_early_sources_cannot_starve_later_source_across_restart(self):
        sources = sorted([{**SOURCE, 'provider': 'codex', 'thread_id': 'fair-' + str(i)} for i in range(3)], key=outbox.source_key)
        early_a, early_b, later = sources
        def rows(size):
            return [{'timestamp': WHEN, 'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'fair-turn'}}] + [
                {'timestamp': WHEN, 'type': 'response_item', 'payload': {'type': 'message', 'role': 'user' if i == 0 else 'assistant', 'content': [text('Synthetic step ' + str(i))]}}
                for i in range(size)]
        by_thread = {s['thread_id']: rows(2) for s in sources}
        class Codex:
            def __init__(self, *args): pass
            def active(self): return {s['thread_id']: {} for s in sources}
            def call(self, method, args): return {'thread': {'fixture_thread': args['threadId']}}
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory, receiver([]) as (url, observed):
            state = Path(directory) / 'state'
            with outbox.database(state) as db:
                initialize(db, url)
                for source in sources: auto.route(db, source, 'fair-turn', 'business')
                # Both older sources occupy capacity before the later one arrives.
                for source in (early_a, early_b):
                    auto.reconcile(db, source, auto.codex_turns(by_thread[source['thread_id']], source, START - 1))
            for iteration in range(2):
                # Old sources continuously grow faster than one scan can admit.
                for source in (early_a, early_b): by_thread[source['thread_id']] = rows(200 + iteration * 200)
                with outbox.database(state) as db:
                    auto.setup(db)
                    with patch.object(auto, 'Codex', Codex), \
                         patch.object(auto, 'codex_path', side_effect=lambda config, meta: Path(meta['fixture_thread'])), \
                         patch.object(auto, 'codex_rows', side_effect=lambda path: by_thread[path.name]), \
                         patch.object(auto, 'check_destination', return_value=None), \
                         patch.object(outbox, 'token_from', return_value='synthetic-token'), \
                         patch.object(outbox, 'MAX_BATCHES', 2):
                        auto.scan(db, providers=('codex',))
            self.assertIn(later['thread_id'], [batch['source']['thread_id'] for batch in observed],
                          'A later source must get a turn even while older sources keep refilling')
            ids = [item['id'] for batch in observed for item in batch['items']]
            self.assertEqual(len(ids), len(set(ids)))

    def test_codex_only_scan_never_discovers_or_delivers_amp(self):
        codex_source = {**SOURCE, 'provider': 'codex', 'thread_id': 'codex-synthetic'}
        rows = [
            {'timestamp': WHEN, 'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'codex-turn'}},
            {'timestamp': WHEN, 'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [text('Synthetic Codex request')]}},
            {'timestamp': WHEN, 'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [text('Synthetic Codex response')]}},
        ]
        class CodexSource:
            def __init__(self, *args): pass
            def active(self): return {codex_source['thread_id']: {}}
            def call(self, *args): return {'thread': {}}
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory, receiver([]) as (url, observed):
            with outbox.database(Path(directory) / 'state') as db:
                initialize(db, url)
                # Amp is older in the shared queue, so an unfiltered flush fails this test.
                auto.reconcile(db, SOURCE, auto.amp_turns(amp(exchange()), SOURCE, START - 1))
                auto.route(db, codex_source, 'codex-turn', 'business')
                auto.reconcile(db, codex_source, auto.codex_turns(rows, codex_source, START - 1))
                with patch.object(auto, 'Codex', CodexSource), \
                     patch.object(auto, 'codex_path', return_value=Path('/synthetic/session.jsonl')), \
                     patch.object(auto, 'codex_rows', return_value=rows), \
                     patch.object(auto, 'amp_active', side_effect=AssertionError('Amp discovery is outside selected scope')), \
                     patch.object(outbox, 'token_from', return_value='synthetic-token'):
                    result = auto.scan(db, providers=('codex',))
                self.assertEqual(result['delivered'], 1)
                self.assertEqual([batch['source']['provider'] for batch in observed], ['codex'])
                batches = outbox.status(db)['batches']
                self.assertEqual(batches[0]['state'], 'queued')
                self.assertEqual(batches[1]['state'], 'acknowledged')

    def test_empty_checked_source_set_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory, receiver([]) as (url, observed):
            with outbox.database(Path(directory) / 'state') as db:
                initialize(db, url)
                auto.reconcile(db, SOURCE, auto.amp_turns(amp(exchange()), SOURCE, START - 1))
                self.assertEqual(outbox.flush(db, 'synthetic-token', source_keys=set())['delivered'], 0)
                with self.assertRaisesRegex(ValueError, 'source identity'):
                    outbox.flush(db, 'synthetic-token', source_keys={'not-an-identity'})
                self.assertEqual(observed, [])

    def test_checked_source_filter_cannot_override_route_or_deletion_fences(self):
        for fence in ('route', 'delete'):
            with self.subTest(fence=fence), tempfile.TemporaryDirectory() as directory, receiver([]) as (url, observed):
                with outbox.database(Path(directory) / 'state') as db:
                    initialize(db, url)
                    auto.reconcile(db, SOURCE, auto.amp_turns(amp(exchange()), SOURCE, START - 1))
                    key = outbox.source_key(SOURCE)
                    if fence == 'route':
                        with self.assertRaises(ValueError): auto.route(db, SOURCE, 'user1', 'personal')
                    else:
                        with db: outbox.purge_local(db, key)
                    self.assertEqual(outbox.flush(db, 'synthetic-token', source_keys={key})['delivered'], 0)
                    self.assertEqual(observed, [])

    def test_invalid_provider_fails_before_discovery_or_delivery(self):
        with self.assertRaisesRegex(ValueError, 'provider'):
            auto.scan(None, providers=())
        with self.assertRaisesRegex(ValueError, 'provider'):
            auto.scan(None, providers=('unknown',))

    def test_missing_codex_rollout_only_blocks_its_own_queued_batches(self):
        missing = {**SOURCE, 'provider': 'codex', 'thread_id': 'missing-rollout'}
        healthy = {**missing, 'thread_id': 'healthy-rollout'}
        rows = [
            {'timestamp': WHEN, 'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'synthetic-turn'}},
            {'timestamp': WHEN, 'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [text('Synthetic request')]}},
        ]
        with tempfile.TemporaryDirectory() as directory, receiver([]) as (url, observed):
            sessions = Path(directory) / 'codex' / 'sessions'
            sessions.mkdir(parents=True)
            healthy_path = sessions / 'healthy.jsonl'
            healthy_path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            paths = {missing['thread_id']: sessions / 'missing.jsonl', healthy['thread_id']: healthy_path}
            class Codex:
                def __init__(self, *args): pass
                def active(self): return {tid: {} for tid in paths}
                def call(self, method, args): return {'thread': {'path': str(paths[args['threadId']])}}
                def close(self): pass
            with outbox.database(Path(directory) / 'state') as db:
                initialize(db, url)
                # The unavailable source already has an older queued batch.
                for source in (missing, healthy):
                    auto.route(db, source, 'synthetic-turn', 'business')
                    auto.reconcile(db, source, auto.codex_turns(rows, source, START - 1))
                config, cutoff, enabled = auto.settings(db)
                config['codex_home'] = str(sessions.parent)
                with patch.object(auto, 'settings', return_value=(config, cutoff, enabled)), \
                     patch.object(auto, 'Codex', Codex), \
                     patch.object(outbox, 'token_from', return_value='synthetic-token'):
                    result = auto.scan(db, providers=('codex',))
                self.assertEqual(result.get('delivered', 0), 1)
                self.assertEqual(result['errors'], [outbox.source_key(missing)])
                self.assertEqual([batch['source']['thread_id'] for batch in observed], [healthy['thread_id']])
                self.assertEqual([b['state'] for b in outbox.status(db)['batches']], ['queued', 'acknowledged'])

    def test_backpressure_never_bypasses_another_sources_content_conflict(self):
        with tempfile.TemporaryDirectory() as directory, receiver([]) as (url, observed):
            with outbox.database(Path(directory) / 'synthetic-state') as db:
                initialize(db, url)
                other = {**SOURCE, 'thread_id': 'T-conflict'}
                other_initial = {**amp(exchange()), 'id': other['thread_id']}
                auto.reconcile(db, SOURCE, auto.amp_turns(amp(exchange()), SOURCE, START - 1))
                auto.reconcile(db, other, auto.amp_turns(other_initial, other, START - 1))
                more = amp(exchange() + [msg('extra', 'assistant', [text('extra')])])
                changed = copy.deepcopy(other_initial)
                changed['messages'][0]['content'][0]['text'] = 'Changed after queueing'
                def exported(binary, operation, thread):
                    return more if thread == SOURCE['thread_id'] else changed
                with patch.object(auto, 'Codex', EmptyCodex), \
                     patch.object(auto, 'amp_active', return_value={s['thread_id']: {'updated': auto.iso(START)} for s in (SOURCE, other)}), \
                     patch.object(auto, 'amp_command', side_effect=exported), \
                     patch.object(outbox, 'token_from', return_value='synthetic-token'), \
                     patch.object(outbox, 'MAX_BATCHES', 2):
                    result = auto.scan(db)
                self.assertEqual(result.get('delivered', 0), 1)
                self.assertEqual(len(result['backpressure']), 1)
                self.assertEqual(len(result['errors']), 1)
                self.assertEqual([batch['source']['thread_id'] for batch in observed], [SOURCE['thread_id']])
                self.assertEqual([b['state'] for b in outbox.status(db)['batches']], ['acknowledged', 'queued'])

    def test_unknown_provider_lifecycle_still_pauses_all_delivery(self):
        with tempfile.TemporaryDirectory() as directory, receiver([]) as (url, observed):
            with outbox.database(Path(directory) / 'synthetic-state') as db:
                initialize(db, url)
                auto.reconcile(db, SOURCE, auto.amp_turns(amp(exchange()), SOURCE, START - 1))
                with patch.object(auto, 'Codex', side_effect=ValueError('synthetic discovery failure')), \
                     patch.object(outbox, 'token_from', return_value='synthetic-token'):
                    result = auto.scan(db)
                self.assertTrue(result['delivery_paused'])
                self.assertEqual(observed, [])

    def test_later_provider_discovery_failure_blocks_already_checked_sources(self):
        with tempfile.TemporaryDirectory() as directory, receiver([]) as (url, observed):
            with outbox.database(Path(directory) / 'state') as db:
                initialize(db, url)
                payload = amp(exchange())
                auto.reconcile(db, SOURCE, auto.amp_turns(payload, SOURCE, START - 1))
                with patch.object(auto, 'amp_active', return_value={SOURCE['thread_id']: {'updated': auto.iso(START)}}), \
                     patch.object(auto, 'amp_command', return_value=payload), \
                     patch.object(auto, 'Codex', side_effect=ValueError('synthetic discovery failure')), \
                     patch.object(outbox, 'token_from', return_value='synthetic-token'):
                    result = auto.scan(db, providers=('amp', 'codex'))
                self.assertTrue(result['delivery_paused'])
                self.assertEqual(observed, [])
                self.assertEqual(outbox.status(db)['batches'][0]['state'], 'queued')

    def test_full_queue_drains_checked_batch_then_recovers_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory, receiver([]) as (url, observed):
            state = Path(directory) / 'synthetic-state'
            with outbox.database(state) as db:
                initialize(db, url)
                initial = auto.amp_turns(amp(exchange()), SOURCE, START - 1)
                self.assertEqual(auto.reconcile(db, SOURCE, initial), 7)
                # New visible content cannot fit while the first batch is queued.
                messages = exchange() + [msg('extra-answer', 'assistant', [text('Synthetic extra')])]
                payload = amp(messages)
                with patch.object(auto, 'Codex', EmptyCodex), \
                     patch.object(auto, 'amp_active', return_value={SOURCE['thread_id']: {'updated': auto.iso(START)}}), \
                     patch.object(auto, 'amp_command', return_value=payload), \
                     patch.object(outbox, 'token_from', return_value='synthetic-token'), \
                     patch.object(outbox, 'MAX_BATCHES', 1):
                    result = auto.scan(db)
                self.assertEqual(result.get('delivered', 0), 1,
                                 'Capacity pressure must not prevent delivery of already checked evidence')
                self.assertEqual(len(observed), 1)
                self.assertEqual(outbox.status(db)['pending_bytes'], 0)
            # Durable cursor is unchanged for the content that did not fit.
            with outbox.database(state) as db:
                auto.setup(db)
                self.assertEqual(auto.reconcile(db, SOURCE, auto.amp_turns(payload, SOURCE, START - 1)), 1)
                self.assertEqual(outbox.flush(db, 'synthetic-token')['delivered'], 1)
                self.assertEqual(auto.reconcile(db, SOURCE, auto.amp_turns(payload, SOURCE, START - 1)), 0)
                ids = [item['id'] for batch in observed for item in batch['items']]
                self.assertEqual(len(ids), 8)
                self.assertEqual(len(set(ids)), 8)


if __name__ == '__main__':
    unittest.main()
