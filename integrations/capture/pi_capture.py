#!/usr/bin/env python3
"""Deliver explicitly routed live Pi turns through the existing durable outbox.

No session discovery/backfill. Traces are observed lifecycle events, not native OTLP.
Configuration and tokens stay outside the checkout.
"""
import argparse
import json
from pathlib import Path
import sys
import uuid
import commons_capture as outbox
from auto_capture import sanitize


def envelope(payload, config, secrets=()):
    if payload.get('domain') != 'business':
        return None
    for key in ('session', 'turn', 'started_at', 'completed_at'):
        if not payload.get(key):
            raise ValueError('missing live turn identity/timing')
    source = {'provider': 'pi', 'namespace': config['namespace'], 'thread_id': payload['session']}
    items = []
    for pos, entry in enumerate(payload['items']):
        body, _ = sanitize(entry['body'], secrets)
        items.append({'id': str(uuid.uuid5(uuid.NAMESPACE_URL, outbox.canonical(source)+payload['turn']+str(pos))),
                      'source_item_id': payload['turn']+':'+str(pos), 'turn_id': payload['turn'],
                      'position': payload['position'] + pos, 'kind': entry['kind'], 'role': entry['role'],
                      'speaker_id': config.get('speaker_ids', {}).get(entry['role']),
                      'source_created_at': entry['at'], 'body': body, 'artifact_ids': [],
                      **{k:entry[k] for k in ('tool_name','tool_call_id','status','model') if k in entry}})
    trace, _ = sanitize(payload['events'], secrets)
    return {'contract_version': outbox.CONTRACT, 'source': source, 'batch_id': payload['turn'],
            'title': 'Pi business conversation', 'history': False,
            **({'on_behalf_of': config['on_behalf_of']} if config.get('on_behalf_of') else {}),
            'coverage': {'status':'partial','messages':'Visible text since live input hook; no historical replay',
                         'tools':'Observed tool lifecycle events','attachments':'Not captured',
                         'history':'From extension activation only',
                         'gaps':['No hidden reasoning or image originals; lifecycle trace is not native OpenTelemetry.',
                                 'Live hooks only: crashes before settlement, reloads and oversized turns can omit capture; no historical recovery.']},
            'items': items, 'attachments': [], 'runs': [{
                'id': str(uuid.uuid5(uuid.NAMESPACE_URL, outbox.canonical(source)+payload['turn'])),
                'source_run_id': payload['turn'], 'kind': 'pi-events', 'status':'ended',
                'actor_id': config.get('speaker_ids', {}).get('agent'),
                'input': {'turn_id':payload['turn'],'format':'pi-extension-events/1',
                          'models':payload.get('models', []),'model_coverage':'Observed lifecycle selections and response metadata; missing values are unknown.'},
                'trace': json.loads(trace), 'result':{},
                'review':{'native_spans':False,'gaps':['Extension lifecycle observations; native exporter not configured.']},
                'started_at':payload['started_at'],'completed_at':payload['completed_at']}]}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True)
    args=parser.parse_args(); config=json.loads(Path(args.config).read_text())
    payload=json.load(sys.stdin)
    if payload.get('domain') != 'business':
        print(json.dumps({'excluded':True})); return
    token=Path(config['token_file']).read_text().strip()
    result=envelope(payload,config,(token,))
    with outbox.database(config['state']) as db:
        outbox.initialize(db,config['url'],config['installation'])
        outbox.set_enabled(db,result['source'],True,'Explicitly routed live Pi business turns only')
        queued=outbox.enqueue(db,result)
        delivery=outbox.flush(db,token)
        print(json.dumps({'queued':queued,'delivery':delivery}))
        if delivery.get('delivered',0) == 0 and queued.get('state') != 'acknowledged':
            raise RuntimeError('Capture queued; delivery pending or failed. Reconcile private outbox before retrying.')

if __name__=='__main__':
    main()
