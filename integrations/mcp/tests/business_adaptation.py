"""Supported fictional procurement mapping and connector-update acceptance.

Uses existing Entity/Task/Note/Source fields, not arbitrary new schema fields.
Requires a private, explicitly authorised isolated fixture; never owns lifecycle.
"""

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from mcp import Client
from mcp.client.stdio import StdioServerParameters


def check(condition, message):
    if not condition:
        raise AssertionError(message)


@asynccontextmanager
async def connect(executable, fixture):
    with tempfile.TemporaryDirectory(prefix="commons-business-adaptation-") as cwd:
        params = StdioServerParameters(command=executable, cwd=cwd,
            env={"COMMONS_URL": fixture["origin"], "COMMONS_TOKEN": fixture["token"],
                 "PYTHONDONTWRITEBYTECODE": "1"})
        async with Client(params) as client:
            yield client


async def call(client, name, arguments):
    result = await client.call_tool(name, arguments)
    check(not result.is_error, f"{name}: {result.structured_content}")
    return result.structured_content


async def run(fixture, before, after, result):
    suffix = uuid4().hex[:10]
    prefix = "procurement-" + suffix
    task_title = "Fictional procurement acceptance " + suffix
    async with connect(before, fixture) as client:
        initial = (await client.list_tools()).tools
        check([t.name for t in initial] == ["commons_search", "commons_read", "commons_write"], "three tools discovered")
        contract = await call(client, "commons_read", {"resource": "contract"})
        check(contract["schema_version"] == 12, "requires reviewed schema11 fixture")
        identity = contract["identity"]
        check(identity["user_id"] == fixture["user_id"], "explicit synthetic User identity")
        check({"note", "source", "entity", "task"} <= set(identity["write_kinds"]), "fixture scopes must allow all mapped kinds")
        await call(client, "commons_read", {"resource": "schema"})

        async def write(stage, operations):
            arguments = {"idempotency_key": prefix + stage, "operations": operations}
            validated = await call(client, "commons_write", arguments)
            check(validated["validated_only"], "default validates without saving")
            return await call(client, "commons_write", {**arguments, "execute": True})

        created = await write("-create", [
            {"op": "create_object", "local_ref": "supplier", "kind": "entity",
             "title": "Fictional Castor Parts " + suffix,
             "description": "A fictional parts supplier used for procurement adaptation acceptance.",
             "fields": {"entity_kind": "supplier"}},
            {"op": "create_object", "local_ref": "policy", "kind": "source",
             "title": "Fictional supplier policy " + suffix,
             "description": "A fictional purchasing policy supporting the supplier review.",
             "body": "This synthetic workshop checks a supplier before its first order.",
             "fields": {"source_kind": "document", "publisher": "Fictional Harbour Workshop"}},
            {"op": "create_object", "local_ref": "note", "kind": "note",
             "title": "Fictional supplier review rationale " + suffix,
             "description": "A synthetic procurement rationale derived from the fictional policy.",
             "body": "Check the fictional supplier against the policy before ordering.",
             "fields": {"intent": "fact", "content_format": "markdown"}},
            {"op": "create_object", "local_ref": "task", "kind": "task", "title": task_title,
             "description": "A fictional supplier-review task testing the procurement project mapping.",
             "body": "Synthetic acceptance work only; not an operational purchasing instruction.",
             "fields": {"status": "todo", "priority": "medium", "owner_object_id": fixture["user_id"],
                        "due_at": fixture["synthetic_due_at"], "work_kind": "general", "project": "procurement"}},
        ])
        ids = created["local_refs"]
        await write("-evidence-link", [{"op": "create_connection", "from_id": ids["note"],
                    "to_id": ids["policy"], "from_revision": 1, "to_revision": 1, "kind": "derived_from",
                    "explanation": "The fictional procurement rationale follows this supplier-review policy."}])
        await write("-supplier-link", [{"op": "create_connection", "from_id": ids["task"],
                    "to_id": ids["supplier"], "from_revision": 1, "to_revision": 1, "kind": "about",
                    "explanation": "This fictional procurement task reviews the named fictional supplier."}])
        snapshot = {}
        for label, oid in ids.items():
            record = await call(client, "commons_read", {"resource": "object", "id": oid})
            snapshot[label] = record["object"]
            check(record["object"]["metadata"]["created_by"] == fixture["user_id"], "writer attribution preserved")
        check(snapshot["supplier"]["fields"]["entity_kind"] == "supplier", "business vocabulary uses Entity field")
        check(snapshot["task"]["fields"]["project"] == "procurement", "native Task project field")

    # New process using the updated installed connector: no inherited agent context.
    async with connect(after, fixture) as client:
        refreshed = (await client.list_tools()).tools
        check([t.name for t in refreshed] == [t.name for t in initial], "same three tool names after connector update")
        for label, oid in ids.items():
            current = (await call(client, "commons_read", {"resource": "object", "id": oid}))["object"]
            check(current["fields"] == snapshot[label]["fields"] and current["body"] == snapshot[label]["body"],
                  "connector update preserves business record content/fields")
        found = await call(client, "commons_search", {"query": task_title, "kind": "task", "neighbours": 0})
        check(any(o["id"] == ids["task"] for o in found["context"]["objects"]), "adapted Task discoverable after refresh")
        patch = {"op": "update_object", "object_id": ids["task"], "expected_revision": snapshot["task"]["revision"],
                 "description": "An updated fictional supplier-review task retaining its procurement project and owner."}
        await call(client, "commons_write", {"idempotency_key": prefix + "-partial-update", "operations": [patch], "execute": True})
        task = (await call(client, "commons_read", {"resource": "object", "id": ids["task"]}))["object"]
        check(task["fields"] == snapshot["task"]["fields"], "partial update preserves project, owner and synthetic due date")
        invalid = await client.call_tool("commons_write", {"idempotency_key": prefix + "-unsupported-field", "execute": True,
            "operations": [{"op": "update_object", "object_id": ids["supplier"],
                            "expected_revision": snapshot["supplier"]["revision"], "fields": {"supplier_risk": "low"}}]})
        check(invalid.is_error and invalid.structured_content["error"]["saved"] is False, "arbitrary business field rejected without saving")
        supplier = (await call(client, "commons_read", {"resource": "object", "id": ids["supplier"]}))["object"]
        check(supplier["revision"] == snapshot["supplier"]["revision"], "unsupported field has no mutation")
        result.update(status="passed", objects=ids, discovery_before=[t.name for t in initial],
                      discovery_after=[t.name for t in refreshed], search_mode=found["mode"], search_reason=found.get("reason"),
                      mapping={"supplier": "entity.fields.entity_kind", "procurement": "task.fields.project"},
                      configuration_only_mapping=True, schema_extension_tested=False, api_server_upgrade_tested=False,
                      connector_refresh_preserves_records=True, arbitrary_fields_rejected=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--before-executable", required=True)
    parser.add_argument("--after-executable", required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    check(args.fixture.stat().st_mode & 0o077 == 0, "fixture must be owner-only")
    fixture = json.loads(args.fixture.read_text())
    check(fixture.get("synthetic") is True, "explicit synthetic fixture required")
    for key in ("origin", "token", "user_id", "synthetic_due_at"):
        check(bool(fixture.get(key)), "missing fixture field " + key)
    result = {"status": "failed"}
    try:
        asyncio.run(run(fixture, args.before_executable, args.after_executable, result))
    except Exception as error:
        result["failure_type"] = type(error).__name__
        raise
    finally:
        output = json.dumps(result, indent=2)
        check(fixture["token"] not in output, "credentials must not enter result evidence")
        args.results.write_text(output + "\n")
    print("PASS: fictional business mapping, connector refresh, discovery/read/write and explicit extension boundary")


if __name__ == "__main__":
    main()
