#!/usr/bin/env python3
"""Package an explicit private Context row selection; never read or write a server."""
import argparse
import base64
import collections
import copy
import json
import os
from pathlib import Path
import sys

from context_source import RAW_VERSION, catalog_shape, normalize_artifact, normalize_message, normalize_run
from context_transfer import VERSION, FULL_VERSION, LIMIT, digest, encoded, envelope, identity, plan, private

MAPPING_VERSION = "commons.context-mapping/1"
SUBTYPES = dict(user="users", task="tasks", memory="memories", source="sources", note="notes",
                theme="themes", entity="entities", event="real_world_events", chat="chats")
FIELDS = dict(
    user="user_kind identities",
    task="status priority owner_object_id agent_suitable blocked_reason due_at completed_at work_kind github_issue_url brief_markdown",
    memory="happened_at", source="source_kind canonical_uri byline publisher published_at published_at_precision last_accessed_at original_language original_media_type original_artifact_reference current_artifact_id",
    note="content content_format intent source_artifact_id source_locator", theme="slug",
    entity="entity_kind image_url primary_category_id",
    event="starts_at starts_at_precision ends_at ends_at_precision timezone", chat="")


def produce(raw, mapping):
    """Preserve original envelopes, account for every row and require every dependency."""
    selection = raw["selection"]
    if (raw["version"] != RAW_VERSION or selection["scope"] not in ("sample", "full")
            or mapping["version"] != MAPPING_VERSION
            or any(mapping[k] != selection[k] for k in ("source_store", "snapshot_id"))
            or catalog_shape(raw["opening_catalog"]) != catalog_shape(raw["closing_catalog"])):
        raise ValueError("mapping/export identity or observations disagree")
    rows = raw["rows"]
    consumed = set()
    def entries(table):
        return rows.get(table, [])
    def take(table, entry):
        key = (table, encoded(entry["key"]))
        if key in consumed:
            raise ValueError("source row consumed twice")
        consumed.add(key)
        return copy.deepcopy(entry["row"])
    def index(table, key):
        values = {e["row"][key]: e for e in entries(table)}
        if len(values) != len(entries(table)):
            raise ValueError("duplicate source identity")
        return values
    objects = index("objects", "id")
    subtypes = {kind: index(table, "object_id") for kind, table in SUBTYPES.items()}
    artifacts = index("artifacts", "id")
    binaries = index("artifact_binary_payloads", "artifact_id")
    connections = index("connections", "id")
    runs = index("runs", "id")
    routines = index("task_routines", "task_id")
    identity_assets, asset_files = {}, []
    for asset in mapping.get("identity_assets", []):
        uid = asset["user_id"]
        if uid in identity_assets or uid not in subtypes["user"]:
            raise ValueError("identity image requires one explicit mapping per selected historical User")
        profiles = [p for p in subtypes["user"][uid]["row"]["identities"] if p["id"] == asset["identity_id"]]
        data = base64.b64decode(asset["image_base64"], validate=True)
        if (len(profiles) != 1 or not asset["reference"]
                or profiles[0].get("avatar_asset_filename") != asset["reference"]
                or profiles[0].get("avatar_asset_sha256") not in (None, asset["sha256"])
                or asset["media_type"] not in ("image/png", "image/jpeg")
                or not 0 < len(data) <= 20 * 1024 * 1024
                or len(data) != asset["size_bytes"] or digest(data) != asset["sha256"]
                or any(f["reference"] == asset["reference"] for f in mapping["files"] + asset_files)):
            raise ValueError("identity image reference, original digest, bytes or disposition disagree")
        provenance = dict(representation="external_identity_asset", source_identity=copy.deepcopy(profiles[0]),
                          reference=asset["reference"], size_bytes=len(data), represented_at=asset["represented_at"])
        identity_assets[uid] = dict(type="artifact", id=asset["artifact_id"], object_id=uid,
            created_by=None, created_at=asset["represented_at"], sha256=asset["sha256"], provenance=provenance,
            artifact=dict(kind="research_visual", title="Historical profile image", body=None,
                uri=asset["reference"], media_type=asset["media_type"], image_base64=asset["image_base64"],
                capture_outcome="complete", semantic_indexing_enabled=False, captured_at=None,
                metadata=dict(representation="external_identity_asset")))
        asset_files.append(dict(reference=asset["reference"], status="packaged",
            reason="Original identity image represented as an authenticated Artifact; no account grant",
            path="identity-assets/" + asset["artifact_id"], sha256=asset["sha256"], size_bytes=len(data)))
    actors = {}
    for item in mapping["actors"]:
        key = (item["source_type"], item["source_id"])
        if key in actors:
            raise ValueError("duplicate actor mapping")
        actors[key] = item["user_id"]
    def actor(row, prefix):
        # Null is an explicit mapping for an opaque actor, not a guessed account.
        return actors[(row[prefix + "_type"], row[prefix + "_id"])]
    groups = {}
    def add(key, records, deps=()):
        if key in groups:
            raise ValueError("duplicate package group")
        groups[key] = dict(id=key, records=records, depends_on=set(deps) - {key})
    def user_dep(value):
        if value is None or value in mapping["existing_user_ids"]:
            return []
        if value not in subtypes["user"]:
            raise ValueError("mapped actor/owner requires a selected historical User or explicit existing User")
        return ["object:" + value]

    for entry in entries("entity_categories"):
        row = take("entity_categories", entry)
        created, updated = actor(row, "created_by"), actor(row, "updated_by")
        category = {k: row[k] for k in ("id", "slug", "label", "definition", "aliases", "legacy_kind")}
        record = dict(type="category", category={**category, "expected_revision": 0},
                      created_by=created, updated_by=updated, provenance=row,
                      **{k: row[k] for k in ("revision", "created_at", "updated_at", "archived_at")})
        add("category:" + row["id"], [record], user_dep(created) + user_dep(updated))

    for oid, entry in objects.items():
        row = take("objects", entry)
        kind = row["kind"]
        table = SUBTYPES[kind]
        subtype = take(table, subtypes[kind][oid])
        if subtype["object_kind"] != kind:
            raise ValueError("subtype kind does not match Object")
        fields = {key: copy.deepcopy(subtype[key]) for key in FIELDS[kind].split()}
        original = dict(object=row, subtype=subtype)
        created, updated = actor(row, "created_by"), actor(row, "updated_by")
        deps = user_dep(created) + user_dep(updated)
        obj = {key: row[key] for key in ("id", "kind", "title", "description", "revision",
                                        "created_at", "updated_at", "archived_at", "protected", "provenance")}
        obj.update(fields=fields, created_by=created, updated_by=updated, authorship=original)
        if kind == "task":
            destination_owner = mapping["task_owners"][oid]
            if fields["owner_object_id"] is not None and destination_owner != fields["owner_object_id"]:
                raise ValueError("assigned Task owner must retain its original User ID")
            obj["owner_mapping"] = dict(source_owner_id=fields["owner_object_id"], destination_owner_id=destination_owner)
            deps += user_dep(destination_owner)
            if oid in routines:
                original["routine_definition"] = take("task_routines", routines[oid])
                # Retain enabled/next_run_at as inert original evidence, never executable config.
        if kind == "entity":
            assignments = [take("entity_category_assignments", e) for e in entries("entity_category_assignments")
                           if e["row"]["entity_object_id"] == oid]
            original["category_assignments"] = assignments
            fields["category_ids"] = sorted(a["category_id"] for a in assignments)
            if fields["primary_category_id"] not in fields["category_ids"]:
                raise ValueError("Entity primary category assignment missing from selection")
            deps += ["category:" + cid for cid in fields["category_ids"]]
        if kind == "note" and fields["source_artifact_id"] is not None:
            deps.append("object:" + artifacts[fields["source_artifact_id"]]["row"]["object_id"])
        records = [dict(type="object", object=obj)]
        if oid in identity_assets:
            image = identity_assets[oid]
            fields["avatar_asset_url"] = f"/api/artifacts/{image['id']}/content"
            fields["avatar_source"] = "Migrated original identity image; historical profile retained"
            original["identity_asset_mapping"] = dict(artifact_id=image["id"], **image["provenance"])
            records.append(image)
        pending = {aid: e for aid, e in artifacts.items() if e["row"]["object_id"] == oid}
        included = set()
        while pending:
            ready = sorted(aid for aid, e in pending.items()
                           if e["row"]["supersedes_artifact_id"] is None
                           or e["row"]["supersedes_artifact_id"] in included)
            if not ready:
                raise ValueError("Artifact predecessor missing, cyclic or owned by a different Object")
            for aid in ready:
                art = take("artifacts", pending.pop(aid))
                binary = take("artifact_binary_payloads", binaries[aid]) if aid in binaries else None
                creator = mapping["artifact_creators"][aid]
                deps += user_dep(creator)
                records.append(normalize_artifact(art, binary, created_by=creator))
                included.add(aid)
        if kind == "source" and fields["current_artifact_id"] is not None and fields["current_artifact_id"] not in included:
            raise ValueError("Source current capture missing from selection")
        add("object:" + oid, records, deps)
        if kind == "chat":
            chat = copy.deepcopy(mapping["chats"][oid])
            # Source namespace/thread/parent decisions are explicit; do not guess from opaque provider IDs.
            if set(chat) != {"source", "parent_chat_id", "coverage"}:
                raise ValueError("Chat mapping requires source, parent and coverage")
            chat.update(id=oid, original=subtype)
            deps = ["object:" + oid]
            if chat["parent_chat_id"] is not None:
                deps.append("chat:" + chat["parent_chat_id"])
            add("chat:" + oid, [dict(type="chat", chat=chat)], deps)

    for entry in entries("chat_messages"):
        row = take("chat_messages", entry)
        sender = subtypes["user"][row["sender_user_object_id"]]["row"]
        add("message:" + row["id"], [normalize_message(row, sender)],
            ["chat:" + row["chat_object_id"], "object:" + sender["object_id"]])
    for entry in entries("runs"):
        row = take("runs", entry)
        refs = mapping["run_references"][row["id"]]
        mapped = actor(row, "actor")
        deps = user_dep(mapped)
        for reference in refs:
            if reference["state"] == "present":
                deps.append("object:" + reference["object_id"])
            elif reference["object_id"] in objects:
                raise ValueError("absent Run reference is present in selection")
            for receipt in reference.get("purge_evidence", []):
                if not any(e["row"]["receipt"] == receipt for e in entries("maintenance_purge_receipts")):
                    raise ValueError("Run purge receipt not included among original selected rows")
        for key, prefix in (("parent_run_id", "run:"), ("chat_object_id", "chat:"), ("primary_object_id", "object:")):
            if row[key] is not None:
                deps.append(prefix + row[key])
        if row["chat_object_id"] is not None:
            deps += ["message:" + row["input"][k] for k in ("first_message_id", "last_message_id") if row["input"].get(k) is not None]
        add("run:" + row["id"], [normalize_run(row, refs, actor_id=mapped)], deps)
    for entry in entries("task_routine_runs"):
        row = take("task_routine_runs", entry)
        if row["task_id"] not in routines:
            raise ValueError("routine result requires its original definition in selection")
        add("routine_result:" + row["id"], [dict(type="routine_result", original=row)], ["object:" + row["task_id"]])
    for cid, entry in connections.items():
        row = take("connections", entry)
        creator = actor(row, "created_by")
        record = dict(type="connection", from_id=row["source_object_id"], to_id=row["target_object_id"],
                      explanation=row["description"], created_by=creator, provenance=row,
                      **{k: row[k] for k in ("id", "kind", "revision", "created_at", "updated_at", "archived_at", "protected")})
        add("connection:" + cid, [record], user_dep(creator) + ["object:" + record["from_id"], "object:" + record["to_id"]])
    for entry in entries("object_events"):
        row = take("object_events", entry)
        target = row["target_type"]
        if target == "object":
            owner, dependency = row["target_id"], "object:" + row["target_id"]
        elif target == "connection":
            owner = connections[row["target_id"]]["row"]["source_object_id"]
            dependency = "connection:" + row["target_id"]
        elif target == "entity_category":
            owner, dependency = None, "category:" + row["target_id"]
        else:
            raise ValueError("unsupported history target")
        mapped = actor(row, "actor")
        record = dict(type="history", object_id=owner, revision=row["to_revision"], actor_id=mapped,
                      occurred_at=row["created_at"], provenance=row,
                      **{k: row[k] for k in ("id", "target_type", "target_id", "action", "run_id", "before_state", "after_state")})
        deps = [dependency] + user_dep(mapped)
        if row["run_id"] is not None:
            disposition = mapping["history_run_references"][row["id"]]
            if disposition["run_id"] != row["run_id"] or not disposition["reason"].strip():
                raise ValueError("history Run disposition must identify its original reference and reason")
            if disposition["state"] == "included":
                deps.append("run:" + row["run_id"])
            elif (selection["scope"] == "sample" and disposition["state"] == "out_of_sample"
                  and row["run_id"] not in runs):
                record["run_id"] = None
            else:
                raise ValueError("history Run must be included or explicitly out of sample, never invented missing")
            record["provenance"] = dict(row=row, run_reference=copy.deepcopy(disposition))
        add("history:" + row["id"], [record], deps)
    for entry in entries("evidence_corrections"):
        row = take("evidence_corrections", entry)
        mapped = actor(row, "actor")
        record = dict(type="correction", actor_id=mapped, provenance=row,
                      **{k: row[k] for k in ("id", "object_id", "object_revision", "target_type", "target_id",
                                             "representation", "reason", "supersedes_correction_id", "created_at")})
        target = row["target_type"]
        dependency = {"event": "history"}.get(target, target) + ":" + row["target_id"]
        if target == "artifact":
            dependency = "object:" + artifacts[row["target_id"]]["row"]["object_id"]
        deps = ["object:" + row["object_id"], dependency] + user_dep(mapped)
        if row["supersedes_correction_id"] is not None:
            deps.append("correction:" + row["supersedes_correction_id"])
        add("correction:" + row["id"], [record], deps)
    receipts = [take("maintenance_purge_receipts", e) for e in entries("maintenance_purge_receipts")]
    expected = {(table, encoded(e["key"])) for table, values in rows.items() for e in values}
    if consumed != expected or len(expected) != sum(map(len, rows.values())):
        raise ValueError("unmapped, orphaned or duplicate selected rows; no partial package")
    for group in groups.values():
        group["depends_on"] = sorted(group["depends_on"])
    counts = collections.Counter(identity(r)[0] for g in groups.values() for r in g["records"])
    package = dict(version=FULL_VERSION if selection["scope"] == "full" else VERSION,
                   scope=selection["scope"], destination=copy.deepcopy(mapping["destination"]),
                   **{k: selection[k] for k in ("source_store", "source_revision", "snapshot_id")},
                   groups=list(groups.values()), record_counts=dict(counts), files=copy.deepcopy(mapping["files"]) + asset_files,
                   source_evidence=dict(rows_sha256=digest(encoded(raw)), selected_counts={t: len(v) for t, v in rows.items()},
                                        opening_catalog=raw["opening_catalog"], closing_catalog=raw["closing_catalog"],
                                        observed_counts=raw.get("observed_counts"),
                                        consistency=raw["consistency"], purge_receipts=receipts))
    if identity_assets:
        package["source_evidence"]["identity_asset_count"] = len(identity_assets)
    if selection["scope"] == "full":
        package["source_evidence"].update(snapshot=copy.deepcopy(selection["snapshot"]),
                                          excluded_tables=copy.deepcopy(selection["excluded_tables"]))
    ordered = plan(package)[1]  # Validate every original atomic dependency group first.
    if selection["scope"] == "full":
        # Preserve dependency order and each atomic group while avoiding one request
        # per history/message/Run. Checkpoints now acknowledge these bounded batches.
        packed = []
        for group in ordered:
            if packed:
                candidate = {**packed[-1], "records": packed[-1]["records"] + group["records"]}
                if (len(candidate["records"]) <= 50
                        and len(encoded(envelope(package["source_store"], "0"*64, candidate))) <= LIMIT):
                    packed[-1] = candidate
                    continue
            packed.append(dict(id=f"batch:{len(packed):06d}", records=group["records"],
                               depends_on=[packed[-1]["id"]] if packed else []))
        package["groups"] = packed
        plan(package)
    return package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rows")
    parser.add_argument("mapping")
    parser.add_argument("output", help="new private directory outside Git on source host")
    args = parser.parse_args()
    try:
        inputs = []
        for name in (args.rows, args.mapping):
            path = Path(name).expanduser()
            private(path)
            inputs.append(json.loads(path.read_bytes()))
        package = produce(*inputs)
        asset_bytes = {"identity-assets/" + a["artifact_id"]: base64.b64decode(a["image_base64"], validate=True)
                       for a in inputs[1].get("identity_assets", [])}
        if any(f["status"] == "packaged" and f["path"] not in asset_bytes for f in package["files"]):
            raise ValueError("only explicitly mapped identity image bytes can be staged by this producer")
        root = Path(args.output).expanduser()
        root.mkdir(mode=0o700)
        private(root, directory=True)
        if asset_bytes:
            (root / "identity-assets").mkdir(mode=0o700)
            for name, data in asset_bytes.items():
                with os.fdopen(os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                    output.write(data)
        with os.fdopen(os.open(root / "package.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
            output.write(encoded(package))
        print(json.dumps(dict(package_sha256=digest(encoded(package)), record_counts=package["record_counts"])))
    except (ValueError, KeyError, TypeError, OSError):
        print("Packaging stopped. Inspect private mappings, dependencies, original shapes and limits locally; no server writes occurred.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
