"""Identify Object effects from captured, paired Commons MCP calls."""
import json
import uuid


def object_id(value):
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def effects(tool, args, result):
    if tool == 'read' and args.get('resource', 'object') in ('object', 'object_full'):
        obj = result.get('object')
        oid = object_id(obj.get('id')) if isinstance(obj, dict) else None
        if oid is not None and oid == object_id(args.get('id')):
            return [(oid, obj.get('revision'), 'read')]
    if tool != 'apply' or args.get('execute') is not True or result.get('saved') is not True or result.get('validated_only') is not False:
        return []
    request = args.get('request')
    operations = request.get('operations') if isinstance(request, dict) else None
    refs, changes = result.get('local_refs'), result.get('changes')
    if not isinstance(operations, list) or not isinstance(refs, dict) or not isinstance(changes, list):
        return []
    observed = {(object_id(change.get('id')), change['revision']) for change in changes
                if isinstance(change, dict) and type(change.get('revision')) is int}
    found = []
    for op in operations:
        if not isinstance(op, dict):
            continue
        if op.get('op') == 'create_object' and isinstance(op.get('local_ref'), str):
            oid, revision, action = refs.get(op['local_ref']), 1, 'created'
        elif op.get('op') == 'update_object' and type(op.get('expected_revision')) is int:
            oid, revision, action = op.get('object_id'), op['expected_revision'] + 1, 'updated'
        else:
            continue
        oid = object_id(oid)
        if oid is not None and (oid, revision) in observed:
            found.append((oid, revision, action))
    return found


def trace_for(call, entry, config):
    if call is None or entry.get('status') != 'completed':
        return None
    if any(len(item['body']) > 1024 * 1024 for item in (call, entry)):
        return None
    try:
        request, response = (json.loads(item['body']) for item in (call, entry))
        if request['server'] != config['server'] or request['tool'] not in ('read', 'apply'):
            return None
        result = response['result']
        if result.get('isError', False) is not False or response.get('error'):
            return None
        blocks = result['content']
        if len(blocks) != 1 or blocks[0]['type'] != 'text':
            return None
        payload = json.loads(blocks[0]['text'])
        if payload['installation'] != config['installation']:
            return None
        observed = effects(request['tool'], request['arguments'], payload['result'])
    except (AttributeError, KeyError, RecursionError, TypeError, ValueError):
        return None
    valid = dict.fromkeys(effect for effect in observed
                          if type(effect[1]) is int and 0 < effect[1] < 2**63)
    links = [{'id': oid, 'revision': revision, 'operation': operation}
             for oid, revision, operation in valid]
    if not links or len(links) > 50:
        return None
    sid = 'commons-tool:' + entry['id']
    return {
        'id': str(uuid.uuid5(uuid.NAMESPACE_URL, sid)), 'source_run_id': sid,
        'kind': 'commons-tool-call', 'status': 'completed',
        'input': {'tool': request['tool'], 'tool_call_id': entry['tool_call_id'], 'turn_id': entry['turn_id']},
        'completed_at': entry['source_created_at'], 'object_effects': links,
    }
