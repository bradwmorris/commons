#!/usr/bin/env python3
"""Atomic-schema retrieval acceptance, isolated fictional data only.

Default: scripts/testing/run retrieval --ollama-binary ... --model-cache ...
uses the real pinned CPU model and records labelled query quality. Missing model
is a failure, never a skip. --disposable-lexical explicitly tests keyword/API/
chunk reconciliation with an unavailable model in a new Docker PostgreSQL; it is
NOT semantic quality, the normal verification lane, or real-agent acceptance.
--disposable-agent --mcp-executable PATH runs an actual Codex client through an
explicit clean-installed MCP package, with a no-Commons control and retained
answers/tool events. It is not a semantic-index or capture-coverage claim.
All authored fixtures use HTTP. SQL is restricted to isolated index inspection
and explicit eligibility/claim/configuration fault injection.
"""
import argparse
import asyncio
import contextlib
import http.cookiejar
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
CORPUS = [
    ("Lumen support agreement", "The service desk operates around the clock.", "", "Who helps customers outside normal business hours?"),
    ("Cedar payroll rule", "Wages are transferred on the final weekday of each month.", "", "When do employees get paid?"),
    ("Orchid access policy", "Departing staff lose all credentials before their last shift ends.", "", "How are former employees prevented from signing in?"),
    ("Juniper warehouse", "Temperature-sensitive parcels travel in refrigerated trucks.", "", "How do we keep medicine cold during delivery?"),
    ("Sable meeting practice", "Decisions are written down for colleagues in other time zones.", "", "How can absent teammates catch up on what was agreed?"),
    ("Harbor continuity", "A standby database is promoted when the primary becomes unavailable.", "", "What happens if the main data server fails?"),
    ("Aster audit record", "A supplier-review evidence document.", "The emergency assembly point is the eastern bicycle shelter.", "Where should people gather after evacuating the building?"),
    ("Birch workshop notes", "An engineering-workshop evidence document.", "Remove customer email addresses before sharing diagnostic logs with vendors.", "How do we protect personal information in troubleshooting files?"),
    ("Quartz field report", "A regional-operations evidence document.", "If an invoice is disputed, suspend collection reminders until the complaint is resolved.", "Should we chase payment while a customer challenges the bill?"),
    ("Willow induction", "A new-colleague evidence document.", "Lost laptops must be reported immediately so the device can be remotely erased.", "What should I do when my work computer is stolen?"),
    ("Peregrine 927", "A calibration certificate for the pressure gauge.", "", "Peregrine 927"),
    ("Nimbus 314", "A travel approval register.", "", "Nimbus 314"),
]


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(fn, seconds=120):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = fn()
            if result:
                return result
        except (OSError, AssertionError, urllib.error.URLError, subprocess.CalledProcessError):
            pass
        time.sleep(.15)
    raise AssertionError("isolated readiness/recovery deadline exceeded")


class HTTP:
    def __init__(self, base, token=None):
        self.base, self.token = base, token
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, body=None, status=200):
        headers = {"Origin": self.base, "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(self.base + "/api/" + path, headers=headers,
            data=None if body is None else json.dumps(body).encode())
        try:
            response = self.opener.open(request, timeout=45)
        except urllib.error.HTTPError as error:
            response = error
        data = json.load(response)
        assert response.code == status, (path, response.code, status, data.get("error"))
        return data

    def apply(self, operations, key=None, execute=True, status=200):
        return self.request("apply", {"contract_version": "commons/0.1", "idempotency_key": key or str(uuid.uuid4()),
                            "operations": operations, "validate_only": not execute}, status)

    def search(self, query, **kwargs):
        return self.request("retrieve?" + urllib.parse.urlencode({"q": query, **kwargs}))


def run_checks(agent, admin, reader, sql, report, real_model, lifecycle):
    def create(title, description, body=""):
        return agent.apply([{"op": "create_object", "local_ref": "new", "kind": "note", "title": title,
                             "description": description, "body": body, "fields": {"intent": "fact"}}])["local_refs"]["new"]

    def current(oid):
        return agent.request("objects/" + oid)["object"]

    def body(oid, text):
        o = current(oid)
        return agent.apply([{"op": "update_object", "object_id": oid, "expected_revision": o["revision"], "body": text}])

    def artifact(oid, text, **extra):
        o = current(oid)
        result = agent.apply([{"op": "save_artifact", "object_id": oid, "expected_revision": o["revision"],
            "artifact": {"body": text, **extra}}])
        return result["changes"][0]["artifact_id"]

    def ids(response):
        return [o["id"] for o in response["context"]["objects"] if o["match"]["relation"] == "query_candidate"]

    primary = create("Frostlane delivery", "A delivery policy for temperature-sensitive shipments.", "Route parcels via the eastern depot.")
    relevant = create("Cold-chain exception", "An exception to Frostlane delivery during refrigeration failure.")
    unrelated = create("Garden roster", "A plan for watering indoor plants.")
    for oid, why in [(unrelated, "General office reference."), (relevant, "Frostlane delivery requires this cold-chain exception when refrigeration fails.")]:
        a, b = current(primary), current(oid)
        agent.apply([{"op": "create_connection", "from_id": primary, "to_id": oid, "from_revision": a["revision"],
                      "to_revision": b["revision"], "kind": "related_to", "explanation": why}])
    result = agent.search("Frostlane delivery", limit=1, neighbours=1)
    assert ids(result) == [primary]
    neighbours = [o["id"] for o in result["context"]["objects"] if o["match"]["relation"] == "existing_connection"]
    assert neighbours == [relevant], neighbours
    assert all("body" not in o and "fields" not in o and "excerpt" not in o["match"] for o in result["context"]["objects"])
    assert result["context_bytes"] <= result["budget"]
    report["checks"].append("compact Object-first discovery; relevant neighbour outranks unrelated link")
    # A title hit outranks identical words occurring only in another Object's body.
    body_only = create("Internal routing detail", "A description of a routing decision.", "Frostlane delivery")
    result = agent.search("Frostlane delivery", neighbours=0)
    assert ids(result)[0] == primary
    assert body_only in ids(result)
    assert relevant in ids(result)
    primary_ids=set(ids(result))
    assert result['neighbour_count']==0
    assert any({c['from_id'],c['to_id']}=={primary,relevant} for c in result['context']['connections'])
    assert all(c['from_id'] in primary_ids and c['to_id'] in primary_ids for c in result['context']['connections'])
    single=agent.search('Frostlane delivery',limit=1,neighbours=0)
    assert ids(single)==[primary] and not single['context']['connections']
    report["checks"].append("title/description priority; whole-Object body remains searchable")
    source = create("Sequoia source", "A source with original supporting material.")
    aid = artifact(source, "Opening context. " * 3000 + "Cobaltwhistle evacuation shelter.")
    assert source not in ids(agent.search("Cobaltwhistle", neighbours=0))
    evidence_search=agent.search('Cobaltwhistle',scope='artifacts',neighbours=0)
    assert source in ids(evidence_search)
    if evidence_search['index']['scope_pending']>0:
        assert not evidence_search['timings']['model_attempted']
    assert source in ids(agent.search("Cobaltwhistle", scope="all", kind="note", object_id=source, neighbours=0))
    assert not ids(agent.search("Cobaltwhistle", scope="all", kind="task", neighbours=0))
    window = agent.request(f"artifacts/{aid}/text?offset=0&limit=1000")
    assert len(window["text"]) == 1000 and window["next_offset"] == 1000
    report["checks"].append("Artifact-only tail discovery, filters and deliberate Unicode evidence window")
    empty = artifact(source, "")
    artifact(source, "Hiddenincomplete evidence", capture_outcome="incomplete", capture_reason="Synthetic unavailable remainder")
    assert source not in ids(agent.search("Hiddenincomplete", scope="all", neighbours=0))
    # Explicit isolated eligibility fault: migrated historical state is not user-editable.
    historical = create("Historicalneedle policy", "A historical policy retained only for explicit reads.")
    artifact(historical, "Historicalartifactneedle material")
    sql(f"UPDATE objects SET provenance='{{\"historical_only\":true}}' WHERE id='{historical}'")
    for query in ("Historicalneedle", "Historicalartifactneedle", historical):
        assert historical not in ids(agent.search(query, scope="all", neighbours=0))
    assert current(historical)["id"] == historical
    assert all(o["id"] != historical for o in agent.request("objects?q=Historicalneedle")["objects"])
    report["checks"].append("historical-only Object and Artifact exclusion, exact reads retained")
    managed = create("Rawcaptureneedle", "A synthetic managed raw-copy eligibility fixture.")
    ma = artifact(managed, "Rawcaptureneedle evidence")
    sql(f"INSERT INTO connections(id,from_id,to_id,kind,explanation) VALUES('{uuid.uuid4()}','{primary}','{managed}','managed_copy','Synthetic eligibility fault')")
    assert managed not in ids(agent.search("Rawcaptureneedle", scope="all", neighbours=0))
    # Typed managed targets have NULL to_id; they must not poison Object membership.
    sql(f"INSERT INTO connections(id,from_id,to_artifact_id,kind,explanation) VALUES('{uuid.uuid4()}','{primary}','{ma}','managed_copy','Synthetic typed eligibility fault')")
    assert primary in ids(agent.search('Frostlane delivery',neighbours=0))
    assert managed not in ids(agent.search('Rawcaptureneedle',scope='all',neighbours=0))
    report["checks"].append("managed raw-copy exclusion and NULL-safe typed-target membership")
    malformed=create('Malformedexcerptneedle','A synthetic legacy malformed-reference fixture.')
    sql(f"BEGIN; ALTER TABLE objects DISABLE TRIGGER note_managed_lineage; UPDATE objects SET fields=fields||'{{\"intent\":\"excerpt\",\"source_artifact_id\":\"not-a-uuid\"}}'::jsonb WHERE id='{malformed}'; ALTER TABLE objects ENABLE TRIGGER note_managed_lineage; COMMIT")
    assert malformed not in ids(agent.search('Malformedexcerptneedle',neighbours=0))
    report['checks'].append('malformed legacy excerpt reference excludes safely without a UUID cast error')
    # Corrections do not search private change envelopes or stale original evidence.
    o = current(source)
    corrected_text = "Préface 東京 🌿. Amberwhistle corrected shelter."
    agent.apply([{"op": "correct_evidence", "object_id": source, "expected_revision": o["revision"],
        "target_type": "artifact", "target_id": aid, "reason": "Synthetic correction test",
        "representation": {"body": corrected_text}}])
    assert source not in ids(agent.search("Cobaltwhistle", scope="artifacts", neighbours=0))
    corrected_match = next(o['match'] for o in agent.search("Amberwhistle", scope="artifacts", neighbours=0)['context']['objects'] if o['id']==source)
    assert corrected_match['read']['resource']=='correction' and corrected_match['field']=='representation.body'
    correction_id = corrected_match['read']['id']
    correction = agent.request('corrections/'+correction_id)['correction']
    assert correction['representation']['body']==corrected_text
    wait(lambda: int(sql(f"SELECT count(*) FROM chunks WHERE artifact_id='{aid}' AND reference LIKE 'correction:{correction_id}:%'"))>0)
    loc = sql(f"SELECT reference FROM chunks WHERE artifact_id='{aid}' ORDER BY ordinal LIMIT 1").split(':')
    start, end = map(int,loc[-2:])
    assert loc[-3]=='body' and correction['representation']['body'][start:end]==corrected_text[start:end]
    assert 'Opening context' not in corrected_text[start:end]
    # An arbitrary structured correction is NOT document text or a JSON search blob.
    bad_source = create('Correction shape fixture','A source for a non-text correction test.')
    bad_artifact = artifact(bad_source,'Oldunsupportedneedle original.')
    b = current(bad_source)
    agent.apply([{'op':'correct_evidence','object_id':bad_source,'expected_revision':b['revision'],
        'target_type':'artifact','target_id':bad_artifact,'reason':'Synthetic non-text assertion',
        'representation':{'not_document_text':'Hiddenjsonneedle'}}])
    bad_result=agent.search('Hiddenjsonneedle',scope='artifacts',neighbours=0)
    assert bad_source not in ids(bad_result)
    assert bad_result['index']['unsupported_corrections']>=1
    assert 'unsupported_correction_text' in bad_result['index']['errors']
    b=current(bad_source)
    agent.apply([{'op':'correct_evidence','object_id':bad_source,'expected_revision':b['revision'],
        'target_type':'artifact','target_id':bad_artifact,'reason':'Provide explicit corrected text',
        'representation':{'text':'Supportedtextneedle correction.'}}])
    text_match=next(o['match'] for o in agent.search('Supportedtextneedle',scope='artifacts',neighbours=0)['context']['objects'] if o['id']==bad_source)
    assert text_match['field']=='representation.text' and text_match['read']['resource']=='correction'
    report['checks'].append('Unicode correction field locators; unsupported correction JSON excluded and flagged')
    assert "Opening context" in agent.request(f"artifacts/{aid}/text?limit=100")["text"]
    report["checks"].append("current Artifact correction matching, immutable original preserved")
    # Draft/atomic failure and writes that cannot bypass whole-packet validation.
    revision = current(primary)["revision"]
    agent.apply([{"op": "update_object", "object_id": primary, "expected_revision": revision,
                  "body": "Overlong packet. " * 1000}], status=422)
    assert current(primary)["revision"] == revision
    key = str(uuid.uuid4())
    op = {"op": "update_object", "object_id": primary, "expected_revision": revision, "body": "Use the west depot."}
    before = current(primary)
    agent.apply([op], execute=False)
    assert current(primary) == before
    first = agent.apply([op], key=key)
    assert agent.apply([op], key=key) == first
    agent.apply([op], status=409)
    report["checks"].append("oversize rejection, validation rollback, exact replay and stale-write denial")
    reader.search("Frostlane", neighbours=0)
    reader.request("retrieval/rebuild", {}, 403)
    report["checks"].append("reader discovery and rebuild denial")
    # The configured but unavailable runtime still prepares input sets durably.
    expected_input = "title: Frostlane delivery | text: A delivery policy for temperature-sensitive shipments.\n\nUse the west depot."
    wait(lambda: sql(f"SELECT body FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL") == expected_input)
    assert sql(f"SELECT count(*) FROM chunks WHERE artifact_id='{empty}'") == '0'
    wait(lambda: sql(f"SELECT count(*) FROM chunks WHERE object_id IN('{managed}','{historical}')") == '0')
    assert int(sql(f"SELECT count(*) FROM chunks WHERE artifact_id='{ma}'")) == 0
    # Old claims cannot publish after text/configuration changes.
    old = sql(f"SELECT id FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL")
    sql(f"UPDATE chunks SET status='processing',claim='{uuid.uuid4()}',claimed_at=now()-interval '10 minutes',available_at=now()-interval '1 second' WHERE id='{old}'")
    body(primary, "Stalefencedneedle replacement depot.")
    wait(lambda: sql(f"SELECT count(*) FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL AND id<>'{old}'") == '1')
    assert int(sql(f"SELECT count(*) FROM chunks WHERE id='{old}'")) == 0
    assert "west depot" not in sql(f"SELECT body FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL")
    if not real_model:
        assert primary not in ids(agent.search("west depot", neighbours=0))
    assert primary in ids(agent.search("Stalefencedneedle", neighbours=0))
    sql(f"UPDATE chunks SET space='incompatible-fixture-space' WHERE object_id='{primary}'")
    wait(lambda: sql(f"SELECT count(*) FROM chunks WHERE object_id='{primary}' AND space='incompatible-fixture-space'") == '0')
    report["checks"].append("one exact Object input; empty Artifact; source/config/old-claim fences")
    # Exercise actual product tool modules over authenticated HTTP, not just mocks.
    import sys
    sys.path.insert(0, str(ROOT))
    from tools import commons_read, commons_search, commons_write
    from tools.client import CommonsError
    class ToolHTTP:
        async def request(self, method, path, *, params=None, json=None):
            assert path.startswith('/api/')
            route = path[5:] + ('?' + urllib.parse.urlencode(params) if params else '')
            return agent.request(route, json if method == 'POST' else None)
    async def tool_journey():
        c = ToolHTTP()
        result = await commons_search.execute({"query": "Stalefencedneedle", "neighbours": 0}, c)
        assert primary in ids(result)
        obj = (await commons_read.execute({"resource": "object", "id": primary}, c))["object"]
        result = await commons_write.execute({"idempotency_key": str(uuid.uuid4()), "operations": [{
            "op": "update_object", "object_id": primary, "expected_revision": obj["revision"],
            "body": "Toolroundtripneedle depot."}]}, c)
        assert result["validated_only"] and not result["saved"]
        assert current(primary)["body"] == obj["body"]
        links = await commons_read.execute({"resource": "connections", "object_id": primary}, c)
        assert links["connections"]
        schema = await commons_read.execute({"resource": "schema"}, c)
        assert schema["schema_version"] == 12
        exact = await commons_read.execute({**corrected_match['read'], 'offset': 2, 'limit': 12}, c)
        assert exact['text'] == corrected_text[2:14] and exact['field'] == 'representation.body'
        create_args={'idempotency_key':str(uuid.uuid4()),'execute':True,'operations':[{
            'op':'create_object','local_ref':'new','kind':'note','title':'Moduletestneedle decision',
            'description':'A synthetic decision saved through the product write tool.',
            'body':'Use the tested onboarding path.','fields':{'intent':'fact'}}]}
        created=await commons_write.execute(create_args,c)
        assert await commons_write.execute(create_args,c)==created
        new_id=created['local_refs']['new']
        opened=(await commons_read.execute({'resource':'object','id':new_id},c))['object']
        target=current(relevant)
        await commons_write.execute({'idempotency_key':str(uuid.uuid4()),'execute':True,'operations':[{
            'op':'create_connection','from_id':new_id,'to_id':relevant,'from_revision':opened['revision'],
            'to_revision':target['revision'],'kind':'related_to','explanation':'The decision references this exception for onboarding checks.'}]},c)
        discovered=await commons_search.execute({'query':'Moduletestneedle','neighbours':0},c)
        assert new_id in ids(discovered)
        connected=await commons_read.execute({'resource':'connections','object_id':new_id},c)
        assert len(connected['connections'])==1
    asyncio.run(tool_journey())
    report["checks"].append("three product modules exercised against real authenticated API")
    # A bookkeeping-only patch changes revision but retains the same chunk/input.
    stable = sql(f"SELECT id||':'||input_hash FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL")
    p = current(primary)
    agent.apply([{"op":"update_object","object_id":primary,"expected_revision":p["revision"],"fields":{"happened_at":"2026-01-01T00:00:00Z"}}])
    wait(lambda: sql(f"SELECT object_revision FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL") == str(current(primary)["revision"]))
    assert sql(f"SELECT id||':'||input_hash FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL") == stable
    report["checks"].append("bookkeeping revision preserves exact chunk and embedding input")
    # Conversation content is a separate long source, not an ordinary atomic packet.
    thread=str(uuid.uuid4());item=str(uuid.uuid4())
    projection_body='Visible padding for synthetic search. '*90+'Threadonlycobaltneedle. Customers can reach the service desk at any hour, day or night.'
    capture=dict(contract_version='commons.capture/1',source=dict(provider='Synthetic',namespace='retrieval',thread_id=thread),chat_id=thread,batch_id='first',title='Synthetic support discussion',coverage=dict(status='partial',messages='visible',tools='visible',attachments='none',history='current',gaps=['Synthetic partial capture']),items=[dict(id=item,source_item_id='message',position=0,kind='message',role='human',body=projection_body)],runs=[])
    admin.request('capture',capture)
    wait(lambda: int(sql(f"SELECT count(*) FROM chunks WHERE object_id='{thread}'"))>1)
    assert int(sql(f"SELECT count(*) FROM chunks WHERE object_id='{thread}' AND artifact_id IS NOT NULL"))==0
    response=reader.search('Threadonlycobaltneedle',scope='threads',object_id=thread,neighbours=0)
    assert thread in ids(response)
    match=response['context']['objects'][0]['match'];read=match['read']
    window=reader.request('threads/'+thread+'/text?'+urllib.parse.urlencode({k:v for k,v in read.items() if k not in ['id','resource']}))
    assert 'Threadonlycobaltneedle' in window['text'] and window['coverage']['status']=='partial'
    assert not ids(reader.search('Threadonlycobaltneedle',scope='artifacts',object_id=thread))
    status=agent.request('retrieval/status')['index'];assert status['thread_sources']>=1 and status['excluded_incomplete_artifacts']>=1
    if real_model:
        wait(lambda: reader.search('How can customers get help overnight?',scope='threads',object_id=thread,neighbours=0)['mode']=='hybrid',180)
        semantic=reader.search('How can customers get help overnight?',scope='threads',object_id=thread,neighbours=0)
        assert semantic['mode']=='hybrid' and thread in ids(semantic)
        semantic_read=semantic['context']['objects'][0]['match']['read'];assert semantic_read['resource']=='thread_text'
        assert reader.request('threads/'+thread+'/text?'+urllib.parse.urlencode({k:v for k,v in semantic_read.items() if k not in ['id','resource']}))['text']
    # Corrected messages fence old claims/input and exact stale read references.
    revision=current(thread)['revision']
    admin.apply([dict(op='correct_evidence',object_id=thread,expected_revision=revision,target_type='message',target_id=item,reason='Synthetic correction',representation=dict(body='Threadreplacementneedle visible corrected content.'))])
    reader.request('threads/'+thread+'/text?'+urllib.parse.urlencode({k:v for k,v in read.items() if k not in ['id','resource']}),status=409)
    wait(lambda: 'Threadonlycobaltneedle' not in sql(f"SELECT string_agg(body,'') FROM chunks WHERE object_id='{thread}'"))
    revision=current(thread)['revision'];admin.request('threads/'+thread+'/delete',dict(expected_revision=revision,acknowledge_managed_copy_deletion=True))
    assert sql(f"SELECT count(*) FROM chunks WHERE object_id='{thread}'")=='0'
    assert not ids(reader.search('Threadreplacementneedle',scope='threads',object_id=thread))
    admin.request('capture',capture,status=410)
    report['checks'].append('visible Thread multi-window index, reader search/read, real semantic query when enabled, correction stale-reference fence, deletion and capture replay denial')
    if not real_model:
        sql(f"UPDATE chunks SET status='pending',attempts=7,available_at=now(),claim=NULL WHERE object_id='{primary}' AND artifact_id IS NULL")
        wait(lambda: sql(f"SELECT status FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL") == 'failed')
        assert agent.request('retrieval/status')['index']['failed'] >= 1
        admin.request('retrieval/rebuild', {})
        assert sql(f"SELECT attempts FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL") in ('0','1')
        report["checks"].append("bounded failed embedding attempts and explicit rebuild retry")
        result = agent.search("Frostlane", neighbours=0)
        assert result["mode"] == 'lexical_only' and result["reason"]
        report["checks"].append("explicit keyword-only degraded result with unavailable runtime")
        return
    # Labelled semantic cases only run with the actual pinned model.
    corpus_ids = []
    for title, description, evidence, _ in CORPUS:
        oid = create(title, description)
        if evidence:
            artifact(oid, evidence)
        corpus_ids.append(oid)
    for i in range(8):
        create(f"Office distractor {i}", "A record about stationery, plants and the office lunch menu.")
    admin.request('retrieval/rebuild', {})
    wait(lambda: agent.request('retrieval/status')['index']['pending'] == 0 and agent.request('retrieval/status')['index']['failed'] == 0, 600)
    ranks = []
    for oid, (_, _, evidence, query) in zip(corpus_ids, CORPUS):
        started = time.monotonic()
        result = agent.search(query, scope='all', neighbours=0)
        assert result['mode'] == 'hybrid', result['reason']
        matches = ids(result)
        rank = matches.index(oid) + 1 if oid in matches else None
        ranks.append(rank)
        report['queries'].append({'query': query, 'rank': rank, 'seconds': time.monotonic()-started,
                                  'context_bytes': result['context_bytes'],'stages':result.get('timings')})
    report['recall_at_5'] = sum(r is not None for r in ranks)/len(ranks)
    report['mrr_at_5'] = sum(1/r if r else 0 for r in ranks)/len(ranks)
    assert report['recall_at_5'] >= .85 and report['mrr_at_5'] >= .75
    report['checks'].append('real pinned model labelled retrieval quality')
    snapshot = current(primary)
    chunk_snapshot = sql(f"SELECT id||':'||input_hash||':'||embedding::text FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL")
    lifecycle['restart_app']()
    assert current(primary) == snapshot
    assert agent.apply([op],key=key) == first
    assert sql(f"SELECT id||':'||input_hash||':'||embedding::text FROM chunks WHERE object_id='{primary}' AND artifact_id IS NULL") == chunk_snapshot
    report['checks'].append('API restart preserves exact current Object/vector and replay receipt')
    lifecycle['pause_model']()
    try:
        degraded = agent.search('Frostlane',neighbours=0)
        assert degraded['mode']=='lexical_only' and degraded['reason']
        assert primary in ids(degraded)
        assert degraded['timings']['model_attempted'] and degraded['timings']['model_ms']>0
    finally:
        lifecycle['resume_model']()
    wait(lambda: agent.search('Frostlane',neighbours=0)['mode']=='hybrid',120)
    report.setdefault('stage_examples',{})['ready_scope_model_outage']=degraded['timings']
    report['checks'].append('real runtime outage gives keyword fallback; runtime recovery restores hybrid')
    # Stress chunk-set creation beyond the retired 512-passage limit without
    # requiring every passage to finish inference for this preparation check.
    long_source = create('Extended evidence fixture','A source for a long-document chunk-preparation check.')
    long_text = 'A repeated supporting observation. ' * 18000 + ' Longtailneedle end.'
    long_artifact = artifact(long_source,long_text)
    wait(lambda: int(sql(f"SELECT count(*) FROM chunks WHERE artifact_id='{long_artifact}'"))>512,180)
    assert long_source in ids(agent.search('Longtailneedle',scope='artifacts',neighbours=0))
    assert int(sql(f"SELECT max(split_part(reference,':',4)::int) FROM chunks WHERE artifact_id='{long_artifact}'")) == len(long_text)
    pending_evidence=agent.search('Longtailneedle',scope='artifacts',object_id=long_source,neighbours=0)
    assert pending_evidence['index']['scope_pending']>0
    assert not pending_evidence['timings']['model_attempted'] and pending_evidence['timings']['model_ms']==0
    report.setdefault('stage_examples',{})['unready_artifact_scope']=pending_evidence['timings']
    scoped=wait(lambda: (r if (r:=agent.search('Frostlane',scope='objects',neighbours=0))['mode']=='hybrid' else None),120)
    assert scoped['index']['scope_pending']==0 and scoped['index']['scope_failed']==0
    assert scoped['index']['coverage']=='requested_scope' and scoped['index']['pending']==0
    assert agent.request('retrieval/status')['index']['pending']>0, 'global Artifact work should remain explicitly separate'
    report['checks'].append('Object-scope hybrid readiness is independent of pending long Artifact embeddings')
    report['checks'].append('more than512 Artifact chunks prepared atomically; exact tail remains keyword searchable')


def benchmark(agent, admin, sql, lifecycle, report, log_snapshot):
    """Same isolated corpus, sequential binaries, no inference or live queries."""
    objects=[]
    started=time.monotonic()
    for batch in range(40):
        ops=[{'op':'create_object','local_ref':f'n{i}','kind':'source' if batch*50+i<346 else 'note',
              'title':f'Synthetic operations record {batch*50+i}',
              'description':'A synthetic operational decision about delivery and team coordination.',
              'body':'Keep the original evidence linked and use the eastern depot when refrigeration is available.',
              'fields':{'source_kind':'document'} if batch*50+i<346 else {'intent':'fact'}} for i in range(50)]
        refs=agent.apply(ops)['local_refs']
        objects.extend(refs[f'n{i}'] for i in range(50))
    unit='Representative original evidence on operations, staffing and shipment handling. '
    artifacts=[]
    for index,oid in enumerate(objects[:1024]):
        text=unit*(19750 if index==0 else 6400 if index<10 else 350)
        revision=agent.request('objects/'+oid)['object']['revision']
        receipt=agent.apply([{'op':'append_artifact','object_id':oid,'expected_revision':revision,'body':text}])
        artifacts.append(receipt['changes'][0]['artifact_id'])
    quote=text[:80]
    for i,oid in enumerate(objects[1100:1150]):
        revision=agent.request('objects/'+oid)['object']['revision']
        agent.apply([{'op':'update_object','object_id':oid,'expected_revision':revision,'body':quote,
            'fields':{'intent':'excerpt','source_artifact_id':artifacts[i%len(artifacts)],
                      'source_locator':{'kind':'text_offset','start':0,'end':len(quote)}}}])
    # Ordinary graph density matters: live installations have ~32k normal links
    # and only zero/four managed targets. Write canonical links through the API.
    revisions={oid:agent.request('objects/'+oid)['object']['revision'] for oid in objects}
    ops=[]
    for index,oid in enumerate(objects):
        for distance in range(1,17):
            target=objects[(index+distance)%len(objects)]
            ops.append({'op':'create_connection','from_id':oid,'to_id':target,
                        'from_revision':revisions[oid],'to_revision':revisions[target],
                        'kind':'related_to','explanation':'Synthetic operations dependency for graph-density testing.'})
            revisions[oid]+=1
            revisions[target]+=1
            if len(ops)==50:
                agent.apply(ops)
                ops=[]
    assert not ops
    # Explicit synthetic lineage faults without importing conversations/capture.
    for oid in objects[-4:]:
        sql(f"INSERT INTO connections(id,from_id,to_id,kind,explanation) VALUES('{uuid.uuid4()}','{objects[0]}','{oid}','managed_copy','Synthetic eligibility fixture')")
    report['corpus']={'objects':len(objects),'artifacts':1024,'artifact_characters':sum(len(unit)*(19750 if i==0 else 6400 if i<10 else 350) for i in range(1024)),
                      'excerpt_notes':50,'ordinary_connections':32000,'managed_copy_links':4,'setup_seconds':time.monotonic()-started,'inference':'disabled in both conditions'}
    # Genuine pending derived entries (no vectors), using the same canonical
    # packet, source hash and exact ASCII windows as the worker. Canonical data
    # above was written through HTTP. This is synthetic index-fixture injection,
    # not a fake semantic pass or mutation of an existing installation.
    source=Path('src/retrieval.rs').read_text()
    eligible=re.search(r'const ELIGIBLE: &str = r#"(.*?)"#;',source,re.S).group(1)
    space=re.search(r'const SPACE: &str = "(.*?)";',source).group(1)
    sql(f"""WITH eligible AS ({eligible}), packets AS (
      SELECT id,title,revision,'title: '||title||' | text: '||description||E'\n\n'||body AS input FROM eligible
    ) INSERT INTO chunks(id,object_id,ordinal,reference,body,input_hash,object_revision,space,status)
      SELECT gen_random_uuid(),id,0,'object:'||id::text,input,
       md5(md5(jsonb_build_array(title,input)::text)||input),revision,'{space}','pending' FROM packets""")
    sql(f"""WITH eligible AS ({eligible}), chosen AS (
      SELECT a.id,a.object_id,a.body,o.title,o.revision FROM artifacts a JOIN eligible o ON o.id=a.object_id
       WHERE length(a.body)<=30000 ORDER BY a.id LIMIT 64
    ), windows AS (
      SELECT *,pos AS start_pos,least(pos+1000,length(body)) AS end_pos,
        row_number() OVER(PARTITION BY id ORDER BY pos)-1 AS ordinal,
        'title: '||title||' | text: '||E'\n\n'||substring(body FROM pos+1 FOR 1000) AS input
      FROM chosen CROSS JOIN LATERAL generate_series(0,greatest(0,ceil((length(body)-1000)::numeric/900)::int*900),900) pos
    ) INSERT INTO chunks(id,object_id,artifact_id,ordinal,reference,body,input_hash,object_revision,space,status)
      SELECT gen_random_uuid(),object_id,id,ordinal,'artifact:'||id::text||':'||start_pos||':'||end_pos,input,
       md5(md5(jsonb_build_array(title,body)::text)||input),revision,'{space}','pending' FROM windows""")
    prepared=int(sql('SELECT count(*) FROM chunks'))
    assert prepared>=3500 and sql('SELECT count(*) FROM chunks WHERE embedding IS NOT NULL')=='0'
    assert int(sql("SELECT count(*) FROM chunks WHERE position(chr(10)||chr(10) IN body)>0"))==prepared
    report['corpus']['prepared_pending_chunks']=prepared
    sql('ANALYZE')
    sql("ALTER SYSTEM SET auto_explain.log_min_duration='0ms'")
    sql('SELECT pg_reload_conf()')
    def inspect_plans(raw):
        def joins(node):
            found=[]
            if node.get('Node Type') in ('Nested Loop','Hash Join','Merge Join','CTE Scan'):
                found.append({k:node.get(k) for k in ('Node Type','Join Type','CTE Name','Actual Loops','Actual Rows','Plan Rows','Rows Removed by Join Filter') if node.get(k) is not None})
            for child in node.get('Plans',[]):found.extend(joins(child))
            return found
        results=[]
        decoder=json.JSONDecoder()
        for fragment in raw.split('plan:')[1:]:
            begin=fragment.find('{')
            if begin<0:continue
            try: plan,_=decoder.raw_decode(fragment[begin:])
            except json.JSONDecodeError:continue
            query=plan.get('Query Text','')
            if 'current_chunks AS' not in query and 'slices AS' not in query:continue
            results.append({'query':'status' if 'current_chunks AS' in query else 'keyword',
                'plan_total_ms':plan.get('Plan',{}).get('Actual Total Time'),
                'join_nodes':joins(plan.get('Plan',{})),
                'estimated_total_cost':plan.get('Plan',{}).get('Total Cost'),
                'jit':plan.get('JIT'), 'settings':plan.get('Settings'),
                'artifact_document_branch':'JOIN artifacts a ON a.object_id=o.id' in query,
                'hash_expression':'md5(' in query,
                'shared_hits':plan.get('Plan',{}).get('Shared Hit Blocks'),
                'temp_read_blocks':plan.get('Plan',{}).get('Temp Read Blocks'),
                'temp_written_blocks':plan.get('Plan',{}).get('Temp Written Blocks')})
        return results
    for phase in ('baseline','candidate'):
        if phase=='candidate':lifecycle['candidate_app']()
        begin=log_snapshot()
        rows=[]
        for _ in range(3):
            started=time.monotonic()
            status=agent.request('retrieval/status')
            status_seconds=time.monotonic()-started
            started=time.monotonic()
            result=agent.search('Synthetic operations record 777',limit=5,neighbours=0)
            search_seconds=time.monotonic()-started
            assert objects[777] in [o['id'] for o in result['context']['objects']]
            assert result['mode']=='lexical_only'
            rows.append({'status_seconds':status_seconds,'search_seconds':search_seconds,
                         'pending':status['index']['pending'],'eligible_objects':status['index']['eligible'],'search_pending':result['index']['pending'],
                         'search_coverage':result['index'].get('coverage'),'stages':result.get('timings'),'context_bytes':result['context_bytes']})
        raw=log_snapshot()[len(begin):]
        plans=inspect_plans(raw)
        report[phase]={'requests':rows,'plans':plans}
        if phase=='candidate':
            assert all(x['search_coverage']=='requested_scope' and x['search_pending']==x['eligible_objects'] for x in rows)
            assert sum(p['artifact_document_branch'] for p in plans)==3, 'only the3 explicit global diagnostics may include Artifact documents'
            assert all(not p['hash_expression'] for p in plans if p['query']=='status'), 'readiness and global status must not hash document bodies'
            assert all(not p['artifact_document_branch'] for p in plans if p['query']=='keyword')
            assert all(j.get('Actual Loops',0)<=1 for p in plans if p['query']=='status'
                       for j in p['join_nodes'] if j.get('CTE Name') in ('current_chunks','current_sources')), 'status must not rescan populated chunk sets per source'
    report['checks'].append('same2000-Object1024-Artifact50-excerpt32000-normal4-managed-link populated-index corpus baseline/candidate status and keyword API latency with actual logged plans')


def agent_journey(agent, report, result_dir, work, args):
    """Actual client, packaged stdio MCP, fictional API data; no live records.

    The control has the same question but no Commons connection. It establishes
    an inspectable missing-context case, not a general benefit claim or grade.
    """
    def create(title, description, body='', kind='note'):
        fields={'source_kind':'document'} if kind=='source' else {'intent':'fact'}
        return agent.apply([{'op':'create_object','local_ref':'new','kind':kind,
                            'title':title,'description':description,'body':body,'fields':fields}])['local_refs']['new']
    def current(oid):
        return agent.request('objects/'+oid)['object']
    def connect(a,b,why):
        return agent.apply([{'op':'create_connection','from_id':a,'to_id':b,
                            'from_revision':current(a)['revision'],'to_revision':current(b)['revision'],
                            'kind':'related_to','explanation':why}])
    primary=create('Snowfin delivery policy','A note recording the default depot policy for Snowfin shipments.',
                   'Use the East depot for routine temperature-controlled shipments when refrigeration is working.')
    exception=create('Thermal interruption handling','A note recording the depot exception during failed refrigeration.',
                     'During a refrigeration outage use the North quarantine bay, never the routine East depot. Release requires the current signed field procedure.')
    source=create('Field procedure 927','A signed procedure source specifying approval and dispatch authorization for quarantined parcels.',kind='source')
    connect(primary,exception,'Snowfin refrigeration outage shipments follow this exception instead of the routine depot policy.')
    connect(primary,source,'The current signed procedure supplies the approval and dispatch code for a Snowfin refrigeration outage.')
    for i in range(10):
        unrelated=create(f'Office reference {i}','A note recording an office watering or stationery arrangement.')
        connect(primary,unrelated,'General office background; no shipment handling instruction.')
    original='Obsolete emergency authorization: Dana Vale, code OLD-19. Retained original, superseded by a correction.'
    saved=agent.apply([{'op':'append_artifact','object_id':source,'expected_revision':current(source)['revision'],'body':original}])
    aid=saved['changes'][0]['artifact_id']
    corrected=('Synthetic field procedure background. '*1000)+'\nRésumé 🚀 東京. Snowfin emergency release requires Mira Cho approval and dispatch code VELA-73. Use the North quarantine bay; the East depot is forbidden until refrigeration recovers.\n'+('Supporting fictional context. '*100)
    saved=agent.apply([{'op':'correct_evidence','object_id':source,'expected_revision':current(source)['revision'],
                       'target_type':'artifact','target_id':aid,'reason':'Replace the obsolete emergency sign-off with the current signed procedure.',
                       'representation':{'body':corrected}}])
    report['agent_fixture']={'primary':primary,'exception':exception,'source':source,'artifact':aid,
                             'corrected_characters':len(corrected),'ordinary_distractors':10,
                             'api_binary_sha256':hashlib.sha256(Path('target/debug/commons').read_bytes()).hexdigest(),
                             'mcp_executable':args.mcp_executable,'model_index':'not configured; honest keyword fallback',
                             'capture':'not asserted; private CLI events are independent test evidence'}
    question=('A refrigerator has failed for a Snowfin shipment. Which depot should the dispatcher use, whose approval is needed, and what dispatch code applies? '
              'Check current signed evidence, explain any exception to the default policy, and cite exact records. '
              'If the evidence supports a decision, save one concise operational decision note and meaningful evidence-supported connections; read it back. '
              'If you cannot verify the details, say so rather than guessing. This is an authorized fictional acceptance test; do not send messages or change existing records.')
    # All authored seed records are known; a final API read checks actual effects.
    before={o['id'] for o in agent.request('objects?kind=note&limit=200')['objects']}
    inherited={k:v for k,v in os.environ.items() if not k.startswith(('PG','COMMONS_','CODEX_THREAD')) and k!='DATABASE_URL'}
    token=agent.token
    arms=[]
    for arm in ('without_commons','with_commons'):
        cwd=work/arm
        cwd.mkdir()
        event_path=result_dir/(arm+'-events.jsonl')
        error_path=result_dir/(arm+'-stderr.log')
        output_path=result_dir/(arm+'-answer.txt')
        command=[args.agent_executable,'exec','--ignore-user-config','--ignore-rules','--ephemeral',
                 '--skip-git-repo-check','--sandbox','read-only','--json','--cd',str(cwd),
                 '-c','project_doc_max_bytes=0','-c','web_search="disabled"',
                 '--output-last-message',str(output_path)]
        arm_env=dict(inherited)
        if arm=='with_commons':
            command+=['-c','mcp_servers.commons.command='+json.dumps(args.mcp_executable),
                      '-c','mcp_servers.commons.env_vars=["COMMONS_URL","COMMONS_TOKEN"]',
                      '-c','mcp_servers.commons.default_tools_approval_mode="approve"']
            arm_env.update(COMMONS_URL=agent.base,COMMONS_TOKEN=token)
        prompt=('Use only the Commons MCP tools if available. Do not use shell, files, web, skills, other servers or ask a human for help. '
                'Before substantive work consult relevant shared knowledge; save useful verified decisions with specific justified links when authorized.\n\n'+question)
        start=time.monotonic()
        with event_path.open('w') as events,error_path.open('w') as errors:
            done=subprocess.run(command,input=prompt,text=True,env=arm_env,stdout=events,stderr=errors,timeout=300)
        raw=event_path.read_text()
        assert token not in raw and token not in error_path.read_text(), 'synthetic credential must never appear in output'
        events=[json.loads(line) for line in raw.splitlines() if line.strip()]
        items=[e['item'] for e in events if e.get('type')=='item.completed' and isinstance(e.get('item'),dict)]
        calls=[i for i in items if i.get('type')=='mcp_tool_call']
        forbidden=[i.get('type') for i in items if i.get('type') in ('command_execution','web_search','collab_tool_call')]
        answer=output_path.read_text() if output_path.exists() else ''
        arms.append({'arm':arm,'exit_code':done.returncode,'seconds':time.monotonic()-start,
                     'tool_calls':[{'tool':i.get('tool'),'arguments':i.get('arguments'),'status':i.get('status'),'error':i.get('error')} for i in calls],
                     'serialized_tool_output_bytes':sum(len(json.dumps(i.get('result',{}),ensure_ascii=False).encode()) for i in calls),
                     'forbidden_tool_types':forbidden,'answer':answer})
        report['agent_arms']=arms
        assert done.returncode==0, 'actual agent client failed; inspect retained events/stderr'
        assert not forbidden, 'actual agent used a forbidden non-MCP tool; isolation acceptance failed'
        assert all(i.get('tool') in ('commons_search','commons_read','commons_write') for i in calls)
        if arm=='without_commons':
            assert not calls, 'control must have no Commons connection'
    after=agent.request('objects?kind=note&limit=200')['objects']
    created=[current(o['id']) for o in after if o['id'] not in before]
    report['agent_created_notes']=created
    assert len(created)==1, 'expected exactly one authorized decision note'
    note=created[0]
    authored=note['title']+' '+note['description']+' '+note['body']
    assert all(s.lower() in authored.lower() for s in ('North','Mira Cho','VELA-73')), 'saved decision must use current exact evidence'
    assert 'OLD-19' not in authored and 'Dana Vale' not in authored, 'obsolete sign-off must not become the decision'
    links=agent.request('connections?object_id='+note['id'])['connections']
    targets={c['to_id'] if c['from_id']==note['id'] else c['from_id'] for c in links}
    report['agent_created_connections']=links
    assert source in targets and exception in targets, 'decision must connect actual procedure evidence and qualifying exception'
    calls=arms[1]['tool_calls']
    assert any(c['tool']=='commons_read' and c['arguments'].get('resource')=='correction' and c['arguments'].get('field')=='body' for c in calls), 'actual agent must deliberately read the corrected evidence'
    assert any(c['tool']=='commons_read' and c['arguments'].get('id')==note['id'] for c in calls), 'actual agent must read back its saved decision'
    report['human_review']='pending: inspect both answers, explicit WHAT description, meaningful link explanations, evidence/cost and missing-context limits'
    report['isolation_limits']='Separate fresh cwd/ephemeral sessions, ignored user config/rules and project_doc_max_bytes=0, only Commons configured in treatment; global standing guidance may still load (first control mentioned capture). Shared provider authentication/host process, not an OS security boundary or verified overlay-free adopter trial. CLI events are not a capture-coverage claim.'
    report['checks'].append('actual Codex packaged-MCP connected exception/current long correction/decision links/readback, with missing-context control')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--disposable-lexical', action='store_true')
    mode.add_argument('--disposable-model', action='store_true')
    mode.add_argument('--disposable-agent', action='store_true')
    parser.add_argument('--agent-executable', default='codex')
    parser.add_argument('--mcp-executable', help='Explicit clean-installed current Commons MCP executable for actual-agent acceptance')
    parser.add_argument('--benchmark', action='store_true')
    parser.add_argument('--baseline-binary')
    parser.add_argument('--model-volume', help='Explicit existing pinned-model cache volume, mounted read-only in an isolated model container')
    args = parser.parse_args()
    if args.disposable_agent and not args.mcp_executable:
        parser.error('--disposable-agent requires --mcp-executable')
    os.chdir(ROOT)
    processes = []
    container = None
    model_container = None
    report = {'status': 'failed', 'checks': [], 'queries': [], 'lane': 'actual-agent' if args.disposable_agent else 'lexical-reconciliation' if args.disposable_lexical else 'real-model'}
    directory = tempfile.TemporaryDirectory(prefix='commons-retrieval-')
    work = Path(directory.name)
    result_dir = Path(os.environ.get('COMMONS_TEST_RESULTS', ROOT/'tests/e2e/results'/('retrieval-'+uuid.uuid4().hex)))
    result_dir.mkdir(parents=True, exist_ok=True)
    env = {k:v for k,v in os.environ.items() if not k.startswith(('PG','COMMONS_')) and k != 'DATABASE_URL'}
    def start(command, name):
        log = (result_dir/(name+'.log')).open('ab')
        p = subprocess.Popen(command, env=env, stdout=log, stderr=log, start_new_session=True)
        log.close()
        processes.append(p)
        return p
    try:
        if args.disposable_lexical or args.disposable_model or args.disposable_agent:
            container = 'commons-retrieval-test-'+uuid.uuid4().hex[:10]
            password = secrets.token_hex(18)
            subprocess.run(['docker','run','--detach','--name',container,'--label','commons.test=retrieval',
                '-e','POSTGRES_USER=commons','-e','POSTGRES_DB=commons','-e','POSTGRES_PASSWORD='+password,
                '-p','127.0.0.1::5432','commons-postgres:16.15-vector0.8.1',
                *(['postgres','-c','shared_preload_libraries=auto_explain',
                   '-c','auto_explain.log_analyze=on','-c','auto_explain.log_buffers=on',
                   '-c','auto_explain.log_format=json','-c','auto_explain.log_settings=on'] if args.benchmark else [])],check=True,stdout=subprocess.DEVNULL)
            mapping = subprocess.check_output(['docker','port',container,'5432'],text=True).strip()
            dbport = mapping.rsplit(':',1)[1]
            env['DATABASE_URL'] = f'postgres://commons:{password}@127.0.0.1:{dbport}/commons'
            def sql(statement):
                return subprocess.check_output(['docker','exec',container,'psql','-XAt','-v','ON_ERROR_STOP=1',
                    '-U','commons','-d','commons','-c',statement],text=True,stderr=subprocess.DEVNULL).strip()
            wait(lambda: subprocess.run(['docker','exec',container,'pg_isready','-h','127.0.0.1','-U','commons','-d','commons'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0)
            wait(lambda: sql('SELECT 1') == '1')
            subprocess.run(['target/debug/commons','migrate'],env=env,check=True,stdout=subprocess.DEVNULL)
            # Deliberately unreachable runtime; no fake embeddings or model responses.
            if not args.benchmark and not args.disposable_agent:
                env['COMMONS_OLLAMA_URL'] = f'http://127.0.0.1:{port()}'
            if args.disposable_model:
                if not args.model_volume:
                    raise RuntimeError('--disposable-model requires an explicit --model-volume; no automatic cache selection')
                model_container = 'commons-retrieval-model-'+uuid.uuid4().hex[:10]
                subprocess.run(['docker','run','--detach','--name',model_container,'--label','commons.test=retrieval',
                    '-e','OLLAMA_MODELS=/models','-e','OLLAMA_NO_CLOUD=1','-e','OLLAMA_HOST=0.0.0.0:11434',
                    '-v',args.model_volume+':/model-cache:ro','-p','127.0.0.1::11434',
                    '--entrypoint','/bin/sh','commons-ollama:0.40.5','-c',
                    'mkdir -p /models && cp -a /model-cache/. /models/ && exec /bin/ollama serve'],
                    check=True,stdout=subprocess.DEVNULL)
                def model_mapping():
                    state = subprocess.check_output(['docker','inspect',model_container,'--format','{{.State.Status}}'],text=True).strip()
                    if state == 'exited':
                        raise RuntimeError('isolated model container exited; inspect retained model.log')
                    return subprocess.check_output(['docker','port',model_container,'11434/tcp'],text=True,stderr=subprocess.DEVNULL).strip().rsplit(':',1)[1]
                model_port = wait(model_mapping)
                model_url = 'http://127.0.0.1:'+model_port
                env['COMMONS_OLLAMA_URL'] = model_url
                wait(lambda: json.load(urllib.request.urlopen(model_url+'/api/version'))['version']=='0.40.5')
        else:
            assert '127.0.0.1:55432/commons' in os.environ['DATABASE_URL']
            env.update(DATABASE_URL=os.environ['DATABASE_URL'], PGPASSWORD=os.environ['PGPASSWORD'])
            def sql(statement):
                return subprocess.check_output(['psql','-XAt','-h','127.0.0.1','-p','55432','-U','commons','-d','commons','-c',statement],env=env,text=True).strip()
            binary = os.environ['COMMONS_TEST_OLLAMA_BINARY']
            cache = Path(os.environ['COMMONS_TEST_MODEL_CACHE'])
            model_cache = work/'models'
            shutil.copytree(cache/'manifests', model_cache/'manifests')
            (model_cache/'blobs').symlink_to(cache/'blobs',target_is_directory=True)
            model_url = f'http://127.0.0.1:{port()}'
            env.update(OLLAMA_HOST=model_url, OLLAMA_MODELS=str(model_cache), OLLAMA_NO_CLOUD='1', COMMONS_OLLAMA_URL=model_url)
            model_process = start([binary,'serve'],'model')
            wait(lambda: json.load(urllib.request.urlopen(model_url+'/api/version'))['version']=='0.40.5')
        assert sql('SELECT count(*) FROM users') == '0', 'refuse pre-existing installation'
        base = f'http://127.0.0.1:{port()}'
        env.update(COMMONS_ORIGIN=base, PORT=base.rsplit(':',1)[1], COMMONS_ADMIN_USER='alice',
                   COMMONS_ADMIN_NAME='Alice Synthetic', COMMONS_ADMIN_PASSWORD=secrets.token_hex(24))
        subprocess.run(['target/debug/commons','bootstrap'],env=env,check=True,stdout=subprocess.DEVNULL)
        app_binary=args.baseline_binary if args.benchmark else 'target/debug/commons'
        app_process = start([app_binary],'api')
        admin = HTTP(base)
        wait(lambda: admin.request('health'))
        admin.request('login', {'username':'alice','password':env['COMMONS_ADMIN_PASSWORD']})
        reader_password = secrets.token_hex(24)
        admin.request('users', {'username':'reader','title':'Reader','password':reader_password,'role':'reader'})
        reader = HTTP(base)
        reader.request('login', {'username':'reader','password':reader_password})
        token = admin.request('tokens', {'label':'Retrieval fixture','write_kinds':['note','source','theme']})['token']
        agent = HTTP(base,token)
        def restart_app():
            nonlocal app_process
            os.killpg(app_process.pid,signal.SIGTERM)
            app_process.wait(timeout=15)
            app_process = start([app_binary],'api')
            wait(lambda: agent.request('health'))
        def pause_model():
            if model_container:
                subprocess.run(['docker','pause',model_container],check=True,stdout=subprocess.DEVNULL)
            else:
                os.killpg(model_process.pid,signal.SIGSTOP)
        def resume_model():
            if model_container:
                subprocess.run(['docker','unpause',model_container],check=True,stdout=subprocess.DEVNULL)
            else:
                os.killpg(model_process.pid,signal.SIGCONT)
        if args.disposable_agent:
            agent_journey(agent,report,result_dir,work,args)
        elif args.benchmark:
            if not args.disposable_lexical or not args.baseline_binary:
                raise RuntimeError('benchmark requires --disposable-lexical and an explicit --baseline-binary')
            # Both processes share only this synthetic test database; neither
            # enables an indexing worker, so model progress is not a confounder.
            def candidate_app():
                nonlocal app_binary
                app_binary='target/debug/commons'
                restart_app()
            def log_snapshot():
                return subprocess.check_output(['docker','logs',container],stderr=subprocess.STDOUT,text=True)
            benchmark(agent,admin,sql,{'candidate_app':candidate_app},report,log_snapshot)
        else:
            run_checks(agent, admin, reader, sql, report, not args.disposable_lexical,
                       {'restart_app':restart_app,'pause_model':pause_model,'resume_model':resume_model})
            if args.disposable_lexical:
                # The diagnostic must work with SELECT-only application access,
                # without API credentials, model startup, migration or workers.
                diagnostic_password=secrets.token_hex(24)
                sql(f"CREATE ROLE retrieval_diagnostic LOGIN PASSWORD '{diagnostic_password}'")
                sql('GRANT CONNECT ON DATABASE commons TO retrieval_diagnostic')
                sql('GRANT USAGE ON SCHEMA public TO retrieval_diagnostic')
                sql('GRANT SELECT ON ALL TABLES IN SCHEMA public TO retrieval_diagnostic')
                diagnostic_env=dict(env,DATABASE_URL=f'postgres://retrieval_diagnostic:{diagnostic_password}@127.0.0.1:{dbport}/commons')
                diagnostic=json.loads(subprocess.check_output(['target/debug/commons','diagnose-retrieval'],env=diagnostic_env,text=True,stderr=subprocess.PIPE))
                assert diagnostic['read_only'] and diagnostic['statement_timeout_ms']==20000
                assert len(diagnostic['plans'])==8
                serialized=json.dumps(diagnostic)
                assert 'Frostlane' not in serialized and not re.search(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',serialized)
                assert all(json.dumps(key)+':' not in serialized for key in ['Filter','Output','Relation Name','Query Text','CTE Name'])
                report['diagnostic']=diagnostic
                report['checks'].append('fixed diagnostic works with SELECT-only role and emits only allowlisted metadata')
        report['status'] = 'passed'
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try:
                    p.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid,signal.SIGKILL)
                    p.wait()
        if model_container:
            (result_dir/'model.log').write_bytes(subprocess.check_output(['docker','logs',model_container],stderr=subprocess.STDOUT))
            subprocess.run(['docker','rm','--force',model_container],check=True,stdout=subprocess.DEVNULL)
        if container:
            subprocess.run(['docker','rm','--force',container],check=True,stdout=subprocess.DEVNULL)
        (result_dir/'retrieval.json').write_text(json.dumps(report,indent=2)+'\n')
        directory.cleanup()
        print(json.dumps({'status':report['status'],'lane':report['lane'],'checks':len(report['checks']),'results':str(result_dir)}))


if __name__ == '__main__':
    main()
