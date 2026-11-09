#!/usr/bin/env python3
"""Opt-in host reconciliation of routed Codex and Amp turns. No model calls."""
import argparse
import bisect
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import sqlite3
import subprocess
import time
import uuid

import commons_capture as outbox
import commons_tool_links

VERSION = 1
ROUTE_TOOL = 'commons_capture_route'
MAX_SOURCE = 64 * 1024 * 1024
MAX_BODY = 1024 * 1024
DOMAINS = ('business', 'personal', 'mixed')
BASE_GAPS = ['Hidden reasoning and internal instructions are excluded.',
             'Attachment originals and audio are unavailable; only stored visible text is captured.',
             'Source exports may already omit, summarize or truncate tool output; this is not a full-fidelity claim.',
             'Voice-only realtime timeline transcripts are not supported; only text persisted as ordinary messages is included.']


def digest(value):
    return hashlib.sha256(outbox.canonical(value).encode()).hexdigest()


def timestamp(value):
    if isinstance(value, (int, float)):
        return float(value) / (1000 if value > 10**11 else 1)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except ValueError:
            pass
    raise ValueError('missing or invalid source timestamp; capture stopped')


def iso(value):
    return dt.datetime.fromtimestamp(timestamp(value), dt.timezone.utc).isoformat()


def setup(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS auto_settings (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), config TEXT NOT NULL,
        activated REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS auto_windows (start REAL NOT NULL, end REAL);
      CREATE TABLE IF NOT EXISTS auto_threads (
        source TEXT PRIMARY KEY, provider TEXT NOT NULL, thread TEXT NOT NULL,
        stopped INTEGER NOT NULL DEFAULT 0, error TEXT);
      CREATE TABLE IF NOT EXISTS auto_routes (
        source TEXT NOT NULL, turn TEXT NOT NULL, domain TEXT NOT NULL,
        PRIMARY KEY(source,turn));
    ''')


def settings(db):
    row = db.execute('SELECT * FROM auto_settings').fetchone()
    if not row:
        raise ValueError('automatic capture has not been initialized')
    return json.loads(row['config']), row['activated'], bool(row['enabled'])


def source_for(config, provider, thread):
    return {'provider': provider, 'namespace': config['namespace'], 'thread_id': thread}


def configure(db, config, now=None):
    required = {'namespace', 'codex_home', 'codex', 'amp', 'token_file', 'domain_label'}
    if not required <= set(config) or set(config) - required - {'speaker_ids', 'commons_object_links'}:
        raise ValueError('invalid automatic capture configuration keys')
    if not all(isinstance(config[k], str) and config[k].strip() for k in required):
        raise ValueError('configuration values must be nonempty strings')
    links = config.get('commons_object_links', {})
    if not isinstance(links, dict) or (links and (set(links) != {'server', 'installation'}
            or not all(isinstance(v, str) and 0 < len(v) <= 100 for v in links.values()))):
        raise ValueError('Object links require a fixed MCP server and installation')
    mappings = config.get('speaker_ids', {})
    if not isinstance(mappings, dict) or set(mappings) - {'codex', 'amp'}:
        raise ValueError('invalid speaker providers')
    for roles in mappings.values():
        if not isinstance(roles, dict) or set(roles) - {'human', 'agent'}:
            raise ValueError('only explicit human/agent speaker mappings are supported')
        for value in roles.values():
            if not isinstance(value, str) or str(uuid.UUID(value)) != value:
                raise ValueError('speaker mappings require canonical User UUIDs')
    if len(config['domain_label']) > 100:
        raise ValueError('domain label too long')
    outbox.source_key(source_for(config, 'codex', 'probe'))
    if db.execute('SELECT 1 FROM auto_settings').fetchone():
        raise ValueError('activation is immutable; use enable/disable, never reset history')
    with db:
        db.execute('INSERT INTO auto_settings VALUES(1,?,?,1)',
                   (outbox.canonical(config), now if now is not None else time.time()))
        db.execute('INSERT INTO auto_windows VALUES(?,NULL)', (now if now is not None else time.time(),))


def eligible(db, started):
    return bool(db.execute('SELECT 1 FROM auto_windows WHERE start<=? AND (end IS NULL OR end>?)',
                           (started, started)).fetchone())


def set_active(db, enabled, now=None):
    _, _, current = settings(db)
    if current == enabled:
        return
    when = now if now is not None else time.time()
    with db:
        if enabled:
            db.execute('INSERT INTO auto_windows VALUES(?,NULL)', (when,))
        else:
            db.execute('UPDATE auto_windows SET end=? WHERE end IS NULL', (when,))
        db.execute('UPDATE auto_settings SET enabled=?', (int(enabled),))


def register(db, source):
    key = outbox.source_key(source)
    with db:
        db.execute('INSERT OR IGNORE INTO auto_threads(source,provider,thread) VALUES(?,?,?)',
                   (key, source['provider'], source['thread_id']))
    return key


def stop(db, key, reason):
    with db:
        db.execute('UPDATE auto_threads SET stopped=1,error=? WHERE source=?', (reason, key))
        db.execute('UPDATE sources SET enabled=0 WHERE id=?', (key,))


def route(db, source, turn, domain):
    if domain not in DOMAINS or not isinstance(turn, str) or not turn:
        raise ValueError('invalid turn routing decision')
    key = register(db, source)
    if db.execute('SELECT stopped FROM auto_threads WHERE source=?', (key,)).fetchone()[0]:
        raise ValueError('stopped source cannot be routed; reconcile explicitly')
    old = db.execute('SELECT domain FROM auto_routes WHERE source=? AND turn=?', (key, turn)).fetchone()
    if old and old['domain'] != 'business' and domain != 'business':
        # Both decisions exclude the whole turn. Preserve the original receipt
        # without stopping unrelated future turns or changing capture scope.
        return {'associated': True, 'domain': old['domain'], 'turn': turn}
    if old and old['domain'] != domain:
        # A later personal/mixed decision must fence pending business delivery,
        # even if the agent ignores the error and the scheduler runs next.
        stop(db, key, 'conflicting turn route; reconcile before further capture')
        raise ValueError('turn route is immutable; capture stopped for reconciliation')
    with db:
        db.execute('INSERT OR IGNORE INTO auto_routes VALUES(?,?,?)', (key, turn, domain))
    return {'associated': True, 'domain': domain, 'turn': turn}


def sanitize(value, secrets=()):
    """Known credential forms, not a guarantee for arbitrary prose secrets."""
    def clean(v, depth=0):
        if depth > 30:
            return '[Nested content unavailable: depth limit]'
        if isinstance(v, dict):
            if v.get('hidden') is True or v.get('type') in ('thinking', 'reasoning', 'redacted_thinking'):
                return '[Hidden content omitted]'
            return {k: ('[redacted]' if re.search(r'(?i)(?:token|password|secret|api_key|apikey|authorization|encrypted_content)$', k)
                        else clean(part, depth + 1)) for k, part in v.items()
                    if k not in ('internal_chat_message_metadata_passthrough', 'system_prompt', 'developer_instructions')}
        if isinstance(v, list):
            return [clean(part, depth + 1) for part in v]
        if isinstance(v, str) and v.lstrip().startswith(('{', '[')):
            try:
                decoded = json.loads(v)
                cleaned = clean(decoded, depth + 1)
                if decoded != cleaned:
                    return outbox.canonical(cleaned)
            except (ValueError, RecursionError):
                pass
        return v

    text = value if isinstance(value, str) else outbox.canonical(value)
    original = text
    cleaned = clean(text)
    if isinstance(cleaned, str):
        text = cleaned
    for secret in secrets:
        if len(secret) >= 8:
            text = text.replace(secret, '[credential redacted]')
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----',
                  '[private key redacted]', text)
    text = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{16,}', r'\1[redacted]', text)
    text = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|tskey-[A-Za-z0-9_-]{16,})\b',
                  '[credential redacted]', text)
    text = re.sub(r'''(?i)((?:["']?)(?<![\w-])(?:[\w-]{0,80}(?:token|password|secret|api_key|apikey|authorization))["']?\s*[:=]\s*)(["'])(.*?)(\2)''',
                  r'\1"[redacted]"', text)
    text = re.sub(r'(?im)^(\w*(?:TOKEN|PASSWORD|SECRET|API_KEY)\w*=).+$', r'\1[redacted]', text)
    return text, text != original


def item(source, sid, turn, position, kind, role, body, when=None, tool=None, call=None, status=None):
    return {'id': str(uuid.uuid5(uuid.NAMESPACE_URL, outbox.canonical(source) + '/' + sid)),
            'source_item_id': sid, 'turn_id': turn, 'position': position, 'kind': kind,
            'role': role, 'speaker_id': None, 'source_created_at': iso(when) if when else None,
            'body': body if isinstance(body, str) else outbox.canonical(body),
            'tool_name': tool, 'tool_call_id': call, 'status': status, 'artifact_ids': []}


def visible_text(block):
    if block.get('hidden'):
        return None
    if block.get('type') in ('text', 'input_text', 'output_text'):
        return block.get('text', '')
    if block.get('type') in ('image', 'input_image', 'image_url', 'audio', 'input_audio', 'file', 'local_image'):
        return '[Attachment/audio original unavailable in this capture]'
    return None


def codex_rows(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_SOURCE:
        raise ValueError('unsupported or oversized Codex source')
    # Incomplete final writes are retried, never interpreted as complete events.
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    rows = []
    for line in lines:
        if not line.endswith(b'\n'):
            break
        try:
            rows.append(json.loads(line))
        except (ValueError, UnicodeError):
            raise ValueError('invalid Codex source; cursor unchanged') from None
    return rows


def codex_turns(rows, source, cutoff):
    turns, current, calls = {}, None, {}
    observed_models = []
    raw_calls = {r.get('payload', {}).get('call_id') for r in rows
                 if r.get('type') == 'response_item' and r.get('payload', {}).get('type') in ('function_call', 'custom_tool_call')}
    for index, row in enumerate(rows):
        p = row.get('payload', {})
        ty = p.get('type')
        if row.get('type') == 'turn_context' and isinstance(p.get('model'), str):
            observed_models.append((index, {'id':p['model'], 'provider':p.get('model_provider')}))
        if row.get('type') == 'event_msg' and ty == 'task_started':
            current = str(p['turn_id'])
            turns.setdefault(current, {'id': current, 'started': timestamp(row['timestamp']), 'items': [], 'gaps': []})
        if row.get('type') == 'turn_context' and current is None:
            current = str(p['turn_id'])
            turns.setdefault(current, {'id': current, 'started': timestamp(row['timestamp']), 'items': [], 'gaps': []})
        if not current or turns[current]['started'] < cutoff :
            continue
        t = turns[current]
        if row.get('type') == 'event_msg' and ty == 'item_completed':
            event = p.get('item', {})
            call_id = event.get('id')
            tool = event.get('type')
            if call_id and call_id not in raw_calls and tool in ('CommandExecution', 'McpToolCall', 'WebSearch', 'FileChange', 'DynamicToolCall'):
                args = {k: event[k] for k in ('command', 'cwd', 'server', 'tool', 'arguments', 'action', 'query', 'changes', 'input') if k in event}
                result = {k: event[k] for k in ('stdout', 'stderr', 'aggregated_output', 'exit_code', 'result', 'error', 'status', 'output') if k in event}
                t['items'].append(item(source, 'event-' + call_id + '-call', current, index * 1000, 'tool_call', 'agent', args,
                                       p.get('started_at_ms') or row.get('timestamp'), tool, call_id))
                t['items'].append(item(source, 'event-' + call_id + '-result', current, index * 1000 + 1, 'tool_result', 'tool', result or '[Result unavailable]',
                                       p.get('completed_at_ms') or row.get('timestamp'), tool, call_id, event.get('status')))
            continue
        if row.get('type') != 'response_item':
            continue
        when = row.get('timestamp')
        sid = 'row-' + str(index)
        if ty == 'message' and p.get('role') in ('user', 'assistant'):
            if p.get('channel') == 'analysis':
                continue
            for bindex, block in enumerate(p.get('content', [])):
                kinds = p.get('internal_chat_message_metadata_passthrough', {}).get('content_item_kinds', [])
                if bindex < len(kinds) and kinds[bindex] not in ('unknown', 'text', 'user_message', 'user.text', 'user.image', 'user.audio'):
                    continue
                body = visible_text(block)
                if body is not None:
                    # System/developer context is not a human turn. Some clients store
                    # injected context as user-role blocks; reject known wrappers.
                    if body.lstrip().startswith(('<environment_context>', '<permissions instructions>', '# AGENTS.md instructions', '<system-reminder>')):
                        continue
                    t['items'].append(item(source, f'{sid}-{bindex}', current, index * 1000 + bindex,
                                           'message', 'human' if p['role'] == 'user' else 'agent', body, when))
        elif ty in ('function_call', 'custom_tool_call'):
            call = p.get('call_id') or p.get('id')
            name = p.get('name', 'unknown')
            calls[call] = (name, current)
            body = p.get('arguments') if ty == 'function_call' else p.get('input')
            t['items'].append(item(source, sid, current, index * 1000, 'tool_call', 'agent',
                                   body if body is not None else '[Arguments unavailable]', when, name, call))
        elif ty in ('function_call_output', 'custom_tool_call_output'):
            call = p.get('call_id')
            if not call and p.get('namespace') == 'codex_app' and p.get('name') == 'create_thread':
                # Desktop-created tasks carry their visible delegated brief as a
                # result without a local call. Keep it honestly, without inventing
                # a human author or a nonexistent matching call.
                t['items'].append(item(source, sid, current, index * 1000, 'tool_result', 'tool',
                                       p.get('output', '[Delegated brief unavailable]'), when,
                                       'codex_app.create_thread', None))
                t['gaps'].append('The desktop delegated task brief has no local matching tool call.')
                continue
            if not call or call not in calls or calls[call][1] != current:
                t['gaps'].append('A tool result has no matching call in the available turn; omitted.')
                continue
            t['items'].append(item(source, sid, current, index * 1000, 'tool_result', 'tool',
                                   p.get('output', '[Result unavailable]'), when, calls[call][0], call))
        elif ty not in ('reasoning', 'message'):
            t['gaps'].append('An unsupported source item was omitted.')
    for turn in turns.values():
        for entry in turn['items']:
            if entry['role'] == 'agent':
                model = next((m for pos,m in reversed(observed_models) if pos <= entry['position']//1000), None)
                if model is not None: entry['model'] = model
    return list(turns.values())


def amp_route_domain(name, args, run):
    if run.get('status') != 'done':
        return None
    if name == ROUTE_TOOL:
        return (args or {}).get('domain')
    # Current Amp exposes plugin tools through code_exec. Accept only this exact
    # single-purpose call shape, never an arbitrary string occurrence in code or
    # output. Do not execute source code to discover its intent.
    if name != 'code_exec' or not isinstance(args, dict):
        return None
    code = args.get('code', '')
    pattern = r"\s*import\s*\{\s*commons_capture_route\s*\}\s*from\s*['\"]plugins['\"]\s*;?\s*text\s*\(\s*await\s+commons_capture_route\s*\(\s*\{\s*domain\s*:\s*['\"](business|personal|mixed)['\"]\s*\}\s*\)\s*\)\s*;?\s*"
    match = re.fullmatch(pattern, code)
    result = run.get('result')
    if match and 'commons.capture-route/1' in outbox.canonical(result):
        return match.group(1)
    return None


def amp_turns(payload, source, cutoff):
    if payload.get('id') != source['thread_id'] or not isinstance(payload.get('messages'), list):
        raise ValueError('unsupported Amp export identity or messages')
    cutoff = max(cutoff, timestamp(payload['created']))
    turns, current, calls = [], None, {}
    for index, message in enumerate(payload['messages']):
        blocks = message.get('content')
        if not isinstance(blocks, list):
            raise ValueError('unsupported Amp content shape')
        # Tool results also use role=user; only a visible user input starts a turn.
        human = message.get('role') == 'user' and any(visible_text(b) is not None for b in blocks)
        mid = message.get('protocolMessageID') or str(message.get('messageId', ''))
        if not mid:
            raise ValueError('Amp message identity unavailable')
        if human:
            current = {'id': mid, 'started': timestamp(message['createdAt']), 'items': [], 'gaps': [], 'route': None}
            turns.append(current)
        if current is None or current['started'] < cutoff:
            continue
        for bi, b in enumerate(blocks):
            if b.get('hidden'):
                continue
            ty = b.get('type')
            body = visible_text(b)
            sid = f'{mid}-{bi}'
            pos = index * 1000 + bi
            when = message.get('createdAt')
            if body is not None and message.get('role') in ('assistant', 'user'):
                # Do not freeze a streaming block whose contents may still grow.
                if message.get('role') == 'assistant' and message.get('state', {}).get('type') != 'complete':
                    return turns
                current['items'].append(item(source, sid, current['id'], pos, 'message',
                                             'human' if human else 'agent', body, when))
            elif ty == 'tool_use':
                if not b.get('complete'):
                    return turns
                call, name = b['id'], b['name']
                calls[call] = (name, b.get('input'), current)
                current['items'].append(item(source, sid, current['id'], pos, 'tool_call', 'agent', b.get('input', {}), when, name, call))
            elif ty == 'tool_result':
                run = b.get('run', {})
                if run.get('status') not in ('done', 'error', 'cancelled'):
                    return turns
                call = b.get('toolUseID')
                if call not in calls:
                    current['gaps'].append('A tool result has no matching available call; omitted.')
                    continue
                name, args, originating = calls[call]
                if originating is not current:
                    current['gaps'].append('Cross-turn tool result omitted to preserve routing boundary.')
                    continue
                domain = amp_route_domain(name, args, run)
                if domain is not None:
                    # Only a real assistant tool invocation plus successful result,
                    # never matching text inside prompts, files or other tool output.
                    if domain not in DOMAINS:
                        raise ValueError('invalid Amp routing domain')
                    if current['route'] and current['route'] != domain:
                        raise ValueError('conflicting Amp turn routes')
                    current['route'] = domain
                current['items'].append(item(source, sid, current['id'], pos, 'tool_result', 'tool',
                                             run.get('result', run.get('error', '[Result unavailable]')), when, name, call, run['status']))
            elif ty not in ('thinking', 'redacted_thinking'):
                current['gaps'].append('An unsupported Amp content block was omitted.')
    return turns


def reconcile(db, source, turns, secrets=(), *, max_batches=None):
    if max_batches is not None and (not isinstance(max_batches, int) or max_batches < 0):
        raise ValueError('nonnegative batch allowance required')
    config, cutoff, enabled = settings(db)
    if not enabled:
        return 0
    key = register(db, source)
    if db.execute('SELECT stopped FROM auto_threads WHERE source=?', (key,)).fetchone()[0]:
        return 0
    existing = db.execute('SELECT * FROM sources WHERE id=?', (key,)).fetchone()
    if existing and (existing['deleted'] or not existing['enabled']):
        return 0
    accepted, gaps = [], list(BASE_GAPS)
    for turn in turns:
        if turn['started'] < cutoff or not eligible(db, turn['started']):
            continue
        if turn.get('route'):
            route(db, source, turn['id'], turn['route'])
        decision = db.execute('SELECT domain FROM auto_routes WHERE source=? AND turn=?', (key, turn['id'])).fetchone()
        if not decision or decision['domain'] != 'business':
            continue
        accepted.extend(i for i in turn['items'] if i['source_created_at'] and eligible(db, timestamp(i['source_created_at'])))
        gaps.extend(turn['gaps'])
    if not accepted:
        return 0
    if not existing:
        outbox.set_enabled(db, source, True, 'per-turn business routing from activation')
        cursor = {'seen': {}, 'coverage': None}
    else:
        cursor = json.loads(existing['cursor']) if existing['cursor'] else {'seen': {}, 'coverage': None}
    link_config = config.get('commons_object_links') if source['provider'] == 'codex' else None
    paired_calls = {}
    if link_config:
        for entry in accepted:
            if entry['kind'] == 'tool_call' and entry['tool_name'] == 'McpToolCall' and entry['tool_call_id']:
                pair = (entry['turn_id'], entry['tool_call_id'])
                paired_calls[pair] = entry if pair not in paired_calls else None
    pending, seen_now = [], set()
    for original in accepted:
        entry = dict(original)
        if entry['kind'] == 'message':
            entry['speaker_id'] = config.get('speaker_ids', {}).get(source['provider'], {}).get(entry['role'])
        sid = entry['source_item_id']
        seen_now.add(sid)
        if len(entry['body'].encode()) > MAX_BODY:
            entry['body'] = '[Oversized item unavailable: exceeds the 1 MiB capture limit]'
            gaps.append('An oversized visible item was replaced by an explicit unavailable marker.')
        else:
            entry['body'], redacted = sanitize(entry['body'], secrets)
            if redacted:
                gaps.append('Known credential material was redacted before local queueing.')
        h = digest(entry)
        if sid in cursor['seen'] and cursor['seen'][sid] != h and 'model' in entry:
            # New optional telemetry must not rewrite previously acknowledged items.
            without_model = {k:v for k,v in entry.items() if k != 'model'}
            if digest(without_model) == cursor['seen'][sid]:
                entry, h = without_model, digest(without_model)
        if sid in cursor['seen']:
            if cursor['seen'][sid] != h:
                raise ValueError('acknowledged source content changed; reconcile before continuing')
        else:
            pending.append((entry, h))
    if set(cursor['seen']) - seen_now:
        raise ValueError('previously captured source items disappeared; reconcile before continuing')
    if max_batches == 0:
        # Still validate every supplied item and prior hash when another source
        # has reserved the next available capacity. Do not advance this cursor.
        return 0
    coverage = {'status': 'partial', 'messages': 'Available visible text in agent-routed business turns only.',
                'tools': 'Stored call/result records in source order; nested tools may be represented in wrapper output.',
                'attachments': 'Original binaries/audio unavailable; placeholders retained where supplied.',
                'history': 'From activation only. Personal, mixed and unclassified turns excluded.',
                'gaps': sorted(set(gaps))[:50]}
    count, batches_queued = 0, 0
    # Small batches bound outage memory while allowing large source histories.
    while (pending or cursor['coverage'] != digest(coverage)) and (max_batches is None or batches_queued < max_batches):
        chunk, size = [], 0
        for candidate in pending[:50]:
            item_size = len(outbox.canonical(candidate[0]).encode())
            if chunk and size + item_size > 4 * 1024 * 1024:
                break
            chunk.append(candidate)
            size += item_size
        pending = pending[len(chunk):]
        batch_items = [entry for entry, _ in chunk]
        runs = []
        if link_config:
            for entry in batch_items:
                if entry['kind'] == 'tool_result' and entry['tool_name'] == 'McpToolCall':
                    call = paired_calls.get((entry['turn_id'], entry['tool_call_id']))
                    run = commons_tool_links.trace_for(call, entry, link_config)
                    if run:
                        runs.append(run)
        envelope = {'contract_version': outbox.CONTRACT, 'source': source,
                    'batch_id': digest([batch_items, coverage, runs] if runs else [batch_items, coverage]),
                    'title': config['domain_label'] + ' — ' + source['provider'] + ' conversation',
                    'history': False, 'coverage': coverage, 'items': batch_items, 'attachments': [], 'runs': runs,
                    **({'on_behalf_of':config['on_behalf_of']} if config.get('on_behalf_of') else {})}
        next_cursor = {'seen': {**cursor['seen'], **{x['source_item_id']: h for x, h in chunk}}, 'coverage': digest(coverage)}
        outbox.enqueue(db, envelope, outbox.canonical(next_cursor))
        cursor = next_cursor
        count += len(chunk)
        batches_queued += 1
    with db:
        db.execute('UPDATE auto_threads SET error=NULL WHERE source=?', (key,))
    return count


class Codex:
    """Read-only app-server client. Never resume or mutate a thread."""
    def __init__(self, binary, home):
        self.process = subprocess.Popen([binary, 'app-server', '--stdio'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        env={**os.environ, 'CODEX_HOME': str(home)}, bufsize=0)
        self.buffer, self.serial = b'', 0
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            self.call('initialize', {'clientInfo': {'name': 'commons_capture', 'version': '1'},
                                     'capabilities': {'experimentalApi': True}})
        except Exception:
            self.close()
            raise

    def call(self, method, params):
        if method not in ('initialize', 'thread/list', 'thread/read'):
            raise ValueError('unsupported read-only Codex method')
        self.serial += 1
        self.process.stdin.write((outbox.canonical({'id': self.serial, 'method': method, 'params': params}) + '\n').encode())
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if b'\n' not in self.buffer:
                if not self.selector.select(max(0, deadline - time.monotonic())):
                    break
                data = os.read(self.process.stdout.fileno(), 65536)
                if not data:
                    break
                self.buffer += data
                if len(self.buffer) > MAX_SOURCE:
                    break
                continue
            line, self.buffer = self.buffer.split(b'\n', 1)
            response = json.loads(line)
            if response.get('id') == self.serial:
                if 'error' in response:
                    raise ValueError('Codex read-only API failed; no fallback or resume')
                return response['result']
        raise ValueError('Codex read-only API timed out or exceeded limit')

    def active(self):
        result, cursor, visited = {}, None, set()
        while True:
            page = self.call('thread/list', {'limit': 100, 'cursor': cursor, 'archived': False,
                                             'sourceKinds': ['cli', 'vscode', 'exec', 'appServer', 'unknown'], 'useStateDbOnly': True})
            for entry in page['data']:
                result[entry['id']] = entry
            cursor = page.get('nextCursor')
            if not cursor:
                return result
            if cursor in visited:
                raise ValueError('Codex pagination repeated a cursor')
            visited.add(cursor)

    def close(self):
        self.selector.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()


def amp_command(binary, *args):
    # A bounded temporary pipe reader avoids unbounded subprocess capture memory.
    p = subprocess.Popen([binary, 'threads', *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    selector = selectors.DefaultSelector()
    selector.register(p.stdout, selectors.EVENT_READ)
    data = bytearray()
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if not selector.select(max(0, deadline - time.monotonic())):
                break
            part = os.read(p.stdout.fileno(), 65536)
            if not part:
                if p.wait(timeout=3) != 0:
                    raise ValueError('Amp command failed; capture paused')
                return json.loads(data)
            data.extend(part)
            if len(data) > MAX_SOURCE:
                raise ValueError('Amp source exceeds reconciliation limit')
        raise ValueError('Amp export timed out')
    finally:
        selector.close()
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdout.close()


def amp_active(binary):
    result, offset, signatures = {}, 0, set()
    while True:
        page = amp_command(binary, 'list', '--json', '--limit', '100', '--offset', str(offset))
        if not isinstance(page, list):
            raise ValueError('unsupported Amp listing shape')
        signature = digest([x['id'] for x in page])
        if page and signature in signatures:
            raise ValueError('Amp pagination repeated a page')
        signatures.add(signature)
        for entry in page:
            result[entry['id']] = entry
        if len(page) < 100:
            return result
        offset += len(page)


def codex_path(config, metadata):
    path = Path(metadata.get('path') or '')
    root = Path(config['codex_home']).expanduser().resolve() / 'sessions'
    if not path.is_absolute() or not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ValueError('Codex session is unavailable or outside active sessions')
    return path


def check_destination(db, source, token):
    key = outbox.source_key(source)
    saved = db.execute('SELECT chat_id FROM batches WHERE source=? AND chat_id IS NOT NULL LIMIT 1', (key,)).fetchone()
    if not saved:
        return
    target = db.execute('SELECT origin FROM destination').fetchone()[0]
    opener = outbox.build_opener(outbox.ProxyHandler({}), outbox.NoRedirect())
    request = outbox.Request(target + '/api/objects/' + saved['chat_id'] + '?view=compact&limit=1',
                            headers={'Authorization': 'Bearer ' + token})
    try:
        with opener.open(request, timeout=10) as response:
            raw = response.read(MAX_SOURCE + 1)
            if len(raw) > MAX_SOURCE:
                raise ValueError('destination lifecycle response exceeds limit')
            obj = json.loads(raw)['object']
        if obj.get('fields', {}).get('deleted'):
            with db:
                outbox.purge_local(db, key)
            stop(db, key, 'destination deleted')
        elif obj.get('archived_at'):
            stop(db, key, 'destination archived; automatic resume forbidden')
    except outbox.HTTPError as exc:
        code = exc.code
        exc.close()
        if code == 410:
            with db:
                outbox.purge_local(db, key)
            stop(db, key, 'destination deleted')
        else:
            raise ValueError('destination lifecycle unavailable; delivery paused') from None


def scan(db, providers=None):
    providers = ('codex', 'amp') if providers is None else tuple(providers)
    if not providers or any(provider not in ('codex', 'amp') for provider in providers):
        raise ValueError('at least one supported capture provider required')
    config, cutoff, enabled = settings(db)
    if not enabled:
        return {'enabled': False, 'queued_items': 0}
    token = outbox.token_from(config['token_file'])
    secrets = (token,)
    queued, errors, backpressure, checked = 0, [], [], set()
    admission_open = True
    # Complete each listing before deciding a known thread was archived/deleted.
    for provider in dict.fromkeys(providers):
        client = None
        try:
            if provider == 'codex':
                client = Codex(config['codex'], Path(config['codex_home']).expanduser())
                active = client.active()
            else:
                active = amp_active(config['amp'])
            known = db.execute('SELECT * FROM auto_threads WHERE provider=? AND stopped=0', (provider,)).fetchall()
            for row in known:
                if row['thread'] not in active:
                    stop(db, row['source'], 'source archived or deleted; automatic resume forbidden')
            # Codex discovers new capture associations via the agent route command.
            candidates = [r['thread'] for r in known if r['thread'] in active] if provider == 'codex' else list(active)
            # Receipt ordinals survive acknowledgement/restart. Resume the ring
            # after the last source admitted, including when it is now absent.
            ordered = sorted((outbox.source_key(source_for(config, provider, tid)), tid) for tid in candidates)
            previous = db.execute('SELECT b.source FROM batches b JOIN auto_threads a ON a.source=b.source WHERE a.provider=? ORDER BY b.ordinal DESC LIMIT 1', (provider,)).fetchone()
            pivot = bisect.bisect([key for key, _ in ordered], previous['source']) if previous else 0
            candidates = [tid for _, tid in ordered[pivot:] + ordered[:pivot]]
            for tid in candidates:
                source = source_for(config, provider, tid)
                key = outbox.source_key(source)
                row = db.execute('SELECT stopped FROM auto_threads WHERE source=?', (key,)).fetchone()
                if row and row['stopped']:
                    continue
                try:
                    check_destination(db, source, token)
                    if provider == 'codex':
                        metadata = client.call('thread/read', {'threadId': tid, 'includeTurns': False})['thread']
                        turns = codex_turns(codex_rows(codex_path(config, metadata)), source, cutoff)
                    else:
                        # Listing timestamps avoid exporting dormant pre-activation threads.
                        if timestamp(active[tid]['updated']) < cutoff:
                            continue
                        payload = amp_command(config['amp'], 'export', tid)
                        if payload.get('archived'):
                            if row:
                                stop(db, key, 'source archived; automatic resume forbidden')
                            continue
                        turns = amp_turns(payload, source, cutoff)
                        if not row and not any(t.get('route') for t in turns):
                            continue
                    queued += reconcile(db, source, turns, secrets, max_batches=1 if admission_open else 0)
                    checked.add(key)
                except outbox.OutboxFull:
                    # Discovery, destination lifecycle and source-content checks
                    # passed before enqueue reached capacity. Keep the cursor
                    # retryable and finish checking every other source before
                    # allowing this source's existing queue to drain. Sources
                    # whose checks fail stay excluded from delivery.
                    with db:
                        db.execute('UPDATE auto_threads SET error=? WHERE source=?',
                                   ('outbox full; pending source content will retry after checked delivery', key))
                    backpressure.append(key)
                    checked.add(key)
                    # Reserve the next freed capacity for this source. Other
                    # sources must still pass their full lifecycle/content checks
                    # but cannot repeatedly consume space before it can fit.
                    admission_open = False
                except (ValueError, KeyError, TypeError, OSError):
                    register(db, source)
                    with db:
                        db.execute('UPDATE auto_threads SET error=? WHERE source=?', ('source reconciliation failed; inspect compatibility/routing', key))
                    errors.append(key)
        except (ValueError, KeyError, TypeError, OSError):
            errors.append(provider + ' discovery failed; delivery paused')
            # Do not flush queued sources until their lifecycle has been checked.
            return {'queued_items': queued, 'errors': errors, 'backpressure': backpressure, 'delivery_paused': True}
        finally:
            if client:
                client.close()
    # Source failures must not block unrelated checked sources. A source that
    # failed lifecycle/content checks cannot leak through the shared queue.
    result = outbox.flush(db, token, source_keys=checked)
    return {'queued_items': queued, 'errors': errors, 'backpressure': backpressure, **result}


@contextlib.contextmanager
def locked_state(directory):
    # database() validates ownership/mode first. Serialize routing, scan, disable.
    with outbox.database(directory) as db:
        lock = Path(directory).expanduser() / 'auto.lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            setup(db)
            yield db
        finally:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('activate')
    init.add_argument('--config', required=True)
    init.add_argument('--acknowledge-shared-readership', action='store_true', required=True)
    r = commands.add_parser('route')
    r.add_argument('domain', choices=DOMAINS)
    r.add_argument('--thread', default=os.environ.get('CODEX_THREAD_ID'))
    scanner = commands.add_parser('scan')
    scanner.add_argument('--provider', action='append', choices=('codex', 'amp'),
                         help='Reconcile and deliver only this provider (repeatable; default: both).')
    commands.add_parser('status')
    commands.add_parser('disable')
    commands.add_parser('enable')
    args = parser.parse_args()
    try:
        with locked_state(args.state) as db:
            if args.command == 'activate':
                configure(db, json.loads(Path(args.config).read_text()))
                result = {'activated': True}
            elif args.command == 'route':
                config, cutoff, enabled = settings(db)
                if not enabled or not args.thread:
                    raise ValueError('capture disabled or current thread unavailable')
                client = Codex(config['codex'], Path(config['codex_home']).expanduser())
                try:
                    if args.thread not in client.active():
                        raise ValueError('current Codex thread is not active')
                    meta = client.call('thread/read', {'threadId': args.thread, 'includeTurns': False})['thread']
                    source = source_for(config, 'codex', args.thread)
                    turns = codex_turns(codex_rows(codex_path(config, meta)), source, cutoff)
                    if not turns or turns[-1]['started'] < cutoff:
                        raise ValueError('current turn predates activation; next turn can be routed')
                    result = route(db, source, turns[-1]['id'], args.domain)
                finally:
                    client.close()
            elif args.command in ('disable', 'enable'):
                settings(db)
                set_active(db, args.command == 'enable')
                result = {'enabled': args.command == 'enable'}
            elif args.command == 'scan':
                result = scan(db, args.provider)
            else:
                _, activated, enabled = settings(db)
                result = {'activated': activated, 'enabled': enabled,
                          'adapters': [dict(x) for x in db.execute('SELECT source,provider,stopped,error FROM auto_threads')],
                          **outbox.status(db)}
            print(outbox.canonical(result))
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError):
        # Vendor data and credentials must never appear in daemon errors.
        print(outbox.canonical({'error': 'capture operation failed; check activation, routing, source compatibility and private configuration'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
