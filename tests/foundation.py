#!/usr/bin/env python3
"""Public HTTP acceptance against an isolated, uniquely-created local database.

Run from repo root after scripts/dev-init: source scripts/dev-env; python3 tests/foundation.py
Never points at the application database: creates and drops only its own commons_test_* DB.
"""
import concurrent.futures
import copy
import datetime
import hashlib
import http.cookiejar
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid

from evals import EvalTests
from capture import CaptureTests
from migration import MigrationTests

class Client:
    def __init__(self, base, token=None):
        self.base = base
        self.token = token
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, path, body=None, status=200, origin=None, extra=None):
        headers = {'Content-Type': 'application/json', 'Origin': origin or self.base}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        headers.update(extra or {})
        req = urllib.request.Request(self.base + '/api/' + path, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            response = self.opener.open(req)
        except urllib.error.HTTPError as e:
            response = e
        data = response.read()
        assert response.code == status, (path, response.code, status, data[:500])
        return json.loads(data)

    def apply(self, operations, status=200, key=None, **options):
        return self.request('apply', {'contract_version': 'commons/0.1',
            'idempotency_key': key or str(uuid.uuid4()), 'operations': operations, **options}, status)


def create(kind='memory', title='Synthetic retention decision', fields=None):
    return {'op': 'create_object', 'local_ref': 'new', 'kind': kind, 'title': title,
            'description': 'Synthetic business knowledge, supplied by an external caller.', 'fields': fields or {}}


class Foundation(EvalTests, CaptureTests, MigrationTests, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = PASSWORD
        cls.admin = Client(BASE)
        cls.admin.request('login', {'username': 'admin', 'password': PASSWORD})
        cls.admin_id = cls.admin.request('me')['id']
        cls.bob_id = cls.admin.request('users', {'username': 'bob', 'title': 'Bob Synthetic',
                                               'password': PASSWORD, 'role': 'member'})['id']
        cls.admin.request('users', {'username': 'reader', 'title': 'Reader Synthetic',
                                   'password': PASSWORD, 'role': 'reader'})
        cls.bob = Client(BASE)
        cls.bob.request('login', {'username': 'bob', 'password': PASSWORD})
        cls.reader = Client(BASE)
        cls.reader.request('login', {'username': 'reader', 'password': PASSWORD})
        cls.agent_receipt = cls.bob.request('tokens', {'label': 'Synthetic Amp fixture',
                                                    'write_kinds': ['task', 'memory', 'note']})
        cls.agent = Client(BASE, cls.agent_receipt['token'])
        cls.note_agent = Client(BASE, cls.bob.request('tokens', {'label': 'No Memory authority',
                                                               'write_kinds': ['note']})['token'])

    def memory(self, client=None, **kw):
        return (client or self.agent).apply([create(**kw)])['local_refs']['new']

    def test_compact_reads_page_related_metadata_and_keep_owner_fields(self):
        oid = self.memory(title='Synthetic compact evidence')
        for revision in range(1, 4):
            self.agent.apply([{'op':'append_artifact','object_id':oid,
                'expected_revision':revision,'body':'private synthetic body '+str(revision)}])
        full = self.agent.request('objects/'+oid)
        first = self.agent.request('objects/'+oid+'?view=compact&limit=1')
        self.assertEqual(first['object'],full['object'])
        self.assertEqual(first['view'],'compact')
        self.assertNotIn('private synthetic body',json.dumps(first))
        self.assertTrue(first['artifacts'][0]['body_omitted'])
        self.assertTrue(first['history'][0]['state_omitted'])
        seen, offset = [], 0
        while offset is not None:
            page = self.agent.request(f'objects/{oid}?view=compact&limit=1&offset={offset}&expected_revision=4')
            seen += [a['id'] for a in page['artifacts']]
            offset = page['page']['next_offset']
        self.assertEqual(seen,[a['id'] for a in full['artifacts']])
        history = first['history'][0]
        readback = self.reader.request('history/'+history['id'])['history']
        self.assertEqual(readback,full['history'][0])
        self.agent.request(f'objects/{oid}?view=compact&offset=1',status=422)
        self.agent.apply([{'op':'append_artifact','object_id':oid,'expected_revision':4,'body':'later'}])
        self.agent.request(f'objects/{oid}?view=compact&offset=1&expected_revision=4',status=409)
        Client(BASE).request('history/'+history['id'],status=401)

    def test_compound_read_matches_one_revision_during_writes(self):
        oid = self.memory(title='Synthetic coherent read')
        def append():
            for revision in range(1, 16):
                self.agent.apply([{'op':'append_artifact','object_id':oid,
                    'expected_revision':revision,'body':f'evidence {revision}'}])
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            writing = pool.submit(append)
            for _ in range(30):
                detail = self.reader.request('objects/'+oid)
                revision = detail['object']['revision']
                self.assertEqual(len(detail['artifacts']), revision-1)
                self.assertEqual(max(e['revision'] for e in detail['audit_events']), revision)
            writing.result()

    def test_artifact_text_windows_preserve_unicode_and_boundaries(self):
        oid = self.memory(title='Synthetic windowed evidence')
        body = 'aé🙂\r\n終' * 13
        result = self.agent.apply([{'op':'append_artifact','object_id':oid,
            'expected_revision':1,'body':body}])
        aid = result['changes'][0]['artifact_id']
        offset, chunks = 0, []
        while offset is not None:
            page = self.agent.request(f'artifacts/{aid}/text?offset={offset}&limit=7')
            self.assertEqual(page['total_characters'],len(body))
            self.assertEqual(page['offset'],offset)
            self.assertLessEqual(len(page['text']),7)
            self.assertEqual(page['sha256'],hashlib.sha256(body.encode()).hexdigest())
            chunks.append(page['text']); offset = page['next_offset']
        self.assertEqual(''.join(chunks),body)
        end = self.reader.request(f'artifacts/{aid}/text?offset={len(body)}&limit=7')
        self.assertEqual(end['text'],''); self.assertIsNone(end['next_offset'])
        for query in ('offset=-1','limit=0','limit=48001',f'offset={len(body)+1}'):
            self.agent.request(f'artifacts/{aid}/text?{query}',status=422)
        Client(BASE).request(f'artifacts/{aid}/text',status=401)

    def test_rich_document_versions(self):
        oid = self.memory(title='Synthetic versioned research')
        body = '# Research\n' + ('Unicode λ evidence.\n' * 65000)
        self.assertGreater(len(body.encode()), 1168247)
        def save(rev, content, predecessor=None):
            return dict(op='save_artifact', object_id=oid, expected_revision=rev,
                        artifact=dict(kind='research_notes', title='Study', body=content,
                                      media_type='text/markdown', metadata={'document_key': 'study'},
                                      supersedes_artifact_id=predecessor))
        first = self.agent.apply([save(1, body)])['changes'][0]['artifact_id']
        detail = self.reader.request('objects/' + oid)
        artifact = detail['artifacts'][0]
        self.assertEqual(artifact['body'], body)
        self.assertEqual(artifact['sha256'], hashlib.sha256(body.encode()).hexdigest())
        self.assertEqual(artifact['size_bytes'], len(body.encode()))
        second = self.agent.apply([save(2, 'Replacement cobalt-heron', first)])['changes'][0]['artifact_id']
        self.agent.apply([save(2, 'Stale draft', first)], 409)
        self.agent.apply([save(3, 'Fork rejected', first)], 409)
        self.reader.apply([save(3, 'Denied', second)], 403)
        self.note_agent.apply([save(3, 'Wrong scope', second)], 403)
        detail = self.reader.request('objects/' + oid)
        self.assertEqual([a['body'] for a in detail['artifacts']], [body, 'Replacement cobalt-heron'])
        self.assertEqual(detail['artifacts'][1]['supersedes_artifact_id'], first)
        self.assertEqual(detail['object']['revision'], 3)

    def test_image_bytes_and_capture_completeness(self):
        import base64, struct, zlib
        def chunk(kind, data):
            return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
        png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 2, 1, 8, 2, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00\x00\x00\xff')) + chunk(b'IEND', b''))
        oid = self.memory()
        image = dict(kind='research_visual', title='Red and blue fixture', media_type='image/png',
                     image_base64=base64.b64encode(png).decode(), semantic_indexing_enabled=False)
        op = dict(op='save_artifact', object_id=oid, expected_revision=1, artifact=image)
        self.agent.apply([{**op, 'artifact': {**image, 'media_type': 'image/jpeg'}}], 422)
        self.agent.apply([{**op, 'artifact': {**image, 'semantic_indexing_enabled': True}}], 422)
        aid = self.agent.apply([op])['changes'][0]['artifact_id']
        req = urllib.request.Request(BASE + '/api/artifacts/' + aid + '/content',
                                     headers={'Authorization': 'Bearer ' + self.agent.token})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.read(), png)
            self.assertEqual(response.headers['Content-Type'], 'image/png')
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        Client(BASE).request('artifacts/' + aid + '/content', status=401)
        Client(BASE).request('artifacts/' + aid, status=401)
        self.reader.request('artifacts/' + str(uuid.uuid4()), status=404)
        incomplete = dict(op='save_artifact', object_id=oid, expected_revision=2,
                          artifact=dict(body='Only the opening page', capture_outcome='incomplete'))
        self.agent.apply([incomplete], 422)
        incomplete['artifact']['capture_reason'] = 'Remaining pages unavailable'
        self.agent.apply([incomplete])
        detail = self.reader.request('objects/' + oid)
        self.assertEqual(detail['artifacts'][0]['sha256'], hashlib.sha256(png).hexdigest())
        self.assertEqual(detail['artifacts'][1]['capture_outcome'], 'incomplete')
        resolved = self.reader.request('artifacts/' + aid)['artifact']
        self.assertEqual(resolved, detail['artifacts'][0])
        self.assertEqual(resolved['object_id'], oid)
        self.assertEqual(self.agent.request('artifacts/' + aid)['artifact'], resolved)

    def test_research_record_fields_and_exact_excerpts(self):
        source = self.admin.apply([create(kind='source', fields={'source_kind': 'paper', 'canonical_uri': 'https://example.test/paper'})])['local_refs']['new']
        aid = self.admin.apply([dict(op='save_artifact', object_id=source, expected_revision=1,
            artifact={'body': 'αβ quoted words and ending', 'kind': 'paper_text'})])['changes'][0]['artifact_id']
        fields = {'intent': 'excerpt', 'content_format': 'plain_text', 'content': 'quoted words',
                  'source_artifact_id': aid, 'source_locator': {'kind': 'text_offset', 'start': 3, 'end': 15}}
        note = self.admin.apply([create(kind='note', fields=fields)])['local_refs']['new']
        self.assertEqual(self.reader.request('objects/' + note)['object']['fields'], fields)
        self.admin.apply([create(kind='note', fields={**fields, 'source_locator': {'kind': 'text_offset', 'start': 4, 'end': 16}})], 422)
        for locator in [{'kind': 'page', 'page': 2, 'end_page': 4}, {'kind': 'timestamp', 'start_ms': 10, 'end_ms': 900}, {'kind': 'section', 'label': 'Methods'}]:
            self.admin.apply([create(kind='note', fields={**fields, 'source_locator': locator})])
        event = {'starts_at': '2021', 'starts_at_precision': 'year', 'ends_at': '2023', 'ends_at_precision': 'year'}
        eid = self.admin.apply([create(kind='event', fields=event)])['local_refs']['new']
        self.assertEqual(self.reader.request('objects/' + eid)['object']['fields'], event)
        self.admin.apply([create(kind='event', fields={**event, 'ends_at': '2020'})], 422)
        self.admin.apply([create(kind='event', fields={'starts_at': '2024-02-30', 'starts_at_precision': 'day'})], 422)
        self.admin.apply([create(kind='theme', fields={'slug': 'synthetic-theme'})])
        self.admin.apply([create(kind='theme', fields={'slug': 'synthetic-theme'})], 409)
        categories=[]
        for slug, legacy in [('researchers','person'),('institutes','organization')]:
            category=dict(id=str(uuid.uuid4()),expected_revision=0,slug=slug,label=slug.title(),definition='Synthetic '+slug,aliases=[slug+'-alias'],legacy_kind=legacy)
            self.admin.request('entity-categories',category)
            categories.append(category)
        self.reader.request('entity-categories',{**categories[0],'expected_revision':1},403)
        entity_fields=dict(entity_kind='person',category_ids=[c['id'] for c in categories],primary_category_id=categories[0]['id'],image_url='https://example.test/original.png')
        entity=self.admin.apply([create(kind='entity',fields=entity_fields)])['local_refs']['new']
        self.assertEqual(self.reader.request('objects/'+entity)['object']['fields'],entity_fields)
        self.admin.request('entity-categories',{**categories[0],'expected_revision':1,'archived':True},422)
        self.admin.request('entity-categories',{**categories[0],'id':str(uuid.uuid4()),'slug':'duplicate-alias'},422)
        self.admin.request('entity-categories',{**categories[0],'expected_revision':1,'definition':'heliographicclassification'})
        found = self.reader.request('retrieve?q=heliographicclassification')['context']['objects']
        self.assertIn(entity, [o['id'] for o in found])
        self.assertEqual(next(o for o in found if o['id']==entity)['match']['reference'], 'category:'+categories[0]['id'])
        self.admin.request('entity-categories',{**categories[0],'expected_revision':2,'definition':'Replacement classification'})
        self.assertNotIn(entity, [o['id'] for o in self.reader.request('retrieve?q=heliographicclassification')['context']['objects']])
        self.admin.request('entity-categories',{**categories[0],'expected_revision':1},409)
        self.assertTrue(self.reader.request('entity-categories')['history'])

    def test_import_legacy_tasks_provenance_and_replay(self):
        actor_id = str(uuid.uuid4())
        def record(kind, fields, oid=None):
            return dict(type='object', object=dict(id=oid or str(uuid.uuid4()), kind=kind,
                title='Synthetic historical ' + kind, description='Original supplied snapshot.', fields=fields,
                revision=7, created_by=actor_id, updated_by=actor_id,
                created_at='2020-01-02T03:04:05Z', updated_at='2021-02-03T04:05:06Z',
                archived_at=None, protected=True, provenance={'source_type': 'synthetic'},
                authorship={'created_by_type': 'centaur_agent', 'created_by_id': 'old-agent'}))
        def op(r, store='synthetic-brad'):
            return dict(op='import_record', source_store=store, record=r)
        user = record('user', {'user_kind': 'agent'}, actor_id)
        self.agent.apply([op(user)], 403)
        self.admin.apply([op(user)])
        self.assertNotIn(actor_id, [u['id'] for u in self.admin.request('users')['users']])
        self.admin.request('tokens', {'label': 'Historical user cannot authenticate', 'account_id': actor_id, 'write_kinds': ['task']}, 403)
        tasks = []
        issue = 'https://github.com/synthetic/migration/issues/89'
        for i in range(3):
            fields = dict(status='todo', priority='medium', owner_object_id=actor_id if i==2 else None,
                          due_at=None, work_kind='general', brief_markdown=None if i==1 else 'Legacy brief')
            if i: fields['github_issue_url'] = issue
            task = record('task', fields)
            task['object']['owner_mapping'] = dict(source_owner_id=actor_id if i==2 else None,
                destination_owner_id=actor_id if i==2 else self.bob_id)
            self.admin.apply([op(task, 'synthetic-enyu' if i==1 else 'synthetic-brad')])
            tasks.append(task)
        self.admin.request('tasks/by-issue?github_issue_url=' + urllib.parse.quote(issue), status=409)
        for i, task in enumerate(tasks):
            oid = task['object']['id']
            before = self.reader.request('objects/' + oid)
            obj = before['object']
            self.assertIsNone(obj['fields']['due_at'])
            self.assertEqual(obj['fields']['brief_markdown'], None if i==1 else 'Legacy brief')
            self.assertEqual(obj['fields']['owner_object_id'], actor_id if i==2 else self.bob_id)
            self.assertEqual(obj['created_by'], actor_id)
            self.assertEqual(obj['revision'], 7)
            self.assertEqual(before['audit_events'][0]['actor_id'], self.admin_id)
            self.assertEqual(obj['import_provenance']['original_fields']['owner_object_id'], actor_id if i==2 else None)
            updated = {**obj['fields'], 'priority': 'high'}
            self.agent.apply([dict(op='update_object', object_id=oid, expected_revision=7,
                title=obj['title'], description=obj['description'], fields=updated)])
            replay = self.admin.apply([op(task, 'synthetic-enyu' if i==1 else 'synthetic-brad')])
            self.assertFalse(replay['changes'][0]['imported'])
            after = self.reader.request('objects/' + oid)
            self.assertEqual(after['object']['fields'], updated)
            self.assertEqual(after['object']['revision'], 8)
        missing = self.reader.request('objects/' + tasks[1]['object']['id'])['object']
        edit = dict(op='update_object', object_id=missing['id'], expected_revision=8,
                    title=missing['title'], description=missing['description'], fields=missing['fields'])
        self.agent.apply([{**edit, 'fields': {**missing['fields'], 'status': 'doing'}}], 422)
        filled = {**missing['fields'], 'brief_markdown': 'Newly supplied brief', 'status': 'doing'}
        self.agent.apply([{**edit, 'fields': filled}])
        self.agent.apply([{**edit, 'expected_revision': 9,
                           'fields': {**filled, 'status': 'todo', 'brief_markdown': None}}], 422)
        self.agent.apply([create(kind='task', fields={**missing['fields'],
                                                     'due_at': '2027-01-01T00:00:00Z'})], 422)
        task = tasks[0]['object']; oid=task['id']
        current = self.reader.request('objects/' + oid)['object']
        with_date={**current['fields'],'due_at':'2027-01-01T00:00:00Z'}
        update=dict(op='update_object',object_id=oid,expected_revision=8,title=current['title'],description=current['description'],fields=with_date)
        self.agent.apply([update])
        self.agent.apply([{**update,'expected_revision':9,'fields':{**with_date,'due_at':None}}],422)
        self.agent.apply([create(kind='task',fields={**with_date,'due_at':None})],422)
        self.agent.apply([{**create(kind='task',fields=with_date),'import_provenance':{'legacy':True}}],422)
        unsupported=record('routine',{})
        staged=record('memory',{})
        self.admin.apply([op(staged),op(unsupported)],422)
        self.admin.request('objects/' + staged['object']['id'],status=404)

    def test_history_corrections_archive_and_long_retrieval(self):
        oid = self.memory(title='Synthetic lifecycle target')
        body = ('padding evidence. ' * 70000) + 'tailzebraquartz'
        aid = self.agent.apply([dict(op='save_artifact', object_id=oid, expected_revision=1,
            artifact=dict(body=body))])['changes'][0]['artifact_id']
        found = lambda term: [o['id'] for o in self.reader.request('retrieve?q='+term)['context']['objects']]
        self.assertIn(oid, found('tailzebraquartz'))
        correction = dict(op='correct_evidence',object_id=oid,expected_revision=2,target_type='artifact',target_id=aid,
                          reason='Synthetic correction',representation={'claim':'replacementtanager'})
        self.reader.apply([correction],403)
        self.agent.apply([correction])
        self.agent.apply([correction],409)
        self.assertNotIn(oid,found('tailzebraquartz'))
        self.assertIn(oid,found('replacementtanager'))
        corrected=self.reader.request('objects/'+oid)
        self.assertEqual(corrected['artifacts'][0]['body'],body)
        self.assertEqual(corrected['corrections'][0]['representation'],{'claim':'replacementtanager'})
        self.assertEqual(corrected['history'][-1]['before_state']['object']['revision'],2)
        neighbor=self.memory(title='Synthetic lifecycle neighbor')
        self.agent.apply([dict(op='create_connection',from_id=oid,to_id=neighbor,from_revision=3,to_revision=1,kind='related_to',explanation='Retain relationship')])
        cid=self.reader.request('objects/'+oid)['connections'][0]['id']
        self.note_agent.apply([dict(op='update_connection',connection_id=cid,expected_revision=1,from_revision=4,to_revision=2,explanation='Denied',archived=True,protected=True)],403)
        self.agent.apply([dict(op='set_lifecycle',object_id=oid,expected_revision=4,archived=True,protected=True)])
        self.assertNotIn(oid,found('replacementtanager'))
        self.assertNotIn(oid,[o['id'] for o in self.reader.request('objects')['objects']])
        self.assertIn(oid,[o['id'] for o in self.reader.request('objects?archived=true')['objects']])
        self.assertFalse(self.reader.request('objects/'+neighbor)['connections'])
        archived=self.reader.request('objects/'+oid)
        self.assertTrue(archived['object']['protected'])
        self.assertEqual(archived['artifacts'][0]['sha256'],hashlib.sha256(body.encode()).hexdigest())
        self.agent.apply([dict(op='set_lifecycle',object_id=oid,expected_revision=5,archived=False,protected=True)])
        self.assertIn(oid,found('replacementtanager'))
        self.assertEqual(self.reader.request('objects/'+oid)['connections'][0]['id'],cid)

    def test_import_rich_historical_shapes(self):
        source, aid, note, event = [str(uuid.uuid4()) for _ in range(4)]
        def obj(oid,kind,fields):
            return dict(type='object',object=dict(id=oid,kind=kind,title='Historical '+kind,description='',fields=fields,
                revision=8,created_by=None,updated_by=None,created_at='2020-01-01T00:00:00Z',updated_at='2021-01-01T00:00:00Z',
                archived_at=None,protected=False,provenance={'original_actor':'opaque-id'},authorship={'created_by_type':'system','created_by_id':'original-text-id'}))
        def op(record): return dict(op='import_record',source_store='rich-synthetic',record=record)
        body='Original α source capture.'
        artifact=dict(type='artifact',id=aid,object_id=source,created_by=self.bob_id,created_at='2020-02-01T00:00:00Z',provenance={'original_created_by':None},sha256=hashlib.sha256(body.encode()).hexdigest(),artifact=dict(body=body,capture_outcome='incomplete',capture_reason='Original incomplete capture',semantic_indexing_enabled=False))
        artifact['artifact']['media_type'] = None
        locator={'unit':'source-defined-unit','start':2,'end':9,'capture_sha256':hashlib.sha256(body.encode()).hexdigest()}
        ops=[op(obj(source,'source',{'source_kind':'article','current_artifact_id':aid})),op(artifact),op(obj(note,'note',{'intent':'excerpt','content':'Original α','source_artifact_id':aid,'source_locator':locator})),op(obj(event,'event',{'starts_at':'2020-03','starts_at_precision':'month'}))]
        self.admin.apply(ops)
        self.assertIsNone(self.reader.request('objects/'+source)['artifacts'][0]['media_type'])
        with self.reader.opener.open(self.reader.base+'/api/artifacts/'+aid+'/content') as response:
            self.assertEqual(response.read(), body.encode())
            self.assertEqual(response.headers['Content-Type'], 'text/plain; charset=utf-8')
        save = dict(op='save_artifact', object_id=source, expected_revision=8,
                    artifact=dict(body='New capture', media_type=None))
        self.admin.apply([save], 422)
        version = self.admin.apply([{**save, 'artifact': {**save['artifact'],
                                   'supersedes_artifact_id': aid}}])['changes'][0]['artifact_id']
        observed = {a['id']: a for a in self.reader.request('objects/'+source)['artifacts']}
        self.assertIsNone(observed[version]['media_type'])
        self.assertEqual(observed[aid]['body'], body)
        self.admin.apply([op(artifact)])
        self.assertEqual(len(self.reader.request('objects/'+source)['artifacts']), 2)
        html = '<p>Exact later capture α</p>\r\n'
        html_input = dict(body=html, media_type='text/html; charset=utf-8', supersedes_artifact_id=version)
        # New writes still keep media stable; privileged history preserves observed transitions.
        self.admin.apply([{**save, 'expected_revision': 9, 'artifact': html_input}], 422)
        html_record = {**artifact, 'id': str(uuid.uuid4()), 'sha256': hashlib.sha256(html.encode()).hexdigest(),
                       'artifact': html_input, 'provenance': {'original_media_type': html_input['media_type']}}
        self.admin.apply([op(html_record)])
        self.admin.apply([op(html_record)])
        observed = {a['id']: a for a in self.reader.request('objects/'+source)['artifacts']}
        self.assertEqual(len(observed), 3)
        self.assertIsNone(observed[version]['media_type'])
        self.assertEqual(observed[html_record['id']]['media_type'], html_input['media_type'])
        self.assertEqual(observed[html_record['id']]['supersedes_artifact_id'], version)
        self.assertEqual(observed[html_record['id']]['body'], html)
        for artifact_id in (aid, version, html_record['id']):
            self.assertEqual(self.reader.request('artifacts/'+artifact_id)['artifact'], observed[artifact_id])
        with self.reader.opener.open(self.reader.base+'/api/artifacts/'+html_record['id']+'/content') as response:
            self.assertEqual(response.read(), html.encode())
            self.assertEqual(response.headers['Content-Type'], 'text/plain; charset=utf-8')
        nd=self.reader.request('objects/'+note)['object']
        self.assertEqual(nd['fields']['source_locator'],locator)
        self.bob.apply([dict(op='update_object',object_id=note,expected_revision=8,title='Edited title',description='',fields=nd['fields'])])
        self.assertEqual(self.reader.request('objects/'+event)['object']['fields']['starts_at'],'2020-03')
        self.admin.apply([create(kind='note',fields=nd['fields'])],422)
        absent=str(uuid.uuid4()); uri='relative/original.pdf'
        self.admin.apply([op(dict(type='artifact',id=absent,object_id=source,created_by=self.bob_id,created_at='2020-02-01T00:00:00Z',provenance={},sha256=hashlib.sha256(uri.encode()).hexdigest(),artifact=dict(body=None,uri=uri,media_type='application/pdf',capture_outcome='unavailable',capture_reason='Original not packaged',semantic_indexing_enabled=False)))])
        self.assertIsNone(next(a for a in self.reader.request('objects/'+source)['artifacts'] if a['id']==absent)['body'])
        unavailable = self.reader.request('artifacts/'+absent)['artifact']
        self.assertEqual(unavailable['object_id'], source)
        self.assertEqual(unavailable['uri'], uri)
        self.assertIsNone(unavailable['body'])
        self.reader.request('artifacts/'+absent+'/content',status=404)
        history=dict(type='history',id=str(uuid.uuid4()),object_id=note,target_type='object',target_id=note,action='updated',revision=7,actor_id=None,occurred_at='2019-03-04T00:00:00Z',before_state={'owner':None},after_state={'supplied':'untouched'},provenance={'actor_type':'centaur_agent','actor_id':'opaque','from_revision':6,'run_id':str(uuid.uuid4()),'sequence':3,'reversible':True})
        self.admin.apply([op(history)])
        readback=next(h for h in self.reader.request('objects/'+note)['history'] if h['id']==history['id'])
        self.assertEqual(readback['before_state'],history['before_state'])
        self.assertEqual(readback['import_provenance']['original'],history['provenance'])
        self.admin.apply([op(history)])
        self.assertEqual(sum(h['id']==history['id'] for h in self.reader.request('objects/'+note)['history']),1)
        events = [{**history, 'id': str(uuid.uuid4()), 'provenance': {'sequence': i}} for i in range(105)]
        for start in range(0, len(events), 50):
            self.admin.apply([op(h) for h in events[start:start+50]])
        observed = {h['id']: h for h in self.reader.request('objects/'+note)['history']}
        for event in events:
            self.assertEqual(observed[event['id']]['import_provenance']['original'], event['provenance'])
        category_id=str(uuid.uuid4())
        category=dict(type='category',category=dict(id=category_id,expected_revision=0,slug='historic-category',label='Historic category',definition='Retained original',aliases=['Old classification'],legacy_kind='concept'),revision=4,created_by=None,updated_by=None,created_at='2018-01-01T00:00:00Z',updated_at='2019-01-01T00:00:00Z',archived_at='2020-01-01T00:00:00Z',provenance={'created_by_id':'opaque-source-actor'})
        category_history={**history,'id':str(uuid.uuid4()),'object_id':None,'target_type':'entity_category','target_id':category_id}
        self.admin.apply([op(category),op(category_history)])
        categories=self.reader.request('entity-categories')
        self.assertEqual(next(c for c in categories['categories'] if c['id']==category_id)['revision'],4)
        self.assertEqual(next(h for h in categories['history'] if h['id']==category_history['id'])['after_state'],history['after_state'])
        correction=dict(type='correction',id=str(uuid.uuid4()),object_id=source,target_type='object',target_id=source,reason='Original correction',representation={'description':'historicalcorrectedwren'},supersedes_correction_id=None,actor_id=None,object_revision=7,created_at='2020-03-01T00:00:00Z',provenance={'actor_id':'source-system','actor_type':'system'})
        self.admin.apply([op(correction)])
        self.assertEqual(self.reader.request('objects/'+source)['corrections'][0]['representation'],correction['representation'])

    def test_00_bounded_retrieval(self):
        Client(BASE).request('retrieve?q=unavailable', status=401)
        oid = self.memory(title='Unconnected retrieval sentinel')
        self.agent.apply([dict(op='append_artifact', object_id=oid,
            expected_revision=1, body='The recovery code is cobalt-otter-927.')])
        result = self.reader.request('retrieve?q=cobalt-otter-927')
        self.assertIn(oid, [o['id'] for o in result['context']['objects']])
        self.assertEqual(result['mode'], 'lexical_only')
        self.assertLessEqual(result['context_bytes'], 24000)
        self.assertIn(oid, [o['id'] for o in self.agent.request('retrieve?q=' + oid)['context']['objects']])
        self.agent.request('retrieve?q=x&limit=11', status=422)
        self.agent.request('retrieve?q=x&budget=1999', status=422)
        orientation = self.reader.request('orientation?limit=1')
        self.assertLessEqual(len(orientation['objects']), 1)
        self.assertIn('schema', orientation)
        self.reader.request('retrieval/rebuild', {}, status=403)
        for n in range(6):
            neighbor = self.memory(title=f'Adjacent retrieval sentinel {n}')
            rev = self.agent.request('objects/' + oid)['object']['revision']
            self.agent.apply([dict(op='create_connection', from_id=oid, to_id=neighbor,
                from_revision=rev, to_revision=1, kind='related_to', explanation='Explicit synthetic link.')])
        expanded = self.reader.request('retrieve?q=' + oid + '&limit=1')['context']
        self.assertEqual(len(expanded['objects']), 6)  # primary plus at most five neighbors
        self.assertEqual(len(expanded['connections']), 5)
        self.assertTrue(all(c['explanation'] == 'Explicit synthetic link.' for c in expanded['connections']))

    def test_01_auth_and_identity(self):
        health = Client(BASE).request('health')
        self.assertEqual(health['status'], 'ok')
        self.assertEqual(health['schema_version'], 9)
        self.assertEqual(health['contract_version'], 'commons/0.1')
        self.assertEqual(health['branding'], {'name': 'Commons', 'theme': 'charcoal'})
        Client(BASE).request('not-a-real-route', status=404)
        Client(BASE).request('contract', status=401)
        discovery = self.agent.request('contract')
        self.assertEqual(discovery['identity']['credential_id'], self.agent_receipt['id'])
        self.assertEqual(discovery['contract_version'], 'commons/0.1')
        self.assertEqual({op['op'] for op in discovery['operations']},
                         {'create_object', 'ensure_task', 'update_object', 'append_artifact', 'save_artifact', 'create_connection', 'update_connection', 'set_lifecycle', 'correct_evidence', 'import_record'})
        Client(BASE).request('objects', status=401)
        Client(BASE).request('objects', status=401, extra={'X-Centaur-Principal-Id': self.bob_id})
        spoofed = {'X-Amp-Authenticated': 'amp-user=yes, workspace-member=yes, collaborator=yes',
                   'X-Amp-User-ID': self.bob_id, 'X-Forwarded-For': '127.0.0.1',
                   'X-Forwarded-Proto': 'https', 'Accept': 'text/html'}
        Client(BASE).request('me', status=401, extra=spoofed)
        with urllib.request.urlopen(urllib.request.Request(BASE + '/', headers=spoofed)) as page:
            self.assertIsNone(page.headers.get('Set-Cookie'), 'normal mode must never auto-login')
        self.assertEqual(self.agent.request('me')['id'], self.bob_id)
        self.admin.request('tokens', {'label': 'csrf', 'write_kinds': []}, 403, origin='https://evil.invalid')
        self.agent.request('users', {'username': 'elevated', 'title': 'X', 'password': PASSWORD, 'role': 'admin'}, 403)
        self.reader.request('tokens', {'label': 'elevate', 'write_kinds': ['memory']}, 403)
        self.reader.apply([create()], 403)

    def test_02_task_optional_issue_all_actors_work_kinds_and_boundaries(self):
        for actor_index, client in enumerate((self.bob, self.agent)):
            for work_index, work in enumerate(('general', 'code')):
                fields = dict(status='todo', priority='high', owner_object_id=self.bob_id,
                              due_at='2027-04-03T14:25:00+10:00', work_kind=work,
                              brief_markdown='Verify synthetic onboarding.', agent_suitable=True)
                if work == 'general':
                    fields['github_issue_url'] = None
                op = create('task', 'Synthetic onboarding Task', fields)
                for bad in (None, '', 'not-valid'):
                    invalid = copy.deepcopy(op)
                    invalid['fields']['due_at'] = bad
                    client.apply([invalid], 422)
                invalid = copy.deepcopy(op)
                del invalid['fields']['due_at']
                client.apply([invalid], 422)
                for url in ('https://github.com/a/b/issues/0', 'https://github.com/a/b/issues/01',
                            'https://github.com/a/b/pull/2', 'https://github.com/a/b/issues/2/',
                            'https://github.com/a/b/issues/2?q=x', 'https://github.com/a/b/issues/2#x', '',
                            'not-valid'):
                    invalid = copy.deepcopy(op)
                    invalid['fields']['github_issue_url'] = url
                    client.apply([invalid], 422)
                result = client.apply([op])
                oid = result['local_refs']['new']
                obj = client.request('objects/' + oid)['object']
                self.assertEqual(obj['fields'], fields)
                update = dict(op='update_object', object_id=oid, expected_revision=1,
                              title=obj['title'], description=obj['description'], fields=fields)
                bad = copy.deepcopy(update)
                bad['fields']['due_at'] = None
                client.apply([bad], 422)
                issue_url = f'https://github.com/synthetic/commons/issues/{27 + actor_index * 2 + work_index}'
                linked = copy.deepcopy(update)
                linked['fields']['github_issue_url'] = issue_url
                client.apply([linked])
                linked_obj = client.request('objects/' + oid)['object']
                self.assertEqual(linked_obj['fields']['github_issue_url'], issue_url)
                cleared = copy.deepcopy(linked)
                cleared['expected_revision'] = 2
                cleared['fields']['github_issue_url'] = None
                cleared['fields']['priority'] = 'low'
                client.apply([cleared])
                current = client.request('objects/' + oid)['object']
                self.assertIsNone(current['fields']['github_issue_url'])
                self.assertEqual(current['fields']['priority'], 'low')

    def test_03_memory_direct_write_audit_revision(self):
        oid = self.memory()
        detail = self.agent.request('objects/' + oid)
        obj = detail['object']
        event = detail['audit_events'][0]
        self.assertEqual(obj['created_by'], self.bob_id)
        self.assertEqual(event['actor_id'], self.bob_id)
        self.assertEqual(event['credential_id'], self.agent_receipt['id'])
        update = dict(op='update_object', object_id=oid, expected_revision=1, title='Revised synthetic decision',
                      description='Evidence changed; external agent explicitly revised this record.', fields={})
        self.agent.apply([update])
        self.agent.apply([update], 409)
        current = self.agent.request('objects/' + oid)
        self.assertEqual(current['object']['revision'], 2)
        self.assertEqual(len(current['audit_events']), 2)
        spoof = create(fields={'actor_id': self.admin_id})
        self.agent.apply([spoof], 422)
        spoof = create()
        spoof['created_by'] = self.admin_id
        self.agent.apply([spoof], 422)

    def test_04_alternate_effect_paths_and_both_endpoints(self):
        memory = self.memory()
        note = self.memory(self.note_agent, kind='note', title='Synthetic evidence')
        artifact = dict(op='append_artifact', object_id=memory, expected_revision=1, body='Synthetic external evidence')
        self.note_agent.apply([artifact], 403)
        self.reader.apply([artifact], 403)
        for frm, to in ((note, memory), (memory, note)):
            self.note_agent.apply([dict(op='create_connection', from_id=frm, to_id=to,
                from_revision=1, to_revision=1, kind='derived_from', explanation='Synthetic support')], 403)
        self.agent.apply([artifact])
        link = dict(op='create_connection', from_id=memory, to_id=note, from_revision=2, to_revision=1,
                    kind='derived_from', explanation='Synthetic note supports this Memory')
        self.agent.apply([link])
        self.assertEqual(self.agent.request('objects/' + memory)['object']['revision'], 3)
        self.assertEqual(self.agent.request('objects/' + note)['object']['revision'], 2)
        self.assertEqual(self.agent.request('objects/' + memory)['artifacts'][0]['origin'], 'caller_supplied')
        self.note_agent.apply([{'op': 'correct_evidence', 'object_id': memory}], 422)

    def test_05_atomic_dry_run_and_receipts(self):
        title = 'Unique atomic rollback marker'
        self.agent.apply([create(title=title), create('chat')], 403)
        self.assertEqual(self.agent.request('objects?q=' + urllib.parse.quote(title))['objects'], [])
        result = self.agent.apply([create(title=title)], validate_only=True)
        self.assertTrue(result['validated_only'])
        self.agent.request('objects/' + result['local_refs']['new'], status=404)
        key = str(uuid.uuid4())
        op = create()
        first = self.agent.apply([op], key=key)
        self.assertEqual(first, self.agent.apply([op], key=key))
        self.agent.apply([create(title='different')], 409, key=key)
        other = Client(BASE, self.admin.request('tokens', {'label': 'Other principal', 'write_kinds': ['memory']})['token'])
        second = other.apply([op], key=key)
        self.assertNotEqual(first['local_refs']['new'], second['local_refs']['new'])
        self.assertEqual(other.request('objects/' + second['local_refs']['new'])['object']['created_by'], self.admin_id)
        self.assertEqual(len(self.agent.request('objects/' + first['local_refs']['new'])['audit_events']), 1)

    def test_06_concurrent_replay_and_lost_update(self):
        key = str(uuid.uuid4())
        op = create()
        def retry(_):
            return Client(BASE, self.agent_receipt['token']).apply([op], key=key)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(retry, range(4)))
        self.assertTrue(all(r == results[0] for r in results))
        oid = results[0]['local_refs']['new']
        def edit(title):
            try:
                Client(BASE, self.agent_receipt['token']).apply([dict(op='update_object', object_id=oid,
                    expected_revision=1, title=title, description='', fields={})])
                return 200
            except AssertionError as e:
                self.assertEqual(e.args[0][1], 409)
                return 409
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(edit, ['Concurrent Alpha', 'Concurrent Beta']))
        self.assertEqual(sorted(codes), [200, 409])
        self.assertEqual(len(self.agent.request('objects/' + oid)['audit_events']), 2)
        self.assertEqual(self.agent.apply([op], key=key), results[0])

    def test_07_search_scope_body_and_untrusted_text(self):
        title = 'Synthetic marmalade inventory'
        oid = self.memory(title=title)
        self.agent.apply([dict(op='append_artifact', object_id=oid, expected_revision=1,
                               body='<script>alert(1)</script> bodyonlyxylophone')])
        found = self.agent.request('objects?q=marmalade')
        self.assertIn(oid, [o['id'] for o in found['objects']])
        self.assertEqual(found['retrieval_mode'], 'lexical_metadata')
        self.assertEqual(self.agent.request('objects?q=bodyonlyxylophone')['objects'], [])

    def test_08_revocation_applies_to_replay(self):
        receipt = self.bob.request('tokens', {'label': 'Revocation check', 'write_kinds': ['memory']})
        client = Client(BASE, receipt['token'])
        key = str(uuid.uuid4())
        client.apply([create()], key=key)
        self.bob.request('tokens/' + receipt['id'] + '/revoke', {})
        client.apply([create()], 401, key=key)
        client.request('objects', status=401)

    def test_09_complete_collections_and_graph(self):
        marker = 'collectionquartz' + uuid.uuid4().hex
        ids = []
        for start in range(0, 103, 40):
            operations = []
            for i in range(start, min(start + 40, 103)):
                op = create(title=f'{marker} {i:03d}')
                op['local_ref'] = str(i)
                operations.append(op)
            result = self.agent.apply(operations)
            ids.extend(result['local_refs'][op['local_ref']] for op in operations)
        self.agent.apply([dict(op='update_object', object_id=ids[0], expected_revision=1,
            title=marker + ' edited oldest', description='', fields={})])
        query = f'objects?q={marker}&kind=memory&sort=recent'
        first = self.reader.request(query)
        second = self.reader.request(query + '&offset=100')
        self.assertEqual((first['total'], first['next_offset'], len(first['objects'])), (103, 100, 100))
        self.assertEqual((second['total'], second['next_offset'], len(second['objects'])), (103, None, 3))
        all_objects = first['objects'] + second['objects']
        self.assertEqual({o['id'] for o in all_objects}, set(ids))
        self.assertEqual([o['id'] for o in all_objects], [o['id'] for o in sorted(
            all_objects, key=lambda o: (-datetime.datetime.fromisoformat(o['created_at']).timestamp(), o['id']))])
        self.assertNotEqual(first['objects'][0]['id'], ids[0])
        self.assertEqual(self.agent.request(query.replace('sort=recent', 'sort=updated'))['objects'][0]['id'], ids[0])
        self.assertEqual(self.reader.request(query + '&offset=103')['objects'], [])
        self.assertEqual(self.reader.request(query.replace('kind=memory', 'kind=task'))['total'], 0)
        for suffix in ('&limit=0', '&limit=201', '&offset=-1', '&sort=invalid', '&kind=invalid'):
            self.reader.request('objects?q=' + marker + suffix, status=422)
        for route in ('users', 'connections', 'objects?kind=memory&sort=connected'):
            Client(BASE).request(route, status=401)
        users = self.agent.request('users')['users']
        self.assertIn(self.bob_id, [u['id'] for u in users])
        self.assertTrue(all(u['kind'] == 'user' and 'password_hash' not in u for u in users))

        note = self.memory(kind='note', title=marker + ' evidence')
        self.agent.apply([dict(op='create_connection', from_id=ids[0], to_id=note,
            from_revision=2, to_revision=1, kind='derived_from', explanation='First supporting edge')])
        self.agent.apply([dict(op='create_connection', from_id=ids[0], to_id=ids[1],
            from_revision=3, to_revision=1, kind='related_to', explanation='Second supporting edge')])
        connected = self.agent.request(query.replace('sort=recent', 'sort=connected'))
        self.assertEqual([(o['id'], o['connection_count']) for o in connected['objects'][:2]],
                         [(ids[0], 2), (ids[1], 1)])
        edges = self.reader.request(f'connections?object_id={ids[0]}&limit=1')
        more = self.reader.request(f'connections?object_id={ids[0]}&limit=1&offset=1')
        self.assertEqual((edges['total'], edges['next_offset'], more['next_offset']), (2, 1, None))
        self.assertNotEqual(edges['connections'][0]['id'], more['connections'][0]['id'])
        detail = self.reader.request('objects/' + ids[0])
        self.assertEqual(detail['object']['connection_count'], 2)
        for edge in detail['connections']:
            self.assertEqual(edge['from_id'], edge['from_object']['id'])
            self.assertEqual(edge['to_id'], edge['to_object']['id'])
            self.assertTrue(edge['explanation'])

        # Historical participation is separate from active accounts and active graph traversal.
        historical = []
        for archived in (None, '2020-04-01T00:00:00Z'):
            historical.append(dict(id=str(uuid.uuid4()), kind='user', title='Preserved participant',
                description='', fields={'user_kind': 'agent' if archived else 'human'}, revision=4,
                created_by=None, updated_by=None, created_at='2020-01-01T00:00:00Z',
                updated_at='2020-02-01T00:00:00Z', archived_at=archived, protected=True,
                provenance={'role': 'Original supplied identity'}, authorship={}))
        def imported(record):
            return dict(op='import_record', source_store='synthetic-participants', record=record)
        self.admin.apply([imported(dict(type='object', object=u)) for u in historical])
        h0, h1 = [u['id'] for u in historical]
        links = []
        for from_id, to_id, kind, archived in (
            (ids[0], h0, 'involves', None), (h1, ids[1], 'involves', None),
            (ids[0], h1, 'related_to', None), (ids[0], note, 'involves', None),
            (ids[0], h1, 'involves', '2020-04-01T00:00:00Z'), (ids[2], h0, 'involves', None),
        ):
            links.append(dict(type='connection', id=str(uuid.uuid4()), from_id=from_id, to_id=to_id,
                kind=kind, explanation='Original participant role α', revision=3, created_by=None,
                created_at='2020-02-01T00:00:00Z', updated_at='2020-03-01T00:00:00Z',
                archived_at=archived, protected=True, provenance={'role': 'observer'}))
        self.admin.apply([imported(c) for c in links])
        route = f'participants?object_ids={ids[0]},{ids[1]},{ids[0]}'
        Client(BASE).request(route, status=401)
        first = self.reader.request(route + '&limit=1')
        second = self.agent.request(route + '&limit=1&offset=1')
        self.assertEqual((first['total'], first['next_offset'], second['next_offset']), (2, 1, None))
        rows = first['participants'] + second['participants']
        self.assertEqual([(r['object_id'], r['direction'], r['user']['id']) for r in rows],
                         sorted([(ids[0], 'outgoing', h0), (ids[1], 'incoming', h1)]))
        for row in rows:
            user = self.reader.request('objects/' + row['user']['id'])['object']
            user.pop('connection_count')
            self.assertEqual(row['user'], user)
            connection = self.reader.request('connections/' + row['connection']['id'])['connection']
            connection.pop('from_object'); connection.pop('to_object')
            self.assertEqual(row['connection'], connection)
        self.assertFalse({h0, h1} & {u['id'] for u in self.reader.request('users')['users']})
        self.assertEqual(self.reader.request(route + '&offset=2')['participants'], [])
        self.assertEqual(self.reader.request('participants?object_ids=' + str(uuid.uuid4()))['total'], 0)
        # Archiving the requested record must not erase its historical participants either.
        current = self.admin.request('objects/' + ids[1])['object']
        self.admin.apply([dict(op='set_lifecycle', object_id=ids[1], expected_revision=current['revision'],
                               archived=True, protected=False)])
        self.assertEqual(self.reader.request(route)['total'], 2)
        for suffix in ('', '?object_ids=bad', '?object_ids=' + ','.join([ids[0]] * 201),
                       f'?object_ids={ids[0]}&limit=201', f'?object_ids={ids[0]}&offset=-1'):
            self.reader.request('participants' + suffix, status=422)

    def test_10_explicit_protected_demo_sessions_do_not_bypass_api_auth(self):
        for setting in ('COMMONS_PROTECTED_DEMO_USER', 'COMMONS_LOCAL_USER'):
            with self.subTest(setting=setting):
                self.check_browser_entry(setting)

    def check_browser_entry(self, setting):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        demo_env = dict(env, PORT=str(port), COMMONS_ORIGIN=base, **{setting: self.bob_id})
        with tempfile.TemporaryFile() as log:
            demo = subprocess.Popen(['target/debug/commons', 'serve'], env=demo_env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    try:
                        Client(base).request('health')
                        break
                    except (OSError, urllib.error.URLError):
                        time.sleep(.1)
                else:
                    self.fail('demo did not become ready')
                browser = Client(base)
                # Even forged proxy identity/HTML headers on an API request grant nothing.
                browser.request('me', status=401, extra={'Accept': 'text/html',
                    'X-Amp-Authenticated': 'amp-user=yes, collaborator=yes', 'X-Amp-User-ID': self.admin_id})
                if setting == 'COMMONS_LOCAL_USER':
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        browser.opener.open(urllib.request.Request(base+'/', headers={'Accept':'text/html', 'Host':'evil.invalid'}))
                    self.assertEqual(denied.exception.code, 403)
                with browser.opener.open(urllib.request.Request(base + '/objects', headers={
                    'Accept': 'text/html', 'If-Modified-Since': 'Wed, 01 Jan 2099 00:00:00 GMT'})) as page:
                    self.assertEqual(page.status, 200)
                    self.assertEqual(page.headers['Cache-Control'], 'private, no-store')
                    cookie = page.headers['Set-Cookie']
                    self.assertIn('HttpOnly', cookie)
                    self.assertIn('SameSite=Strict', cookie)
                    self.assertNotIn(cookie.split(';')[0].split('=', 1)[1].encode(), page.read())
                self.assertEqual(browser.request('me')['id'], self.bob_id)
                self.assertEqual(browser.request('me')['role'], 'member')
                browser.apply([dict(op='import_record', source_store='denied', record={})], 403)
                # Document reload preserves this session; API traffic never mints one.
                with browser.opener.open(urllib.request.Request(base + '/', headers={'Accept': 'text/html'})) as page:
                    self.assertIsNone(page.headers.get('Set-Cookie'))
                oid = browser.apply([create(title='Synthetic protected-demo edit')])['local_refs']['new']
                obj = browser.request('objects/' + oid)['object']
                update = dict(op='update_object', object_id=oid, expected_revision=1,
                              title=obj['title'], description='Edited through the demo session.', fields=obj['fields'])
                browser.request('apply', {'contract_version': 'commons/0.1', 'idempotency_key': str(uuid.uuid4()),
                    'operations': [update]}, 403, origin='https://evil.invalid')
                browser.apply([update])
                agent = Client(base, self.agent_receipt['token'])
                self.assertEqual(agent.request('objects/' + oid)['object']['revision'], 2)
                self.assertEqual(agent.request('objects/' + oid)['object']['description'], update['description'])
                browser.apply([update], 409)
                Client(base).request('objects', status=401)
                Client(base, 'invalid').request('objects', status=401)
                browser.request('me', status=401, extra={'Authorization': 'Bearer invalid'})
                Client(base, self.note_agent.token).apply([create()], 403)
                # An explicit reader login is never replaced by the demo member.
                reader = Client(base)
                reader.request('login', {'username': 'reader', 'password': PASSWORD})
                with reader.opener.open(urllib.request.Request(base + '/', headers={'Accept': 'text/html'})) as page:
                    self.assertIsNone(page.headers.get('Set-Cookie'))
                self.assertEqual(reader.request('me')['role'], 'reader')
                reader.apply([create()], 403)
                # The same demo cookie is invalid on the normal-mode server.
                browser.base = BASE
                browser.request('me', status=401)
                browser.base = base
                browser.request('logout', {})
                browser.request('me', status=401)
                with browser.opener.open(urllib.request.Request(base + '/', headers={'Accept': 'text/html'})) as page:
                    self.assertIsNotNone(page.headers.get('Set-Cookie'))
                self.assertEqual(browser.request('me')['id'], self.bob_id)
            finally:
                demo.terminate()
                demo.wait(timeout=10)
        for invalid_id in (self.admin_id, str(uuid.uuid4())):
            rejected = subprocess.run(['target/debug/commons', 'serve'],
                env={**demo_env, setting: invalid_id}, capture_output=True, timeout=10)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(b'existing active member', rejected.stderr)
        if setting == 'COMMONS_LOCAL_USER':
            for config in ({'COMMONS_ORIGIN':'https://public.invalid'}, {'COMMONS_PROTECTED_DEMO_USER':self.bob_id}):
                rejected = subprocess.run(['target/debug/commons', 'serve'],
                    env={**demo_env, **config}, capture_output=True, timeout=10)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn(b'HTTP loopback origin', rejected.stderr)
            for key, value in [('COMMONS_THEME', 'unsupported'),
                               ('COMMONS_INSTALLATION_NAME', '   '),
                               ('COMMONS_INSTALLATION_NAME', 'x' * 65),
                               ('COMMONS_INSTALLATION_NAME', 'one\ntwo')]:
                rejected = subprocess.run(['target/debug/commons', 'serve'],
                    env={**demo_env, key: value}, capture_output=True, timeout=10)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn(key.encode(), rejected.stderr)

    def test_11_issue_task_pairing_across_callers_and_recovery(self):
        fields = dict(status='todo', priority='medium', owner_object_id=self.bob_id,
                      due_at='2026-10-16T23:59:59+11:00', work_kind='code',
                      github_issue_url='https://github.com/synthetic/commons/issues/411',
                      brief_markdown='Implement the acceptance in the linked Issue.')
        op = dict(op='ensure_task', local_ref='task', title='Synthetic paired work',
                  description='The Issue owns acceptance.', fields=fields)
        key = str(uuid.uuid4())
        # An Issue may already exist when Task creation fails; retry only the Task.
        bad = copy.deepcopy(op)
        bad['fields']['due_at'] = ''
        self.agent.apply([bad], 422, key=key)
        missing_issue = copy.deepcopy(op)
        del missing_issue['fields']['github_issue_url']
        self.agent.apply([missing_issue], 422)
        lookup = 'tasks/by-issue?github_issue_url=' + urllib.parse.quote(fields['github_issue_url'], safe='')
        self.agent.request(lookup, status=404)
        self.reader.apply([op], 403)
        self.note_agent.apply([op], 403)
        other_token = self.bob.request('tokens', {'label': 'Independent pairing caller', 'write_kinds': ['task']})['token']
        def ensure(token):
            return Client(BASE, token).apply([op], key=key)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(ensure, [self.agent_receipt['token'], other_token]))
        oid = results[0]['local_refs']['task']
        self.assertEqual(results[1]['local_refs']['task'], oid)
        self.assertEqual(sum(r['changes'][0]['created'] for r in results), 1)
        self.assertEqual(self.agent.apply([op], key=key), results[0])
        obj = self.agent.request(lookup)['object']
        self.assertEqual(obj['id'], oid)
        revised_fields = {**fields, 'status': 'review', 'priority': 'high', 'owner_object_id': self.admin_id}
        self.agent.apply([dict(op='update_object', object_id=oid, expected_revision=1,
            title='Reviewed work', description='Preserve this', fields=revised_fields)])
        repeat = copy.deepcopy(op)
        repeat['fields']['github_issue_url'] = fields['github_issue_url'].replace('synthetic/commons', 'SYNTHETIC/Commons')
        self.assertEqual(self.agent.apply([repeat])['local_refs']['task'], oid)
        current = self.agent.request('objects/' + oid)
        self.assertEqual(current['object']['fields'], revised_fields)
        self.assertEqual(current['object']['title'], 'Reviewed work')
        self.assertEqual(current['object']['revision'], 2)
        self.assertEqual(len(current['audit_events']), 2)
        self.reader.apply([op], 403)
        self.agent.apply([create('task', fields=fields)], 409)
        another = {**fields, 'github_issue_url': fields['github_issue_url'] + '2'}
        second = self.agent.apply([create('task', fields=another)])['local_refs']['new']
        self.agent.apply([dict(op='update_object', object_id=second, expected_revision=1,
            title='Cannot steal Issue', description='', fields=fields)], 409)
        self.assertEqual(self.agent.request('objects/' + second)['object']['revision'], 1)
        self.agent.request('tasks/by-issue?github_issue_url=https://github.com/synthetic/commons/pull/411', status=422)
        Client(BASE).request(lookup, status=401)

    def test_12_agent_user_credentials_and_avatar(self):
        puck = self.admin.request('users', {'username': 'puck', 'title': 'Puck Synthetic',
            'user_kind': 'agent', 'role': 'member'})['id']
        self.assertEqual(self.admin.request('objects/' + puck)['object']['fields']['user_kind'], 'agent')
        Client(BASE).request('login', {'username': 'puck', 'password': PASSWORD}, 401)
        self.admin.request('users', {'username': 'bad-agent', 'title': 'Bad',
            'user_kind': 'agent', 'role': 'admin'}, 422)
        self.bob.request('tokens', {'account_id': puck, 'label': 'Impersonation', 'write_kinds': ['task']}, 403)
        self.admin.request('tokens', {'account_id': self.bob_id, 'label': 'Human impersonation', 'write_kinds': []}, 403)
        credential = self.admin.request('tokens', {'account_id': puck, 'label': 'Puck task writer', 'write_kinds': ['task']})
        agent = Client(BASE, credential['token'])
        self.assertEqual(agent.request('me')['id'], puck)
        agent.apply([create()], 403)
        fields = dict(status='review', priority='high', owner_object_id=puck,
                      due_at='2026-10-16T23:59:59+11:00', work_kind='code',
                      github_issue_url='https://github.com/synthetic/commons/issues/412', brief_markdown='Await Brad review.')
        oid = agent.apply([dict(op='ensure_task', local_ref='puck', title='Puck-owned work', description='', fields=fields)])['local_refs']['puck']
        detail = agent.request('objects/' + oid)
        self.assertEqual(detail['object']['fields']['owner_object_id'], puck)
        self.assertEqual(detail['audit_events'][0]['actor_id'], puck)
        self.assertEqual(detail['audit_events'][0]['credential_id'], credential['id'])
        # Assignment to a human does not change the authenticated writer.
        agent.apply([dict(op='update_object', object_id=oid, expected_revision=1,
            title=detail['object']['title'], description='', fields={**fields, 'owner_object_id': self.bob_id})])
        self.assertEqual(agent.request('objects/' + oid)['audit_events'][-1]['actor_id'], puck)
        import base64
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        path = f'users/{puck}/avatar?expected_revision=1&source=Synthetic+fixture'
        def upload(client, data=png, status=200, media='image/png', route=path):
            headers = {'Content-Type': media, 'Origin': BASE}
            if client.token:
                headers['Authorization'] = 'Bearer ' + client.token
            req = urllib.request.Request(BASE + '/api/' + route, data=data, headers=headers)
            try:
                response = client.opener.open(req)
            except urllib.error.HTTPError as error:
                response = error
            self.assertEqual(response.code, status)
            response.close()
        upload(self.bob, status=403)
        upload(agent, status=403)
        upload(self.admin, b'<svg onload="alert(1)"/>', 422, 'image/svg+xml')
        upload(self.admin)
        upload(self.admin, status=409)
        user = agent.request('objects/' + puck)['object']
        self.assertEqual(user['fields']['avatar_source'], 'Synthetic fixture')
        self.assertEqual(user['revision'], 2)
        asset = BASE + user['fields']['avatar_asset_url']
        with self.bob.opener.open(asset) as response:
            self.assertEqual(response.headers['Content-Type'], 'image/png')
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(response.read(), png)
        Client(BASE).request(f'users/{puck}/avatar', status=401)
        self.assertTrue(any(t['id'] == credential['id'] and t['account_id'] == puck for t in self.admin.request('tokens')))
        self.bob.request('tokens/' + credential['id'] + '/revoke', {}, 404)
        self.admin.request('tokens/' + credential['id'] + '/revoke', {})
        agent.request('me', status=401)


if __name__ == '__main__':
    parsed = urllib.parse.urlsplit(os.environ['DATABASE_URL'])
    if parsed.hostname != '127.0.0.1' or parsed.port != 55432 or parsed.path != '/commons':
        raise SystemExit('Refusing: use scripts/dev-env local disposable cluster only')
    dbname = 'commons_test_' + uuid.uuid4().hex
    env = dict(os.environ, PGPASSWORD=parsed.password or '')
    pg = ['-h', '127.0.0.1', '-p', '55432', '-U', 'commons']
    subprocess.run(['createdb', *pg, dbname], env=env, check=True)
    env['DATABASE_URL'] = urllib.parse.urlunsplit(parsed._replace(path='/' + dbname))
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    BASE = f'http://127.0.0.1:{port}'
    PASSWORD = uuid.uuid4().hex
    # Amp PUBLIC_URL includes a trailing slash; browser Origin never does.
    env.update(PORT=str(port), COMMONS_ORIGIN=BASE + '/', COMMONS_ADMIN_USER='admin',
               COMMONS_ADMIN_NAME='Alice Synthetic', COMMONS_ADMIN_PASSWORD=PASSWORD)
    process = None
    try:
        uninitialized = subprocess.run(['target/debug/commons', 'serve'], env=env, capture_output=True, timeout=10)
        assert uninitialized.returncode != 0 and b'database schema unavailable' in uninitialized.stderr
        subprocess.run(['target/debug/commons', 'migrate'], env=env, check=True)
        with tempfile.TemporaryDirectory(prefix='commons-secret-files-') as secret_dir:
            file_env = dict(env)
            for setting in ('DATABASE_URL', 'COMMONS_ADMIN_PASSWORD'):
                path = os.path.join(secret_dir, setting.lower())
                with open(path, 'w') as f:
                    f.write(file_env.pop(setting) + '\n')
                os.chmod(path, 0o600)
                file_env[setting + '_FILE'] = path
            ambiguous = subprocess.run(['target/debug/commons', 'bootstrap'], env={**file_env, 'DATABASE_URL': 'must-not-appear-in-output'}, capture_output=True)
            assert ambiguous.returncode != 0 and b'set only DATABASE_URL or DATABASE_URL_FILE' in ambiguous.stderr
            assert b'must-not-appear-in-output' not in ambiguous.stderr
            subprocess.run(['target/debug/commons', 'bootstrap'], env=file_env, check=True)
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(['target/debug/commons'], env=env, stdout=log, stderr=log)
            for _ in range(100):
                try:
                    Client(BASE).request('health')
                    break
                except (OSError, urllib.error.URLError):
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read().decode())
                    time.sleep(.1)
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(Foundation)
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            # Restart same binary and read persisted identity/record through existing credential.
            process.terminate(); process.wait(timeout=10)
            process = subprocess.Popen(['target/debug/commons'], env=env, stdout=log, stderr=log)
            for _ in range(100):
                try:
                    assert Foundation.agent.request('objects?kind=task')['objects']
                    assert Foundation.agent.request('objects?kind=memory')['objects']
                    print('PASS: API process restart preserves records and scoped credential')
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(.1)
            else:
                raise AssertionError('restart readiness failed')
            if not result.wasSuccessful():
                raise SystemExit(1)
    finally:
        if process and process.poll() is None:
            process.terminate(); process.wait(timeout=10)
        subprocess.run(['dropdb', *pg, dbname], env=env, check=True)
