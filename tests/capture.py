"""Public capture behavior, composed into the disposable foundation HTTP suite.

No vendor profile, private history, live store or model is used here.
"""
import concurrent.futures
import copy
import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


def uid():
    return str(uuid.uuid4())


def envelope(speaker, marker='Synthetic capture marker'):
    return dict(contract_version='commons.capture/1',
        source=dict(provider='manual', namespace='isolated-http-suite', thread_id=uid()),
        batch_id=uid(), title='Synthetic captured conversation', history=False,
        coverage=dict(status='partial', messages='Two supplied messages', tools='One supplied result',
            attachments='No original files supplied', history='From activation only',
            gaps=['No vendor-client completeness claim']),
        items=[dict(id=uid(), source_item_id='human-a', position=0, kind='message', role='human',
                    speaker_id=speaker, source_created_at='2026-10-16T11:03:02+11:00',
                    body=marker, artifact_ids=[]),
               dict(id=uid(), source_item_id='tool-b', position=1, kind='tool_result', role='tool',
                    tool_name='synthetic_lookup', tool_call_id='call-a', status='failed',
                    source_created_at=None, body='Synthetic tool unavailable', artifact_ids=[]),
               dict(id=uid(), source_item_id='agent-c', position=2, kind='message', role='agent',
                    speaker_id=None, source_created_at='2026-10-16T00:03:05Z',
                    body='Visible final response, not hidden reasoning', artifact_ids=[])],
        attachments=[], runs=[])


def reported_run(**changes):
    return dict(id=uid(), source_run_id=uid(), kind='synthetic-check', status='running',
                input={'request': 'check asymmetric values'}, trace=[{'step': 'started', 'value': 3}],
                result={}, review={}, consulted_object_ids=[], **changes)


class CaptureTests:
    def test_thread_participants_include_all_explicit_users(self):
        users = [self.admin.request('users', {'username': 'participant-' + uid(),
            'title': 'Synthetic participant ' + str(i), 'user_kind': 'agent', 'role': 'member'})['id'] for i in range(3)]
        request = envelope(self.bob_id)
        request['items'][2]['speaker_id'] = users[0]
        request['runs'] = [reported_run(actor_id=users[1])]
        chat = self.bob.request('capture', request)['chat_id']
        # Include both directions of explicit participant Connections; deduplicate a speaker.
        for source, target in [(users[2], chat), (chat, self.bob_id)]:
            self.admin.apply([dict(op='import_record', source_store='synthetic-thread-participants',
                record=dict(type='connection', id=uid(), from_id=source, to_id=target,
                    kind='involves', explanation='Synthetic historical participant', revision=1,
                    created_by=None, created_at='2020-02-01T00:00:00Z', updated_at='2020-02-01T00:00:00Z',
                    archived_at=None, protected=False, provenance={}))])
        def participants():
            rows = self.reader.request('chats?limit=200')['objects']
            return next(row['participants'] for row in rows if row['id'] == chat)
        expected = set(users + [self.bob_id])
        actual = participants()
        self.assertEqual({u['user_object_id'] for u in actual}, expected)
        self.assertEqual(len(actual), 4)
        self.assertNotIn(self.admin_id, expected)  # uploader is not inferred as a participant
        self.assertTrue(all('avatar_asset_url' in u for u in actual))
        refs = self.reader.request(f'chats/{chat}/relationships')['references']
        self.assertEqual({r['id'] for r in refs if r['relation'] == 'participant'}, expected)
        # A later new speaker joins the same Thread, without overwriting earlier participants.
        later = copy.deepcopy(request)
        later['batch_id'] = uid()
        later['items'] = [dict(id=uid(), source_item_id='later-human', position=3,
            kind='message', role='human', speaker_id=self.admin_id, source_created_at=None,
            body='Another participant joined', artifact_ids=[])]
        later['runs'] = []
        self.bob.request('capture', later)
        self.assertEqual({u['user_object_id'] for u in participants()}, expected | {self.admin_id})
        revision = self.bob.request(f'chats/{chat}')['object']['revision']
        self.bob.request(f'chats/{chat}/delete', dict(expected_revision=revision, acknowledge_managed_copy_deletion=True))

    def test_capture_relationship_references(self):
        note = self.bob.apply([dict(op='create_object', local_ref='note', kind='note',
            title='Synthetic linked work', description='', fields={'content': 'Evidence'})])['local_refs']['note']
        request = envelope(self.bob_id)
        run = reported_run(actor_id=self.bob_id, primary_object_id=note)
        run['consulted_object_ids'] = [note, note]
        request['runs'] = [run]
        chat = self.bob.request('capture', request)['chat_id']
        chat_revision = self.bob.request(f'chats/{chat}')['object']['revision']
        self.bob.apply([dict(op='create_connection', from_id=chat, to_id=note,
            from_revision=chat_revision, to_revision=1, kind='related_to', explanation='Explicit work link')])
        for endpoint in (chat, note):
            edges = self.reader.request(f'connections?object_id={endpoint}')['connections']
            self.assertEqual(len(edges), 1)
            self.assertEqual(edges[0]['from_id'], chat)
            self.assertEqual(edges[0]['to_id'], note)
            self.assertEqual(self.reader.request(f'objects/{endpoint}')['object']['connection_count'], 1)
        self.assertNotIn(chat, [o['id'] for o in self.reader.request('retrieve?q=' + chat)['context']['objects']])
        type(self.admin)(self.bob.base).request(f'chats/{chat}/relationships', status=401)
        refs = self.reader.request(f'chats/{chat}/relationships')['references']
        self.assertIn((self.bob_id, 'participant'), [(r['id'], r['relation']) for r in refs])
        self.assertIn((note, 'linked_run_work'), [(r['id'], r['relation']) for r in refs])
        self.assertIn((run['id'], 'run'), [(r['id'], r['relation']) for r in refs])
        refs = self.reader.request(f'runs/{run["id"]}/relationships')['references']
        self.assertEqual({r['relation'] for r in refs}, {'actor', 'thread', 'primary_object', 'consulted'})
        self.assertEqual(len([r for r in refs if r['relation'] == 'consulted']), 1)
        self.assertEqual(self.reader.request(f'runs/{run["id"]}')['run']['consulted_object_ids'], [note, note])
        first = self.reader.request(f'runs/{run["id"]}/relationships?limit=2')
        second = self.reader.request(f'runs/{run["id"]}/relationships?limit=2&offset={first["next_offset"]}')
        self.assertEqual(first['references'] + second['references'], refs)
        self.assertIsNone(second['next_offset'])
        self.reader.request(f'chats/{chat}/relationships?limit=201', status=422)
        self.reader.request(f'runs/{run["id"]}/relationships?offset=-1', status=422)
        revision = self.bob.request(f'chats/{chat}')['object']['revision']
        self.bob.request(f'chats/{chat}/delete', dict(expected_revision=revision, acknowledge_managed_copy_deletion=True))
        self.reader.request(f'chats/{chat}/relationships', status=410)
        self.reader.request(f'runs/{run["id"]}/relationships', status=404)

    def test_capture_delivery_readership_and_run_history(self):
        client_type = type(self.admin)
        token = self.bob.request('tokens', {'label': 'Capture test', 'write_kinds': ['chat']})
        writer = client_type(self.bob.base, token['token'])
        request = envelope(self.bob_id)
        request['runs'] = [reported_run()]
        client_type(self.bob.base).request('capture', request, 401)
        self.note_agent.request('capture', request, 403)
        self.reader.request('capture', request, 403)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda _: client_type(self.bob.base, token['token']).request(
                'capture', request), range(2)))
        self.assertEqual(receipts[0], receipts[1])
        chat = receipts[0]['chat_id']
        reader = client_type(self.bob.base, self.bob.request('tokens', {
            'label': 'Context only; no capture scope', 'write_kinds': []})['token'])
        detail = reader.request(f'chats/{chat}?limit=2')
        self.assertEqual(detail['readership'], 'all_authenticated')
        self.assertEqual(detail['total'], 3)
        self.assertEqual(detail['next_offset'], 2)
        self.assertEqual([m['id'] for m in detail['items']], [m['id'] for m in request['items'][:2]])
        self.assertEqual(detail['items'][0]['speaker_name'], 'Bob Synthetic')
        self.assertEqual(detail['items'][0]['attribution'], 'caller_attested')
        native = request['items'][0]
        self.admin.apply([dict(op='import_record', source_store='synthetic-cannot-relabel-native',
            record=dict(type='message', message=dict(chat_id=chat, item=native,
                source_ingested_at=None, original=dict(id=native['id'], chat_object_id=chat,
                    provider_message_id=native['source_item_id'], sender_user_object_id=native['speaker_id'],
                    ingested_sequence=native['position'], source_created_at=native['source_created_at'],
                    ingested_at=None, content=native['body']))))], 409)
        self.assertIsNone(reader.request(f'chats/{chat}')['items'][0]['import_provenance'])
        self.assertEqual(detail['items'][1]['tool_call_id'], 'call-a')
        self.assertIsNone(detail['items'][1]['source_created_at'])
        self.assertEqual(reader.request(f'chats/{chat}?offset=2')['items'][0]['body'], request['items'][2]['body'])
        reader.request(f'chats/{chat}?offset=-1', status=422)
        rotated = client_type(self.bob.base, self.bob.request('tokens', {
            'label': 'Rotated capture credential', 'write_kinds': ['chat']})['token'])
        self.assertEqual(rotated.request('capture', request), receipts[0])
        self.admin.request('capture', {**request, 'batch_id': uid(), 'runs': []})  # administrator may reconcile
        other_id = self.admin.request('users', {'username': 'capture-other', 'title': 'Other capture writer',
            'user_kind': 'agent', 'role': 'member'})['id']
        other = client_type(self.bob.base, self.admin.request('tokens', {
            'account_id': other_id, 'label': 'Other writer', 'write_kinds': ['chat']})['token'])
        other.request('capture', request, 403)
        writer.request('capture', {**request, 'title': 'Changed under same batch'}, 409)
        changed = copy.deepcopy(request)
        changed['batch_id'] = uid()
        changed['items'][0]['body'] = 'Changed under same source item'
        writer.request('capture', changed, 409)
        # Read scope is installation-wide, but raw Chats are not ordinary knowledge retrieval.
        self.assertNotIn(chat, [o['id'] for o in reader.request('objects')['objects']])
        self.assertNotIn(chat, [o['id'] for o in reader.request('retrieve?q=' + chat)['context']['objects']])
        run = request['runs'][0]
        update = copy.deepcopy(run)
        update.update(expected_revision=1, status='completed', trace=run['trace'] + [{'step': 'done', 'value': 8}],
                      result={'answer': 11}, review={'verdict': 'mixed', 'notes': 'Supplied review'})
        update_request = {**request, 'batch_id': uid(), 'items': [], 'runs': [update]}
        writer.request('capture', update_request)
        saved = reader.request('runs/' + run['id'])['run']
        self.assertEqual(saved['trace'], update['trace'])
        self.assertEqual(saved['result'], {'answer': 11})
        self.assertEqual(saved['review'], update['review'])
        history = reader.request('runs/' + run['id'] + '/history?limit=1')
        self.assertEqual(history['total'], 2)
        self.assertEqual(history['next_offset'], 1)
        self.assertEqual(history['history'][0]['before_state']['result'], {})
        self.assertEqual(history['history'][0]['after_state']['result'], {'answer': 11})
        first = reader.request('runs/' + run['id'] + '/history?limit=1&offset=1')
        self.assertIsNone(first['history'][0]['before_state'])
        self.assertEqual(first['history'][0]['after_state']['trace'], [{'step': 'started', 'value': 3}])
        for field, value in [('input', {'rewritten': True}), ('trace', []), ('kind', 'changed')]:
            wrong = {**update, 'expected_revision': 2, field: value}
            writer.request('capture', {**update_request, 'batch_id': uid(), 'runs': [wrong]}, 409)
        self.assertEqual(reader.request('runs/' + run['id'])['run']['revision'], 2)
        self.bob.request('tokens/' + token['id'] + '/revoke', {})
        writer.request('capture', request, 401)

    def test_capture_delete_managed_copies_and_pending_delivery(self):
        marker = 'synthetic-raw-' + uid()
        request = envelope(self.bob_id, marker)
        artifact_id, image_id = uid(), uid()
        request['attachments'] = [dict(id=artifact_id, artifact=dict(body=marker, kind='text',
            title=marker, media_type='text/plain', metadata={'supplied': marker})),
            dict(id=image_id, artifact=dict(kind='image', media_type='image/png',
                image_base64='iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAADUlEQVR4nGP4zwAE/wEHAAH/4iOeWQAAAABJRU5ErkJggg=='))]
        request['items'][0]['artifact_ids'] = [artifact_id, image_id]
        request['runs'] = [reported_run()]
        request['runs'][0]['trace'] = [{'output': marker}]
        receipt = self.bob.request('capture', request)
        chat = receipt['chat_id']
        excerpt = self.bob.apply([dict(op='create_object', local_ref='excerpt', kind='note',
            title=marker, description=marker, fields=dict(intent='excerpt', content=marker,
                source_artifact_id=artifact_id, source_locator={'kind': 'text_offset', 'start': 0, 'end': len(marker)}))])['local_refs']['excerpt']
        self.bob.apply([dict(op='append_artifact', object_id=excerpt, expected_revision=1, body=marker)])
        copied_artifact = self.bob.request('objects/' + excerpt)['artifacts'][0]['id']
        nested = self.bob.apply([dict(op='create_object', local_ref='nested', kind='note',
            title=marker, description='', fields=dict(intent='excerpt', content=marker,
                source_artifact_id=copied_artifact, source_locator={'kind': 'text_offset', 'start': 0, 'end': len(marker)}))])['local_refs']['nested']
        # Changing a pointer or intent must not erase already registered raw-copy lineage.
        self.bob.apply([dict(op='update_object', object_id=excerpt, expected_revision=2,
            title=marker, description=marker, fields=dict(intent='insight', content=marker))])
        # Ordinary knowledge keeps its own content rather than inheriting a hidden transcript.
        authored = self.bob.apply([dict(op='create_object', local_ref='authored', kind='note',
            title='Authored conclusion', description='Independent authored knowledge',
            fields=dict(intent='insight', content='A separate conclusion'))])['local_refs']['authored']
        link = self.bob.apply([dict(op='create_connection', from_id=authored, to_id=chat,
            from_revision=1, to_revision=receipt['revision'], kind='derived_from', explanation=marker)])['changes'][0]['connection_id']
        self.assertEqual(self.reader.request('connections/' + link)['connection']['explanation'], marker)
        # A historical event can belong to independent knowledge and still carry
        # the payload of a linked Run. Both correction ownership paths must work.
        event_id = uid()
        historical = dict(op='import_record', source_store='synthetic-linked-history', record=dict(
            type='history', id=event_id, object_id=authored, target_type='object', target_id=authored,
            run_id=request['runs'][0]['id'], action='legacy-review', revision=2, actor_id=None,
            occurred_at='2025-04-01T00:00:00Z', before_state=None, after_state={'original': marker}, provenance={'text': marker}))
        self.admin.apply([historical])
        for target, target_id in [('run', request['runs'][0]['id']), ('event', event_id)]:
            obj = self.bob.request('objects/' + authored)['object']
            self.bob.apply([dict(op='correct_evidence', object_id=authored, expected_revision=obj['revision'],
                target_type=target, target_id=target_id, reason=marker, representation={'assertion': {'text': marker}})])
        revision = self.bob.request('objects/' + chat)['object']['revision']
        self.bob.apply([dict(op='correct_evidence', object_id=chat, expected_revision=revision,
            target_type='message', target_id=request['items'][0]['id'], reason=marker,
            representation={'body': marker + ' corrected'})])
        revision = self.bob.request('objects/' + chat)['object']['revision']
        deletion = dict(expected_revision=revision, acknowledge_managed_copy_deletion=True)
        self.reader.request('chats/' + chat + '/delete', deletion, 403)
        self.bob.request('chats/' + chat + '/delete', {**deletion, 'expected_revision': revision - 1}, 409)
        self.bob.request('chats/' + chat + '/delete', {**deletion, 'acknowledge_managed_copy_deletion': False}, 422)
        temporary = tempfile.TemporaryDirectory(prefix='commons-capture-http-')
        self.addCleanup(temporary.cleanup)
        state = Path(temporary.name)
        uploader = Path(__file__).resolve().parents[1] / 'integrations/capture/commons_capture.py'
        def outbox(*args):
            command = [sys.executable, str(uploader), '--state', str(state / 'outbox'), *map(str, args)]
            return json.loads(subprocess.check_output(command, text=True))
        token = self.bob.request('tokens', {'label': 'Pending delivery test', 'write_kinds': ['chat']})
        token_path = state / 'token'
        token_path.write_text(token['token'])
        token_path.chmod(0o600)
        batch_path = state / 'pending.json'
        batch_path.write_text(json.dumps(request))
        outbox('init', '--url', self.bob.base, '--installation', 'disposable-test')
        outbox('enable', '--provider', request['source']['provider'], '--namespace', request['source']['namespace'],
               '--thread', request['source']['thread_id'], '--scope', 'synthetic-test', '--acknowledge-shared-readership')
        outbox('enqueue', batch_path)
        self.assertGreater(outbox('status')['pending_bytes'], 0)
        self.bob.request('chats/' + chat + '/delete', deletion)
        delivered = outbox('flush', '--token-file', token_path)
        self.assertEqual(delivered['pending_bytes'], 0)
        self.assertEqual(delivered['batches'][0]['state'], 'deleted')
        self.assertNotIn(marker, json.dumps(delivered))
        self.bob.request('capture', request, 410)
        self.bob.request('capture', {**request, 'batch_id': uid()}, 410)
        self.reader.request('chats/' + chat, status=410)
        self.reader.request('runs/' + request['runs'][0]['id'], status=404)
        self.reader.request('runs/' + request['runs'][0]['id'] + '/history', status=404)
        self.reader.request('artifacts/' + artifact_id + '/content', status=410)
        self.reader.request('artifacts/' + image_id + '/content', status=410)
        self.reader.request('artifacts/' + copied_artifact + '/content', status=410)
        for aid in (artifact_id, image_id, copied_artifact):
            self.reader.request('artifacts/' + aid, status=410)
        for oid in (chat, excerpt, nested):
            detail = self.reader.request('objects/' + oid)
            self.assertNotIn(marker, json.dumps(detail))
        detail = self.reader.request('objects/' + authored)
        self.assertNotIn(marker, json.dumps(detail))
        self.assertNotIn(marker, json.dumps(self.reader.request('connections/' + link)))
        knowledge = detail['object']
        self.assertEqual(knowledge['fields']['content'], 'A separate conclusion')
        self.assertIn(chat, knowledge['provenance']['deleted_source_ids'])
        self.assertNotIn(marker, json.dumps(self.reader.request('retrieve?q=' + marker)))
        self.bob.apply([dict(op='append_artifact', object_id=chat, expected_revision=revision+1, body=marker)], 410)
        self.admin.apply([historical], 410)
        self.admin.apply([{**historical, 'record': {**historical['record'], 'id': uid()}}], 410)
        # Reusing a deleted message UUID under a new source cannot revive it.
        replacement = copy.deepcopy(request)
        replacement['source']['thread_id'] = uid()
        replacement['attachments'] = []
        replacement['runs'] = []
        replacement['items'][0]['artifact_ids'] = []
        self.bob.request('capture', replacement, 409)

    def test_historical_run_missing_references_are_explicit_and_import_only(self):
        present = self.memory(title='Historical consulted target')
        deleted, missing = uid(), uid()
        run = reported_run()
        run.update(status='completed', consulted_object_ids=[present, deleted, missing, deleted],
                   review={'verdict': 'mixed', 'reviewed_by': 'legacy-reviewer', 'notes': 'Historical only'})
        original = {**copy.deepcopy(run), 'actor_type': 'system', 'actor_id': 'disabled-routine',
            'available_at': None, 'updated_at': '2026-10-01T00:00:00Z', 'pinned': True}
        evidence = {'manifest_sha256': '1' * 64, 'rows': [dict(table='objects', key={'id': deleted}, row_sha256='2' * 64)]}
        imported = dict(run=run, chat_object_id=None, original=original, references=[
            dict(object_id=present, state='present'), dict(object_id=deleted, state='deleted', purge_evidence=[evidence]),
            dict(object_id=missing, state='missing')])
        operation = dict(op='import_record', source_store='synthetic-legacy-store', record=dict(type='run', run=imported))
        self.bob.apply([operation], 403)
        self.admin.apply([operation])
        self.admin.apply([operation])  # different request key, same imported identity
        saved = self.reader.request('runs/' + run['id'])['run']
        self.assertEqual(saved['consulted_object_ids'], [present, deleted, missing, deleted])
        self.assertEqual(saved['import_provenance']['original'], original)
        self.assertEqual([r['state'] for r in saved['historical_references']], ['present', 'deleted', 'missing'])
        self.assertEqual(saved['historical_references'][1]['purge_evidence'], [evidence])
        references = self.reader.request(f'runs/{run["id"]}/relationships')['references']
        unresolved = {r['id']: r for r in references if r['id'] in (deleted, missing)}
        self.assertEqual(set(unresolved), {deleted, missing})
        self.assertTrue(all(r['title'] is None and r['kind'] is None for r in unresolved.values()))
        self.reader.request('objects/' + deleted, status=404)
        self.reader.request('objects/' + missing, status=404)
        native = envelope(self.bob_id)
        native['runs'] = [{**run, 'id': uid()}]
        self.bob.request('capture', native, 422)
        self.admin.request('capture', {**native, 'history': True}, 422)
        wrong = copy.deepcopy(operation)
        wrong['record']['run']['run']['id'] = uid()
        wrong['record']['run']['original']['id'] = wrong['record']['run']['run']['id']
        wrong['record']['run']['references'][1]['purge_evidence'][0]['rows'][0]['key']['id'] = missing
        self.admin.apply([wrong], 422)
        task = self.memory(kind='task', fields=dict(status='todo', priority='medium', owner_object_id=self.bob_id,
            due_at='2027-01-01T00:00:00Z', work_kind='general', brief_markdown='Synthetic passive history'))
        task_before = self.reader.request('objects/' + task)['object']
        routine = dict(id=uid(), task_id=task, scheduled_for='2025-03-01T03:04:05Z', definition_revision=3,
            status='blocked', execution_thread='synthetic-old-thread', execution_url=None,
            result='Original disabled routine result', created_at='2025-03-01T03:04:06Z', completed_at=None)
        op = dict(op='import_record', source_store='synthetic-legacy-store', record=dict(type='routine_result', original=routine))
        self.bob.apply([op], 403)
        self.admin.apply([op])
        self.admin.apply([op])
        stored = self.reader.request('runs/' + routine['id'])['run']
        self.assertEqual(stored['import_provenance']['original'], routine)
        self.assertEqual(stored['result'], {'text': routine['result']})
        self.assertEqual(stored['status'], 'blocked')
        self.assertIsNone(stored['completed_at'])
        self.assertEqual(self.reader.request('objects/' + task)['object'], task_before)

    def test_historical_chat_messages_and_payload_history_delete_together(self):
        chat_id, message_id, history_id = uid(), uid(), uid()
        marker = 'synthetic-historical-raw-' + uid()
        source = dict(provider='legacy', namespace='synthetic-legacy-store', thread_id=uid())
        original_chat = dict(object_id=chat_id, provider='legacy', thread_id=source['thread_id'],
                             channel_name='Synthetic archive', processing_updated_at=None)
        original_message = dict(id=message_id, chat_object_id=chat_id, provider_message_id='old-message',
            content=marker, sender_user_object_id=self.bob_id, source_created_at=None, ingestion_sequence=18,
            ingested_at='2025-03-03T13:02:01+11:00')
        obj = dict(id=chat_id, kind='chat', title='Historical conversation', description='', fields={},
            revision=8, created_by=None, updated_by=None, created_at='2025-03-02T00:00:00Z',
            updated_at='2025-03-04T00:00:00Z', protected=False, provenance={}, authorship={})
        item = dict(id=message_id, source_item_id='old-message', position=18, kind='message', role='human',
                    speaker_id=self.bob_id, source_created_at=None, body=marker)
        records = [dict(type='object', object=obj),
            dict(type='chat', chat=dict(id=chat_id, source=source, coverage={}, original=original_chat)),
            dict(type='message', message=dict(chat_id=chat_id, item=item, original=original_message,
                source_ingested_at='2025-03-03T13:02:01+11:00')),
            dict(type='history', id=history_id, object_id=chat_id, target_type='object', target_id=chat_id,
                 action='legacy-update', revision=8, actor_id=None, occurred_at='2025-03-04T00:00:00Z',
                 before_state={'title': marker}, after_state={'title': marker}, provenance={'original': marker})]
        operations = [dict(op='import_record', source_store='synthetic-legacy-store', record=r) for r in records]
        contradictory = copy.deepcopy(operations)
        contradictory[2]['record']['message']['original']['ingested_sequence'] = 19
        self.admin.apply(contradictory, 422)
        self.admin.apply(operations)
        read = self.reader.request('chats/' + chat_id)
        self.assertEqual(read['chat']['coverage'], {})  # unknown is never relabelled complete
        self.assertEqual(read['chat']['import_provenance']['original'], original_chat)
        self.assertEqual(read['items'][0]['import_provenance']['original'], original_message)
        self.assertIsNone(read['items'][0]['source_created_at'])
        self.assertEqual(datetime.datetime.fromisoformat(read['items'][0]['source_ingested_at']),
                         datetime.datetime(2025, 3, 3, 2, 2, 1, tzinfo=datetime.timezone.utc))
        self.assertNotEqual(read['items'][0]['received_at'], read['items'][0]['source_ingested_at'])
        self.assertEqual(read['items'][0]['position'], 18)
        self.assertEqual(self.reader.request('objects/' + chat_id)['object']['revision'], 8)
        self.admin.request('chats/' + chat_id + '/delete', {
            'expected_revision': 8, 'acknowledge_managed_copy_deletion': True})
        self.assertNotIn(marker, json.dumps(self.reader.request('objects/' + chat_id)))
        self.admin.apply(operations, 410)  # new apply key cannot bypass the source tombstone
