"""Packaged MCP acceptance against an explicitly authorised synthetic API fixture.

Reads a private fixture; never prints credentials. Does not own server lifecycle.
Expiry is not simulated by changing the database or the system clock.
"""

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile
from uuid import uuid4

import httpx
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from commons_mcp.client import Config, HttpClient
from commons_mcp.server import create_server


def check(condition, label):
    if not condition:
        raise AssertionError(label)


async def call(client, name, arguments, *, status=None):
    result = await client.call_tool(name, arguments)
    data = result.structured_content
    if status is None:
        check(not result.is_error, f"{name}: {data.get('error') if isinstance(data, dict) else 'missing structured result'}")
    else:
        check(result.is_error and data["error"]["status"] == status, f"{name}: expected HTTP {status}")
        check(data["error"]["saved"] is False, f"{name}: denial must report saved=false")
    return data


@asynccontextmanager
async def session(executable, origin, token):
    with tempfile.TemporaryDirectory(prefix="commons-mcp-api-cwd-") as directory:
        params = StdioServerParameters(command=executable, cwd=directory,
            env={"COMMONS_URL": origin, "COMMONS_TOKEN": token, "PYTHONDONTWRITEBYTECODE": "1"})
        async with Client(params) as client:
            yield client


async def uncertain_write(fixture, executable, results):
    """The API commits, then the transport loses the success representation."""
    write = {"idempotency_key": "mcp-uncertain-" + uuid4().hex, "execute": True,
             "operations": [{"op": "create_object", "local_ref": "note", "kind": "note",
                             "title": "Synthetic uncertain MCP write", "description": "A synthetic note testing lost-response reconciliation.",
                             "fields": {}}]}
    delivered = []
    async with httpx.AsyncClient(trust_env=False) as upstream:
        async def lose_response(request):
            response = await upstream.send(request)
            check(response.status_code == 200, "uncertainty injection needs an actual committed API success")
            delivered.append(response.json())
            return httpx.Response(200, content=b"synthetic interrupted success representation")
        async with HttpClient(Config(fixture["origin"], fixture["A"]["token"]),
                              transport=httpx.MockTransport(lose_response)) as http:
            async with Client(create_server(http)) as client:
                failed = await client.call_tool("commons_write", write)
                check(failed.is_error and failed.structured_content["error"]["saved"] is None,
                      "actual committed request with lost response must stay unknown")
    check(len(delivered) == 1, "uncertain transport must not retry")
    async with session(executable, fixture["origin"], fixture["A"]["token"]) as client:
        receipt = await call(client, "commons_write", write)
        check(receipt == delivered[0], "same-key reconciliation returns original actual receipt")
        check((await call(client, "commons_read", {"resource": "object", "id": receipt["local_refs"]["note"]}))["object"]["revision"] == 1,
              "uncertain write reconciliation creates no second mutation")
    results["passed"].append("actual API commit + injected lost response saved=null + packaged same-key reconciliation")


async def run(fixture, executable, results):
    origin = fixture["origin"]
    check(fixture["schema_version"] == 12, "synthetic fixture must identify schema11")
    results.update(schema_version=12, binary_sha256=fixture["binary_sha256"],
                   embedding_state=fixture["embedding_state"], semantic_checks="not exercised",
                   expiry="not exercised: no supported expiry-control fixture/API",
                   passed=[], objects={})
    run_id = uuid4().hex[:10]
    for user in ("A", "B"):
        account = fixture[user]
        title = f"Synthetic MCP {user} {run_id}"
        op = {"op": "create_object", "local_ref": "note", "kind": "note", "title": title,
              "description": "A synthetic note for independent MCP onboarding acceptance.",
              "body": "One synthetic operation with exact evidence and a supported link.",
              "fields": {"intent": "idea", "content_format": "plain_text"}}
        write = {"idempotency_key": f"mcp-{user}-{run_id}-create", "operations": [op], "execute": True}
        async with session(executable, origin, account["token"]) as client:
            definitions = (await client.list_tools()).tools
            check([t.name for t in definitions] == ["commons_search", "commons_read", "commons_write"], "three product tools")
            identity = await call(client, "commons_read", {"resource": "contract"})
            check(identity["identity"]["user_id"] == account["id"], "per-user authenticated identity")
            created = await call(client, "commons_write", write)
            oid = created["local_refs"]["note"]
            check(await call(client, "commons_write", write) == created, "same key/body returns original receipt")
            await call(client, "commons_write", {**write, "operations": [{**op, "title": title + " changed"}]}, status=409)
            read = await call(client, "commons_read", {"resource": "object", "id": oid})
            check(read["object"]["metadata"]["created_by"] == account["id"], "Object writer attribution")
            history = await call(client, "commons_read", {"resource": "history", "id": read["history"][0]["id"]})
            check(history["history"]["actor_id"] == account["id"], "Change actor attribution")
            found = await call(client, "commons_search", {"query": title, "limit": 5})
            check(found["mode"] == "lexical_only" and found["reason"] == "model_not_configured", "honest lexical degradation")
            check(any(o["id"] == oid for o in found["context"]["objects"]), "search retrieves created Object")
            check(all("body" not in o for o in found["context"]["objects"]), "compact discovery")
            source = await call(client, "commons_write", {"idempotency_key": f"mcp-{user}-{run_id}-source", "execute": True,
                "operations": [{"op": "create_object", "local_ref": "source", "kind": "source", "title": title + " evidence",
                                "description": "A fictional source used for MCP evidence and link checks.",
                                "fields": {"source_kind": "document"}}]})
            sid = source["local_refs"]["source"]
            original = "Synthetic original evidence, preserved exactly.\n" * 1300
            artifact = await call(client, "commons_write", {"idempotency_key": f"mcp-{user}-{run_id}-artifact", "execute": True,
                "operations": [{"op": "save_artifact", "object_id": sid, "expected_revision": 1,
                                "artifact": {"kind": "document", "body": original, "media_type": "text/plain", "capture_outcome": "complete"}}]})
            aid = artifact["changes"][0]["artifact_id"]
            window = await call(client, "commons_read", {"resource": "artifact", "id": aid, "limit": 48000})
            remainder = await call(client, "commons_read", {"resource": "artifact", "id": aid,
                                   "offset": window["next_offset"], "limit": 48000})
            check(window["text"] + remainder["text"] == original, "exact Artifact paging")
            linked = await call(client, "commons_write", {"idempotency_key": f"mcp-{user}-{run_id}-link", "execute": True,
                "operations": [{"op": "create_connection", "from_id": oid, "to_id": sid, "from_revision": 1,
                                "to_revision": 2, "kind": "derived_from", "explanation": "The synthetic note is supported by this exact fictional source."}]})
            cid = linked["changes"][0]["connection_id"]
            connection = await call(client, "commons_read", {"resource": "connection", "id": cid})
            check(connection["connection"]["from_id"] == oid and connection["connection"]["to_id"] == sid, "link endpoints")
            latest = await call(client, "commons_read", {"resource": "object", "id": oid})
            revision = latest["object"]["revision"]
            await call(client, "commons_write", {"idempotency_key": f"mcp-{user}-{run_id}-stale", "execute": True,
                "operations": [{"op": "update_object", "object_id": oid, "expected_revision": 1, "body": "Stale"}]}, status=409)
            rejected = await call(client, "commons_write", {"idempotency_key": f"mcp-{user}-{run_id}-oversize", "execute": True,
                "operations": [{"op": "update_object", "object_id": oid, "expected_revision": revision,
                                "body": "Synthetic long supporting detail. " * 600}]}, status=422)
            check("500" in rejected["error"]["message"] and "Artifact" in rejected["error"]["message"], "actionable packet validation")
            check((await call(client, "commons_read", {"resource": "object", "id": oid}))["object"]["revision"] == revision,
                  "rejected write has no mutation")
            check(await call(client, "commons_write", write) == created, "receipt survives later link revisions")
            await call(client, "commons_write", {"idempotency_key": f"mcp-{user}-{run_id}-scope", "execute": True,
                "operations": [{**op, "kind": "entity", "fields": {}}]}, status=403)
        results["objects"][user] = {"note_id": oid, "title": title, "source_id": sid, "artifact_id": aid, "connection_id": cid}
        results["passed"].append(user + ": discovery/create/search/read/evidence/link/attribution/retry/conflict/scope/packet rejection")
    # A fresh process for the other user sees the shared Object without inherited context.
    async with session(executable, origin, fixture["B"]["token"]) as client:
        check((await call(client, "commons_read", {"resource": "object", "id": results["objects"]["A"]["note_id"]}))["object"]["id"]
              == results["objects"]["A"]["note_id"], "cross-user fresh-session shared read")
    async with session(executable, origin, fixture["reader"]["token"]) as client:
        await call(client, "commons_write", {"idempotency_key": "reader-" + run_id, "operations": [op], "execute": True}, status=403)
    async with session(executable, origin, "synthetic-invalid-token") as client:
        await call(client, "commons_read", {"resource": "contract"}, status=401)
    results["passed"].append("fresh cross-user shared read, reader403 and invalid-token401")
    await uncertain_write(fixture, executable, results)
    # Revoke only the credential explicitly supplied for this disposable test.
    async with session(executable, origin, fixture["revocable"]["token"]) as client:
        await call(client, "commons_read", {"resource": "contract"})
    async with httpx.AsyncClient(base_url=origin, headers={"Origin": origin}, trust_env=False) as admin:
        login = await admin.post("/api/login", json=fixture["admin"])
        check(login.status_code == 200, "synthetic admin login")
        revoked = await admin.post("/api/tokens/" + fixture["revocable"]["credential_id"] + "/revoke", json={})
        check(revoked.status_code == 200, "disposable credential revocation")
    async with session(executable, origin, fixture["revocable"]["token"]) as client:
        await call(client, "commons_read", {"resource": "contract"}, status=401)
    results["passed"].append("actual disposable token revocation and401")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--results", required=True, type=Path)
    args = parser.parse_args()
    check(args.fixture.stat().st_mode & 0o077 == 0, "fixture must be owner-only")
    fixture = json.loads(args.fixture.read_text())
    results = {"status": "failed"}
    try:
        asyncio.run(run(fixture, args.executable, results))
        results["status"] = "passed"
    except Exception as error:
        results["failure"] = str(error)
        raise
    finally:
        text = json.dumps(results, indent=2)
        check(not any(value["token"] in text for value in fixture.values() if isinstance(value, dict) and "token" in value),
              "result must not contain a credential")
        args.results.write_text(text + "\n")
    print("PASS: actual packaged MCP/synthetic candidate API checks; semantic and expiry checks not exercised")


if __name__ == "__main__":
    main()
