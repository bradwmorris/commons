"""Bounded measurements inside compose_lifecycle's disposable synthetic installation.

Never connect this helper to a real installation. Results are measurements of the
named fixture, not a capacity claim or a production timeout diagnosis.
"""
import json
import math
import statistics
import time
import urllib.request


def measure(client, source_id, artifact_id, retrieve=False):
    routes = {
        'full_object': 'objects/' + source_id,
        'compact_object': 'objects/' + source_id + '?view=compact&limit=20',
        'text_window': 'artifacts/' + artifact_id + '/text?offset=0&limit=24000',
    }
    if retrieve:
        routes['warm_retrieval'] = 'retrieve?q=synthetic&limit=5'
    report = {'fixture': 'compose rich recovery source: >1.1 MiB text, version chain, image and correction',
              'samples_per_route': 8, 'routes': {},
              'limits': ['small synthetic corpus; not representative production scale',
                         'first request is not a guaranteed cold cache',
                         'no database pool-wait, query-plan or process peak-memory attribution']}
    for name, path in routes.items():
        samples, sizes, modes = [], [], set()
        for _ in range(8):
            started = time.perf_counter()
            with client.opener.open(urllib.request.Request(client.base + '/api/' + path)) as response:
                body = response.read()
            samples.append(time.perf_counter() - started)
            sizes.append(len(body))
            payload = json.loads(body)
            if name == 'warm_retrieval':
                modes.add(payload.get('mode'))
        report['routes'][name] = {'first_s': samples[0], 'p50_s': statistics.median(samples),
                                 'p95_s': sorted(samples)[math.ceil(.95 * len(samples))-1],
                                 'max_response_bytes': max(sizes), 'modes': sorted(modes)}
    full = report['routes']['full_object']['max_response_bytes']
    compact = report['routes']['compact_object']['max_response_bytes']
    assert compact < full / 10, 'compact read unexpectedly includes large fixture payloads'
    report['compact_fraction_of_full'] = compact / full
    return report


def idle_scans(sql):
    # Caller supplies SQL access ONLY to the lifecycle-owned disposable database.
    # Let prior fixture/read statistics flush before observing the quiet worker.
    time.sleep(3)
    query = "SELECT seq_scan FROM pg_stat_user_tables WHERE relname='objects'"
    before = int(sql(query))
    started = time.monotonic()
    time.sleep(10)
    scans = int(sql(query)) - before
    elapsed = time.monotonic() - started
    pending = int(sql("SELECT count(*) FROM retrieval_jobs"))
    assert pending == 0, 'idle measurement requires an empty job queue'
    # Original 250ms reconciliation produced ~66 scans/10s on the audited host.
    # Generous bound tolerates startup/statistics timing without allowing that rate.
    assert scans <= 24, f'idle worker performed {scans} Object scans in {elapsed:.1f}s'
    return {'seconds': elapsed, 'object_sequential_scans': scans, 'pending_jobs': pending,
            'maximum_accepted_scans': 24}
