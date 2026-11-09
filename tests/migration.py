"""Sample transfer behavior against the real isolated foundation API."""
import base64
import copy
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import uuid
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations/migration"))
import context_transfer as transfer
from context_source import normalize_artifact, normalize_message, normalize_run
from context_package import produce


class MigrationTests:
    def test_full_snapshot_batches_resume_after_lost_committed_response(self):
        users = [str(uuid.uuid4()) for _ in range(55)]
        image_id = str(uuid.uuid4())
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAADUlEQVR4nGP4zwAE/wEHAAH/4iOeWQAAAABJRU5ErkJggg==')
        # A valid ancillary chunk makes the original larger than the account-avatar limit.
        comment = b'tEXt' + b'Comment\x00' + b'original profile evidence ' * 14000
        png = png[:-12] + struct.pack('!I', len(comment)-4) + comment + struct.pack('!I', zlib.crc32(comment)) + png[-12:]
        image_hash = hashlib.sha256(png).hexdigest()
        profile = dict(id='original-profile', provider='legacy', provider_user_id='original-user',
            avatar_asset_filename='original-profile.png', avatar_asset_sha256=image_hash, avatar_url=None)
        rows = {'objects': [], 'users': []}
        actors = [dict(source_type='system', source_id='bootstrap', user_id=None)]
        for i, uid in enumerate(users):
            actor_type, actor_id = ('system', 'bootstrap') if i == 0 else ('human', users[i-1])
            if i:
                actors.append(dict(source_type=actor_type, source_id=actor_id, user_id=actor_id))
            obj = dict(id=uid, kind='user', title=f'Full historical user {i}', description='Original α\r\n',
                revision=3, created_at='2020-01-01T00:00:00Z', updated_at='2020-01-01T00:00:00Z',
                archived_at=None, protected=True, provenance={}, created_by_type=actor_type,
                created_by_id=actor_id, updated_by_type=actor_type, updated_by_id=actor_id)
            for table, value, key in (('objects', obj, 'id'),
                    ('users', dict(object_id=uid, object_kind='user', user_kind='human', identities=[profile] if i == 0 else []), 'object_id')):
                rows[table].append(dict(key={key:uid}, row=value, row_sha256=transfer.digest(transfer.encoded(value))))
        counts = {t: len(v) for t, v in rows.items()}
        catalog = {t: dict(row_count=n) for t, n in counts.items()}
        raw = dict(version='commons.context-rows/1', rows=rows, opening_catalog=catalog, closing_catalog=catalog,
            observed_counts=[counts, counts], consistency='fenced_full_snapshot_two_equal_observations',
            selection=dict(scope='full', source_store='synthetic-full:'+users[0], source_revision='synthetic',
                snapshot_id='frozen-full', excluded_tables={}, snapshot=dict(kind='isolated_restore',
                    backup_sha256='a'*64, writer_fence='Synthetic restore without writers')))
        mapping = dict(version='commons.context-mapping/1', source_store=raw['selection']['source_store'],
            snapshot_id='frozen-full', destination=dict(origin=self.admin.base, admin_user_id=self.admin_id),
            actors=actors, existing_user_ids=[], files=[], identity_assets=[dict(user_id=users[0], artifact_id=image_id,
                identity_id=profile['id'], reference=profile['avatar_asset_filename'], media_type='image/png',
                sha256=image_hash, size_bytes=len(png), image_base64=base64.b64encode(png).decode(),
                represented_at='2026-10-20T07:00:00Z')])
        package = produce(raw, mapping)
        self.assertEqual(package['version'], transfer.FULL_VERSION)
        self.assertEqual([len(g['records']) for g in package['groups']], [50, 6])
        self.assertEqual(package['source_evidence']['identity_asset_count'], 1)
        self.assertEqual(package['source_evidence']['selected_counts'], counts)
        self.assertEqual(package['record_counts'], dict(object=55, artifact=1))
        for key, value in [('reference', 'wrong.png'), ('sha256', 'f'*64), ('size_bytes', len(png)-1),
                           ('user_id', str(uuid.uuid4())), ('artifact_id', '../../escape')]:
            bad = copy.deepcopy(mapping)
            bad['identity_assets'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                produce(raw, bad)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, value in [('rows', raw), ('mapping', mapping)]:
                path = root / (name+'.json')
                path.write_bytes(transfer.encoded(value)); path.chmod(0o600)
            subprocess.run([sys.executable, 'integrations/migration/context_package.py',
                str(root/'rows.json'), str(root/'mapping.json'), str(root/'package')], check=True, capture_output=True)
            self.assertEqual(transfer.load_package(root/'package'), package)
            self.assertEqual((root/'package'/package['files'][0]['path']).read_bytes(), png)
        real = transfer.Session(self.admin.base)
        real.login('admin', self.password)
        class LoseResponse:
            origin = real.origin
            calls = 0
            def request(self, route, body=None):
                result = real.request(route, body)
                if route == 'apply':
                    self.calls += 1
                    if self.calls == 2:
                        raise RuntimeError('Synthetic full batch response lost')
                return result
        with tempfile.TemporaryDirectory() as state:
            with self.assertRaisesRegex(RuntimeError, 'response lost'):
                transfer.transfer(package, state, LoseResponse())
            result = transfer.transfer(package, state, real)
            self.assertEqual((result['checkpoint_skipped_groups'], result['acknowledged_groups']), (1, 1))
            for entry in rows['objects']:
                actual = self.reader.request('objects/'+entry['row']['id'])['object']
                self.assertEqual(actual['import_provenance']['original_authorship']['object'], entry['row'])
            active = {u['id'] for u in self.admin.request('users')['users']}
            self.assertTrue(active.isdisjoint(users))
            historical = self.reader.request('objects/'+users[0])
            self.assertEqual(historical['object']['fields']['identities'], [profile])
            avatar = historical['object']['fields']['avatar_asset_url']
            self.assertEqual(avatar, '/api/artifacts/'+image_id+'/content')
            self.assertEqual(historical['artifacts'][0]['sha256'], image_hash)
            self.assertIsNone(historical['artifacts'][0]['created_by'])
            self.assertIsNone(historical['artifacts'][0]['captured_at'])
            self.assertFalse(historical['artifacts'][0]['semantic_indexing_enabled'])
            with real.opener.open(real.origin + avatar) as response:
                self.assertEqual(response.headers['Content-Type'], 'image/png')
                self.assertEqual(response.read(), png)
            self.assertEqual(transfer.transfer(package, state, real, replay=True)['acknowledged_groups'], 2)
            self.assertEqual(self.reader.request('objects/'+users[0]), historical)

    def test_raw_selection_packages_all_types_without_losing_originals(self):
        ids = {k: str(uuid.uuid4()) for k in ('user', 'task', 'memory', 'source', 'note', 'theme',
            'entity', 'event', 'chat', 'category', 'artifact', 'message', 'run', 'connection', 'history',
            'outside_history', 'outside_run', 'correction', 'routine_result', 'deleted')}
        time = '2020-02-03T04:05:06Z'
        rows = {}
        def row(table, value, keys=('id',)):
            rows.setdefault(table, []).append(dict(key={k: value[k] for k in keys},
                row=value, row_sha256=transfer.digest(transfer.encoded(value))))
        author = dict(created_by_type='system', created_by_id='original-opaque',
                      updated_by_type='human', updated_by_id='original-human')
        subtypes = {
            'user': ('users', dict(user_kind='human', identities=[])),
            'task': ('tasks', dict(status='todo', priority='high', owner_object_id=None,
                agent_suitable=True, blocked_reason=None, due_at=None, completed_at=None,
                work_kind='general', github_issue_url=None, brief_markdown=None, execution_actor_id='inert-only')),
            'memory': ('memories', dict(happened_at=None)),
            'source': ('sources', dict(source_kind='article', canonical_uri=None, byline='Original byline',
                publisher=None, published_at=None, published_at_precision=None, last_accessed_at=None,
                original_language=None, original_media_type=None, original_artifact_reference='relative/original.pdf',
                current_artifact_id=ids['artifact'])),
            'note': ('notes', dict(content='Exact α\r\nexcerpt', content_format='plain_text', intent='excerpt',
                source_artifact_id=ids['artifact'], source_locator={'unit': 'original', 'start': 0, 'end': 5})),
            'theme': ('themes', dict(slug='sample-' + ids['theme'])),
            'entity': ('entities', dict(entity_kind='project', image_url=None, primary_category_id=ids['category'])),
            'event': ('real_world_events', dict(starts_at='2020-03', starts_at_precision='month',
                ends_at=None, ends_at_precision=None, timezone=None)),
            'chat': ('chats', dict(provider='legacy', provider_thread_id='original-thread', surface='desktop')),
        }
        for kind, (table, fields) in subtypes.items():
            row('objects', dict(id=ids[kind], kind=kind, title='Synthetic raw '+kind, description='Original α\r\n',
                revision=7, created_at=time, updated_at=time, archived_at=time if kind=='memory' else None,
                protected=True, provenance={'supplied': True}, explicitly_corrected=False, **author))
            row(table, dict(object_id=ids[kind], object_kind=kind, **fields), ('object_id',))
        row('entity_categories', dict(id=ids['category'], slug='category-'+ids['category'], label='Synthetic '+ids['category'],
            definition='Original classification', aliases=[], legacy_kind='project', revision=2,
            created_at=time, updated_at=time, archived_at=None, **author))
        row('entity_category_assignments', dict(entity_object_id=ids['entity'], category_id=ids['category']),
            ('entity_object_id', 'category_id'))
        text = 'Exact α\r\noriginal capture'
        row('artifacts', dict(id=ids['artifact'], object_id=ids['source'], kind='text', title='Null media',
            content=text, uri=None, media_type=None, language=None, sha256=hashlib.sha256(text.encode()).hexdigest(),
            size_bytes=len(text.encode()), capture_outcome='complete', capture_reason=None,
            expected_size_bytes=None, semantic_indexing_enabled=True, metadata={}, supersedes_artifact_id=None,
            captured_at=None, created_at=time))
        row('chat_messages', dict(id=ids['message'], chat_object_id=ids['chat'], provider_message_id='original-message',
            sender_user_object_id=ids['user'], content='Original message α\r\n', ingestion_sequence=13,
            source_created_at=None, ingested_at=time))
        receipt = dict(rows=[dict(table='objects', key={'id':ids['deleted']}, row_sha256='b'*64)],
            manifest_sha256='c'*64, counts={'objects':1}, retained_reference_count=1, recovery_export_sha256='d'*64)
        receipt_row = dict(principal_id='original-operator', idempotency_key='original-purge',
            created_at=time, manifest_sha256='c'*64, request_sha256='e'*64, receipt=receipt)
        row('maintenance_purge_receipts', receipt_row, ('principal_id', 'idempotency_key'))
        row('runs', dict(id=ids['run'], parent_run_id=None, chat_object_id=ids['chat'], primary_object_id=ids['task'],
            kind='curator', status='completed', actor_type='system', actor_id='original-opaque',
            input={'first_message_id': ids['message'], 'last_message_id': ids['message']}, trace=[], result={'text': 'Original'},
            error=None, consulted_object_ids=[ids['source'], ids['deleted']], verdict=None, review_notes=None, reviewed_by=None,
            reviewed_at=None, created_at=time, started_at=None, completed_at=time))
        row('connections', dict(id=ids['connection'], source_object_id=ids['task'], target_object_id=ids['source'],
            kind='related_to', description='Original relationship α', revision=4, created_at=time, updated_at=time,
            archived_at=None, protected=True, provenance={}, **author))
        for key, run in (('history', ids['run']), ('outside_history', ids['outside_run'])):
            row('object_events', dict(id=ids[key], run_id=run, sequence=3, target_type='object', target_id=ids['task'],
                action='updated', actor_type='system', actor_id='original-opaque', idempotency_key='historical-only',
                from_revision=5, to_revision=6, before_state={'brief_markdown': None}, after_state={'original': 'unchanged'},
                reversible=True, created_at=time))
        row('evidence_corrections', dict(id=ids['correction'], object_id=ids['source'], object_revision=7,
            target_type='artifact', target_id=ids['artifact'], representation={'text': 'Supplied correction'},
            reason='Historical correction', supersedes_correction_id=None, actor_type='system', actor_id='original-opaque', created_at=time))
        row('task_routines', dict(task_id=ids['task'], schedule={'original': 'never activate'}, enabled=False,
            definition_revision=6, next_run_at=None, updated_at=time), ('task_id',))
        row('task_routine_runs', dict(id=ids['routine_result'], task_id=ids['task'], scheduled_for=time,
            definition_revision=6, status='completed', execution_thread=None, execution_url=None,
            result='Original routine result', created_at=time, completed_at=time))
        raw = dict(version='commons.context-rows/1', selection=dict(scope='sample', source_store='synthetic:'+ids['source'],
            source_revision='synthetic-physical', snapshot_id='frozen-selection'), rows=rows,
            opening_catalog={}, closing_catalog={}, consistency='two_equal_observations_not_an_atomic_snapshot')
        mappings = dict(version='commons.context-mapping/1', source_store=raw['selection']['source_store'],
            snapshot_id='frozen-selection', destination=dict(origin=self.admin.base, admin_user_id=self.admin_id),
            actors=[dict(source_type='system', source_id='original-opaque', user_id=None),
                    dict(source_type='human', source_id='original-human', user_id=ids['user'])],
            existing_user_ids=[self.bob_id], task_owners={ids['task']:self.bob_id}, artifact_creators={ids['artifact']: None},
            chats={ids['chat']: dict(source=dict(provider='legacy', namespace='synthetic-source', thread_id=ids['chat']),
                                    parent_chat_id=None, coverage={})},
            run_references={ids['run']: [dict(object_id=ids['source'], state='present'),
                dict(object_id=ids['deleted'], state='deleted', purge_evidence=[receipt])]},
            history_run_references={ids['history']: dict(run_id=ids['run'], state='included', reason='Selected terminal Run'),
                ids['outside_history']: dict(run_id=ids['outside_run'], state='out_of_sample', reason='Known source Run outside bounded sample')},
            files=[dict(reference='relative/original.pdf', status='unresolved', reason='Original base path not established')])
        package = produce(raw, mappings)
        self.assertEqual(package['record_counts'], dict(object=9, category=1, artifact=1, chat=1, message=1,
            run=1, routine_result=1, connection=1, history=2, correction=1))
        self.assertEqual(package['source_evidence']['selected_counts'], {k:len(v) for k,v in rows.items()})
        self.assertEqual(package['source_evidence']['purge_receipts'], [receipt_row])
        for broken in ('artifact', 'owner', 'orphan', 'outside', 'receipt'):
            r, m = copy.deepcopy(raw), copy.deepcopy(mappings)
            if broken=='artifact': r['rows']['artifacts']=[]
            if broken=='owner': m['task_owners']={}
            if broken=='orphan': r['rows']['notes'].append(dict(key={'object_id':ids['outside_run']}, row={'object_id':ids['outside_run']}))
            if broken=='outside': m['history_run_references'][ids['outside_history']]['state']='missing'
            if broken=='receipt': m['run_references'][ids['run']][1]['purge_evidence'][0]['counts']['objects']=2
            with self.subTest(broken=broken), self.assertRaises((ValueError, KeyError)):
                produce(r, m)
        session = transfer.Session(self.admin.base)
        session.login('admin', self.password)
        with tempfile.TemporaryDirectory() as state:
            transfer.transfer(package, state, session)
            for kind in subtypes:
                actual = self.reader.request('objects/'+ids[kind])['object']
                original = actual['import_provenance']['original_authorship']
                self.assertEqual(original['object'], next(e['row'] for e in rows['objects'] if e['row']['id']==ids[kind]))
                self.assertEqual(original['subtype'], subtypes[kind][1] | {'object_id':ids[kind], 'object_kind':kind})
            task = self.reader.request('objects/'+ids['task'])
            self.assertIsNone(task['object']['fields']['brief_markdown'])
            self.assertEqual(task['object']['fields']['owner_object_id'],self.bob_id)
            self.assertEqual(task['object']['import_provenance']['original_authorship']['routine_definition'],rows['task_routines'][0]['row'])
            histories={h['id']:h for h in task['history']}
            for key in ('history', 'outside_history'):
                original=histories[ids[key]]['import_provenance']['original']
                self.assertEqual(original['row'],next(e['row'] for e in rows['object_events'] if e['row']['id']==ids[key]))
                self.assertEqual(original['run_reference'],mappings['history_run_references'][ids[key]])
            self.assertIsNone(histories[ids['outside_history']]['run_id'])
            self.assertEqual(histories[ids['history']]['run_id'],ids['run'])
            source=self.reader.request('objects/'+ids['source'])
            self.assertEqual(source['artifacts'][0]['body'],text)
            self.assertIsNone(source['artifacts'][0]['media_type'])
            self.assertEqual(source['corrections'][0]['representation'],{'text':'Supplied correction'})
            saved_run = self.reader.request('runs/'+ids['run'])['run']
            self.assertEqual(saved_run['historical_references'][1]['purge_evidence'], [receipt])
            self.reader.request('objects/'+ids['deleted'], status=404)
            self.assertEqual(self.reader.request('runs/'+ids['routine_result'])['run']['kind'],'historical_task_routine')
            self.assertEqual(self.reader.request('chats/'+ids['chat'])['items'][0]['body'],'Original message α\r\n')
            self.reader.request('runs/'+ids['outside_run'],status=404)
            transfer.transfer(package, state, session, replay=True)
            self.assertEqual(self.reader.request('objects/'+ids['task']),task)

    def test_sample_transfer_interruption_replay_and_conflict(self):
        actor, source, task, text_id, older_id, image_id, history_id, link_id = [str(uuid.uuid4()) for _ in range(8)]
        def obj(id, kind, fields):
            return dict(type="object", object=dict(id=id, kind=kind, title="Synthetic transfer " + kind,
                description="Original snapshot", fields=fields, revision=7, created_by=None, updated_by=None,
                created_at="2020-01-01T00:00:00Z", updated_at="2021-01-01T00:00:00Z",
                archived_at=None, protected=True, provenance={}, authorship={"created_by_id": "opaque-source"}))
        user = obj(actor, "user", {"user_kind": "human"})
        legacy = obj(task, "task", dict(status="todo", priority="medium", owner_object_id=None,
            due_at=None, work_kind="general", brief_markdown="Original unassigned task"))
        legacy["object"]["owner_mapping"] = dict(source_owner_id=None, destination_owner_id=self.bob_id)
        body = "Original αβ evidence\r\n" * 60000
        def chunk(kind, data):
            return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", 2, 1, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\x00\x00\xff")) + chunk(b"IEND", b""))
        def artifact(id, data, **fields):
            return dict(id=id, object_id=source, kind="document", title="Original capture",
                created_at="2020-02-01T00:00:00Z", sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
                uri=None, media_type="text/plain", language=None, capture_outcome="complete", capture_reason=None,
                expected_size_bytes=None, semantic_indexing_enabled=False, metadata={"document_key": "original"},
                captured_at=None, **fields)
        raw_older = artifact(older_id, b"Older exact version\r\n", content="Older exact version\r\n", supersedes_artifact_id=None)
        raw_document = artifact(text_id, body.encode(), content=body, supersedes_artifact_id=older_id)
        raw_image = {**artifact(image_id, png, content=None, supersedes_artifact_id=None),
                     "kind": "research_visual", "media_type": "image/png"}
        binary = dict(artifact_id=image_id, bytes="\\x" + png.hex(), media_type="image/png", width=2, height=1)
        older = normalize_artifact(raw_older, None, created_by=actor)
        document = normalize_artifact(raw_document, None, created_by=actor)
        image = normalize_artifact(raw_image, binary, created_by=actor)
        history = dict(type="history", id=history_id, object_id=task, target_type="object", target_id=task,
            action="updated", revision=6, actor_id=actor, occurred_at="2020-03-01T00:00:00Z",
            before_state={"owner_object_id": None}, after_state={"due_at": None}, provenance={"sequence": 9})
        link = dict(type="connection", id=link_id, from_id=task, to_id=source, kind="related_to",
            explanation="Original evidence", revision=3, created_by=actor, created_at="2020-02-01T00:00:00Z",
            updated_at="2020-03-01T00:00:00Z", archived_at=None, protected=True, provenance={})
        chat_id, message_id = str(uuid.uuid4()), str(uuid.uuid4())
        raw_message = dict(id=message_id, chat_object_id=chat_id, provider_message_id="original-message",
            sender_user_object_id=actor, content="Original conversation α\r\n", ingestion_sequence=23,
            source_created_at=None, ingested_at="2020-02-01T00:00:00Z")
        message = normalize_message(raw_message, dict(object_id=actor, user_kind="human"))
        chat = dict(type="chat", chat=dict(id=chat_id,
            source=dict(provider="legacy", namespace="synthetic-source", thread_id=chat_id),
            coverage={}, original=dict(object_id=chat_id, provider="legacy", thread_id=chat_id)))
        run_id, deleted, missing = [str(uuid.uuid4()) for _ in range(3)]
        raw_run = dict(id=run_id, parent_run_id=None, chat_object_id=chat_id, primary_object_id=task,
            kind="curator", status="completed", actor_type="system", actor_id="disabled-old-routine",
            input={"original": "input"}, trace=[{"attempt": 1}], result={"text": "Original result α\r\n"},
            error=None, consulted_object_ids=[source, deleted, missing, deleted], verdict="mixed",
            review_notes="Original review", reviewed_by="historical-reviewer", reviewed_at="2020-03-03T00:00:00Z",
            created_at="2020-03-02T00:00:00Z", started_at=None, completed_at=None, available_at=None, pinned=True)
        purge_receipt = dict(rows=[dict(table="objects", key={"id": deleted}, row_sha256="a" * 64)])
        run = normalize_run(raw_run, [dict(object_id=source, state="present"),
            dict(object_id=deleted, state="deleted", purge_evidence=[purge_receipt]),
            dict(object_id=missing, state="missing")], actor_id=None)
        package = dict(version=transfer.VERSION, scope="sample", source_store="synthetic:" + str(uuid.uuid4()),
            source_revision="synthetic-context-v1", snapshot_id="selected-connected-sample", files=[],
            destination=dict(origin=self.admin.base, admin_user_id=self.admin_id),
            record_counts=dict(object=4, artifact=3, history=1, connection=1, chat=1, message=1, run=1), groups=[
                dict(id="task-links", depends_on=["source"], records=[legacy, run, history, link]),
                dict(id="source", depends_on=["user"], records=[obj(source, "source", {
                    "source_kind": "article", "current_artifact_id": text_id}), older, document, image,
                    obj(chat_id, "chat", {}), chat, message]),
                dict(id="user", depends_on=[], records=[user])])
        def session(username="admin"):
            value = transfer.Session(self.admin.base)
            value.login(username, self.password)
            return value
        real = session()
        class LoseResponse:
            origin = real.origin
            calls = 0
            def request(self, route, body=None):
                result = real.request(route, body)
                if route == "apply":
                    self.calls += 1
                    if self.calls == 2:
                        raise RuntimeError("Synthetic lost response after committed source group")
                return result
        with tempfile.TemporaryDirectory() as state:
            with self.assertRaisesRegex(ValueError, "administrator"):
                transfer.transfer(package, state, session("reader"))
            wrong_target = copy.deepcopy(package)
            wrong_target["destination"]["admin_user_id"] = self.bob_id
            with self.assertRaisesRegex(ValueError, "administrator"):
                transfer.transfer(wrong_target, state, real)
            with self.assertRaisesRegex(RuntimeError, "lost response"):
                transfer.transfer(package, state, LoseResponse())
            self.reader.request("objects/" + task, status=404)
            result = transfer.transfer(package, state, real)
            self.assertEqual(result["checkpoint_skipped_groups"], 1)
            self.assertEqual(result["acknowledged_groups"], 2)
            detail = self.reader.request("objects/" + source)
            self.assertEqual(len(detail["artifacts"]), 3)
            saved_document = next(a for a in detail["artifacts"] if a["id"] == text_id)
            self.assertEqual(saved_document["body"], body)
            self.assertEqual(saved_document["supersedes_artifact_id"], older_id)
            self.assertEqual(saved_document["import_provenance"]["original"]["artifact"], raw_document)
            self.assertEqual(next(a for a in detail["artifacts"] if a["id"] == older_id)["body"], "Older exact version\r\n")
            self.assertEqual(next(a for a in detail["artifacts"] if a["id"] == image_id)["sha256"], hashlib.sha256(png).hexdigest())
            with real.opener.open(real.origin + "/api/artifacts/" + image_id + "/content") as response:
                self.assertEqual(response.read(), png)
            detail = self.reader.request("objects/" + task)
            self.assertEqual(detail["object"]["fields"]["owner_object_id"], self.bob_id)
            self.assertIsNone(detail["object"]["fields"]["due_at"])
            self.assertEqual(detail["history"][0]["before_state"], history["before_state"])
            saved_link = self.reader.request("connections/" + link_id)
            self.assertEqual(saved_link["connection"]["to_id"], source)
            self.assertNotIn(actor, [u["id"] for u in self.admin.request("users")["users"]])
            saved_message = self.reader.request("chats/" + chat_id)["items"][0]
            self.assertEqual(saved_message["import_provenance"]["original"], raw_message)
            self.assertEqual(saved_message["body"], "Original conversation α\r\n")
            self.assertEqual(saved_message["position"], 23)
            saved_run = self.reader.request("runs/" + run_id)["run"]
            self.assertEqual(saved_run["import_provenance"]["original"], raw_run)
            self.assertEqual(saved_run["consulted_object_ids"], [source, deleted, missing, deleted])
            self.assertEqual([r["state"] for r in saved_run["historical_references"]], ["present", "deleted", "missing"])
            self.assertEqual(saved_run["historical_references"][1]["purge_evidence"], [purge_receipt])
            self.assertIsNone(saved_run["actor_id"])
            self.reader.request("objects/" + deleted, status=404)
            self.reader.request("objects/" + missing, status=404)
            fields = {**detail["object"]["fields"], "owner_object_id": self.admin_id, "priority": "high"}
            self.admin.apply([dict(op="update_object", object_id=task, expected_revision=7,
                title="Later destination edit", description="Keep this", fields=fields)])
            edited = self.reader.request("objects/" + task)
            # New login has no cached apply receipts: exercise durable record identity replay.
            self.assertEqual(transfer.transfer(package, state, session(), replay=True)["acknowledged_groups"], 3)
            self.assertEqual(self.reader.request("objects/" + task), edited)
            changed = copy.deepcopy(package)
            changed["groups"][0]["records"][0]["object"]["title"] = "Changed source snapshot"
            with self.assertRaisesRegex(ValueError, "checkpoint"):
                transfer.transfer(changed, state, real)
            with tempfile.TemporaryDirectory() as fresh_state:
                with self.assertRaisesRegex(RuntimeError, "HTTP 409"):
                    transfer.transfer(changed, fresh_state, real)
            self.assertEqual(self.reader.request("objects/" + task), edited)
