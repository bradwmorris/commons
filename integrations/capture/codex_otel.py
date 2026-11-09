#!/usr/bin/env python3
"""Opt-in loopback OTLP/JSON bridge. Persist only independently routed business turns.

The existing transcript scanner/state is read-only here. Unclassified spans wait
in bounded volatile memory for a native run_turn parent; they never enter a file.
Approved batches use a separate existing capture outbox and authenticated API.
"""
import argparse
import collections
from contextlib import closing, contextmanager
import datetime as dt
import hmac
import fcntl
import stat
import http.server
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

import auto_capture as auto
import commons_capture as outbox

MAX_REQUEST = 8 * 1024 * 1024
MAX_MEMORY = 32 * 1024 * 1024
TTL = 120
KIND = 'opentelemetry'


def attributes(span):
    # Do not use thread.id: Codex also uses that key for OS thread numbers.
    result = {}
    for a in span.get('attributes', []):
        if isinstance(a, dict) and isinstance(a.get('value'), dict):
            result[a.get('key')] = a['value'].get('stringValue')
    return result


def native_id(value, size):
    return isinstance(value, str) and bool(re.fullmatch('[0-9a-fA-F]{%d}' % size, value)) and int(value, 16) != 0


def uuid_values(span, key):
    # A span can carry both the numeric OS thread.id and the chat UUID. Only
    # canonical UUID strings are correlation candidates; retain all duplicates
    # so two different chat UUIDs cannot silently overwrite each other.
    return {a['value']['stringValue'] for a in span.get('attributes', [])
            if a.get('key') == key and isinstance(a.get('value'), dict)
            and isinstance(a['value'].get('stringValue'), str)
            and re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', a['value']['stringValue'])}


def root_context(span):
    if span['name'] not in ('run_turn', 'session_task.turn'): return None
    key = 'conversation.id' if span['name'] == 'run_turn' else 'thread.id'
    threads, turns = uuid_values(span, key), uuid_values(span, 'turn.id')
    if len(threads) != 1 or len(turns) != 1: return None
    thread, turn = next(iter(threads)), next(iter(turns))
    if any(a.get('key') in ('conversation.id', 'turn.id')
           and a.get('value', {}).get('stringValue') != (thread if a['key'] == 'conversation.id' else turn)
           for a in span.get('attributes', [])): return None
    if uuid_values(span, 'thread.id') - {thread}: return None
    return thread, turn


def descendants(entries, root):
    selected = {root['span']['spanId'].lower()}
    while True:
        next_ids = {sid for sid,e in entries.items() if e['span'].get('parentSpanId','').lower() in selected}
        if next_ids <= selected: return selected
        selected |= next_ids


def flatten(payload):
    result = []
    for resource in payload['resourceSpans']:
        for scope in resource.get('scopeSpans', []):
            for span in scope.get('spans', []):
                if not native_id(span.get('traceId'), 32) or not native_id(span.get('spanId'), 16):
                    raise ValueError('invalid span identity')
                parent = span.get('parentSpanId')
                if parent and (not native_id(parent, 16) or parent.lower() == span['spanId'].lower()):
                    raise ValueError('invalid parent identity')
                start, end = int(span['startTimeUnixNano']), int(span['endTimeUnixNano'])
                if not 0 < start <= end < 2**64 or not isinstance(span.get('name'), str):
                    raise ValueError('invalid span timing/name')
                entry = {'resource': resource.get('resource', {}), 'scope': scope.get('scope', {}), 'span': span}
                if 'schemaUrl' in resource: entry['resourceSchemaUrl'] = resource['schemaUrl']
                if 'schemaUrl' in scope: entry['scopeSchemaUrl'] = scope['schemaUrl']
                result.append(entry)
    if len(result) > 5000:
        raise ValueError('too many spans')
    return result


def request(origin, token, path):
    opener = outbox.build_opener(outbox.ProxyHandler({}), outbox.NoRedirect())
    req = outbox.Request(origin + '/api/' + path, headers={'Authorization': 'Bearer ' + token})
    with opener.open(req, timeout=10) as response:
        body = response.read(16 * 1024 * 1024 + 1)
        if len(body) > 16 * 1024 * 1024: raise ValueError('response too large')
        return json.loads(body)


class RouteGate:
    def __init__(self, capture_state):
        self.state = Path(capture_state).expanduser()

    @contextmanager
    def delivery(self):
        # Share the scanner/router's existing lock for the whole checked send.
        # A completed disable/conflicting route cannot race a later POST.
        fd=os.open(self.state / 'auto.lock', os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('unsafe capture lock')
            fcntl.flock(fd, fcntl.LOCK_SH)
            yield
        finally: os.close(fd)

    def resolve(self, thread, turn, started):
        # No schema creation, locks, queue mutation or runtime backup/copy.
        with closing(sqlite3.connect((self.state / 'delivery.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            config, cutoff, enabled = auto.settings(db)
            source = auto.source_for(config, 'codex', thread)
            key = outbox.source_key(source)
            row = db.execute('SELECT a.stopped,a.error,s.enabled,s.deleted FROM auto_threads a JOIN sources s ON s.id=a.source WHERE a.source=?', (key,)).fetchone()
            route = db.execute('SELECT domain FROM auto_routes WHERE source=? AND turn=?', (key, turn)).fetchone()
            if not enabled or not row or row['stopped'] or not row['enabled'] or row['deleted']:
                return None
            if row['error'] and not row['error'].startswith('outbox full;'):
                return None
            if not route or route['domain'] != 'business' or started < cutoff or not auto.eligible(db, started):
                return None
            saved = db.execute('SELECT chat_id FROM batches WHERE source=? AND chat_id IS NOT NULL LIMIT 1', (key,)).fetchone()
            if not saved: return None  # Transcript capture establishes the association first.
            origin = db.execute('SELECT origin FROM destination').fetchone()[0]
            # Archived/deleted source rollouts leave active sessions. No historical fallback.
            home = Path(config['codex_home']).expanduser().resolve()
            paths = list((home / 'sessions').glob('**/*' + thread + '*.jsonl'))
            if len(paths) != 1: return None
            path = auto.codex_path(config, {'path': str(paths[0])})
            turns = auto.codex_turns(auto.codex_rows(path), source, cutoff)
            match = next((t for t in turns if t['id'] == turn), None)
            if not match or not auto.eligible(db, match['started']): return None
            token = outbox.token_from(config['token_file'])
            detail = request(origin, token, 'threads/' + saved['chat_id'] + '?limit=1')
            capture = detail.get('thread', detail.get('chat', {}))
            if any(capture.get(k) != source[k] for k in ('provider','namespace','thread_id')):
                return None
            if capture.get('deleted_at'): return None
            return {'source': source, 'chat_id': saved['chat_id'], 'coverage': capture['coverage'],
                    'origin': origin, 'token': token, 'title': detail['object']['title'],
                    'installation': config['domain_label']}


def iso(nanos):
    return dt.datetime.fromtimestamp(int(nanos) / 1e9, dt.timezone.utc).isoformat()


def matches_readback(saved, sent):
    """Compare stored OTLP with the original, allowing JSON double roundoff."""
    if saved == sent:
        return True
    if isinstance(saved, dict) and isinstance(sent, dict) and saved.keys() == sent.keys():
        for key, value in sent.items():
            stored = saved[key]
            # The API's JSON parser can round an OTLP double to the adjacent
            # IEEE 754 value. Integer fields and time/identity strings stay exact.
            if (key == 'doubleValue' and type(value) is float and type(stored) is float
                    and math.isfinite(value) and math.isfinite(stored)
                    and math.nextafter(value, stored) == stored):
                continue
            if not matches_readback(stored, value):
                return False
        return True
    if isinstance(saved, list) and isinstance(sent, list) and len(saved) == len(sent):
        return all(matches_readback(stored, value) for stored, value in zip(saved, sent))
    return False


class Bridge:
    def __init__(self, state, gate, now=time.monotonic):
        self.state, self.gate, self.now = Path(state), gate, now
        self.pending = collections.OrderedDict()
        self.lock = threading.RLock()
        self.counters = collections.Counter()
        self.last_error = None

    def ingest(self, payload):
        entries = flatten(payload)
        with self.lock:
            for entry in entries:
                s = entry['span']; tid = s['traceId'].lower(); sid = s['spanId'].lower()
                # Fixed counters only: never expose names, IDs or attribute values
                # from unclassified spans through receiver diagnostics.
                self.counters['spans_received'] += 1
                if s['name'] in ('run_turn', 'session_task.turn'):
                    prefix = 'run_turn' if s['name'] == 'run_turn' else 'session_task_turn'
                    self.counters[prefix + '_received'] += 1
                    a = attributes(s)
                    for key, counter in (('conversation.id', prefix + '_conversation_id'),
                                         ('turn.id', prefix + '_turn_id')):
                        if a.get(key): self.counters[counter] += 1
                    if a.get('conversation.id') and a.get('turn.id'):
                        self.counters['correlated_' + prefix + '_received'] += 1
                    if any(item.get('key') == 'thread.id'
                           and isinstance(item.get('value', {}).get('stringValue'), str)
                           and re.fullmatch('[0-9a-f-]{36}', item['value']['stringValue'])
                           for item in s.get('attributes', [])):
                        self.counters[prefix + '_uuid_thread_id'] += 1
                group = self.pending.setdefault(tid, {'at': self.now(), 'entries': {}})
                prior = group['entries'].get(sid)
                if prior and prior != entry:
                    self.counters['conflicting_spans'] += 1
                    # Never silently replace an immutable native span.
                    group['conflict'] = True
                else: group['entries'][sid] = entry
                group['at'] = self.now(); self.pending.move_to_end(tid)
            self.expire()
        return len(entries)

    def expire(self):
        total = sum(len(outbox.canonical(g['entries']).encode()) for g in self.pending.values())
        while self.pending:
            tid, group = next(iter(self.pending.items()))
            if total <= MAX_MEMORY and self.now() - group['at'] < TTL: break
            total -= len(outbox.canonical(group['entries']).encode())
            self.counters['volatile_spans_expired'] += len(group['entries'])
            del self.pending[tid]

    def pump(self):
        with self.lock:
            self.expire()
            snapshot = [(tid, {**g, 'entries': dict(g['entries'])}) for tid,g in self.pending.items()]
        with outbox.database(self.state) as db:
            # Durable approved batches survive restart/volatile-buffer expiry. Every
            # delivery is gated again; unclassified sources cannot unlock this queue.
            checked_sources=set()
            for batch in db.execute("SELECT source,payload FROM batches WHERE state IN ('queued','failed') AND payload IS NOT NULL ORDER BY ordinal").fetchall():
                if batch['source'] in checked_sources: continue
                checked_sources.add(batch['source'])
                envelope=json.loads(batch['payload']); run=envelope['runs'][0]
                with self.gate.delivery():
                    gate=self.gate.resolve(envelope['source']['thread_id'], run['input']['turn_id'], auto.timestamp(run['started_at']))
                    if gate:
                        result=outbox.flush(db,gate['token'],source_keys={outbox.source_key(gate['source'])},limit=1)
                        self.counters['batches_delivered'] += result['delivered']
            for tid, group in snapshot:
                if group.get('conflict'): continue
                entries = group['entries']
                roots = [e for e in entries.values() if root_context(e['span'])]
                # Both names can be correlated in one version. Accept only a
                # unique outer root with proven parentage and identical context.
                if len(roots) > 1 and len({root_context(e['span']) for e in roots}) == 1:
                    root_ids = {e['span']['spanId'].lower() for e in roots}
                    roots = [e for e in roots if root_ids <= descendants(entries, e)]
                if len(roots) != 1: continue
                root = roots[0]; thread, turn = root_context(root['span'])
                with self.gate.delivery():
                    gate = self.gate.resolve(thread, turn, int(root['span']['startTimeUnixNano']) / 1e9)
                    if not gate:
                        self.counters['not_authorized_yet'] += 1
                        continue
                    selected = descendants(entries, root)
                    chosen = [entries[sid] for sid in sorted(selected)]
                    # Conflicting explicit thread/turn context fails closed, including descendants.
                    if any((attributes(e['span']).get('conversation.id') not in (None,thread)
                            or attributes(e['span']).get('turn.id') not in (None,turn)
                            or bool(uuid_values(e['span'], 'thread.id') - {thread})) for e in chosen):
                        group['conflict'] = True; self.counters['context_conflicts'] += 1; continue
                    outbox.initialize(db, gate['origin'], gate['installation'])
                    key = outbox.source_key(gate['source'])
                    if not db.execute('SELECT 1 FROM sources WHERE id=?',(key,)).fetchone():
                        outbox.set_enabled(db, gate['source'], True, 'native spans for routed business turns only')
                    # Resolve queued revisions before preparing another append.
                    if db.execute("SELECT 1 FROM batches WHERE source=? AND state IN ('queued','failed')",(key,)).fetchone():
                        continue
                    rid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'commons:otel:' + outbox.canonical(gate['source']) + ':' + tid))
                    try:
                        prior = request(gate['origin'], gate['token'], 'traces/' + rid)['trace']
                    except outbox.HTTPError as exc:
                        if exc.code != 404: raise
                        exc.close()
                        prior = None
                    old = {e['span']['spanId'].lower():e for e in prior['trace']} if prior else {}
                    cleaned = []
                    for entry in chosen:
                        # Preserve identities/timing; existing credential redaction applies before disk.
                        text, _ = auto.sanitize(entry, (gate['token'],))
                        entry = json.loads(text); sid = entry['span']['spanId'].lower()
                        if sid in old:
                            if not matches_readback(old[sid], entry):
                                raise ValueError('saved native span changed')
                        else: cleaned.append(entry)
                    if not cleaned: continue
                    # Capture API bounds each append; native IDs give stable append keys.
                    chunk=[]
                    for entry in cleaned:
                        if len(outbox.canonical(chunk+[entry]).encode()) > 900000: break
                        chunk.append(entry)
                    if not chunk: raise ValueError('single span exceeds capture limit')
                    missing = sum(bool(e['span'].get('parentSpanId')) and e['span']['parentSpanId'].lower() not in selected for e in chosen)
                    run = {'id':rid,'expected_revision':prior['revision'] if prior else None,'source_run_id':tid,
                           'kind':KIND,'status':'ended','input':{'format':'otlp-json','thread_id':thread,'turn_id':turn},
                           'trace':chunk,'result':{},'review':{'status':'partial','native_spans':True,
                           'boundary':'Native completed turn root and available descendants; startup and unrelated traces excluded.',
                           'missing_parents':missing,'gaps':['Volatile pre-correlation buffer is bounded; restart, expiry or exporter loss can omit spans.',
                           'Ended is not a success verdict. Transcript and tool bodies are in the linked Thread.']},
                           'started_at':iso(root['span']['startTimeUnixNano']),'completed_at':iso(root['span']['endTimeUnixNano'])}
                    envelope = {'contract_version':outbox.CONTRACT,'source':gate['source'],'batch_id':'otel:'+auto.digest(run),
                                'chat_id':gate['chat_id'],'title':gate['title'],'history':False,'coverage':gate['coverage'],
                                'items':[],'attachments':[],'runs':[run]}
                    outbox.enqueue(db,envelope)
                    result = outbox.flush(db,gate['token'],source_keys={key})
                    self.counters['batches_delivered'] += result['delivered']
            self.last_error = None

    def status(self):
        with self.lock:
            roots = collections.Counter()
            for group in self.pending.values():
                count = sum(bool(root_context(e['span'])) for e in group['entries'].values())
                roots['none' if count == 0 else 'one' if count == 1 else 'multiple'] += 1
            queue={}
            path=self.state/'delivery.sqlite3'
            if path.exists():
                with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
                    queue=dict(db.execute('SELECT state,count(*) FROM batches GROUP BY state'))
            return {'buffered_traces':len(self.pending),'buffered_root_counts':dict(roots),
                    'counters':dict(self.counters),'queue':queue,'error':self.last_error}


def serve(bridge, port, token):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # Request bodies, paths and credentials never logged.
        def respond(self, code, value):
            body=outbox.canonical(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_POST(self):
            if self.path != '/v1/traces': return self.respond(404,{})
            if not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+token): return self.respond(401,{})
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json' or self.headers.get('Content-Encoding'):
                return self.respond(415,{})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size <= 0 or size > MAX_REQUEST: return self.respond(413,{})
                self.connection.settimeout(10)
                bridge.ingest(json.loads(self.rfile.read(size)))
                self.respond(200,{})
            except (ValueError,TypeError,KeyError,OverflowError): self.respond(400,{})
        def do_GET(self):
            if not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+token): return self.respond(401,{})
            self.respond(200,bridge.status())
    server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    def worker():
        while True:
            try: bridge.pump()
            except (ValueError,OSError,KeyError,TypeError,sqlite3.Error): bridge.last_error='delivery paused; inspect private configuration or reconcile denied/conflicting evidence'
            time.sleep(5)
    threading.Thread(target=worker,daemon=True).start()
    server.serve_forever()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture-state',required=True);p.add_argument('--state',required=True)
    p.add_argument('--token-file',required=True);p.add_argument('--port',type=int,default=18418)
    args=p.parse_args()
    # Validate private state/token before opening a loopback listener.
    with outbox.database(args.state): pass
    serve(Bridge(args.state,RouteGate(args.capture_state)),args.port,outbox.token_from(args.token_file))

if __name__=='__main__': main()
