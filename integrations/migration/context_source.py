#!/usr/bin/env python3
"""Read an explicit Context sample selection on its host. Never writes to Context."""
import argparse
import base64
import copy
import getpass
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from context_transfer import NoRedirect, check_snapshot, digest, encoded, origin, private

VERSION = "commons.context-selection/1"
FULL_VERSION = "commons.context-selection/2"
RAW_VERSION = "commons.context-rows/1"
# No credentials, sessions, request receipts, vectors or execution fences.
TABLES = frozenset("""objects users tasks memories sources notes themes entities
    real_world_events chats chat_messages artifacts artifact_binary_payloads
    connections entity_categories entity_category_assignments object_events
    evidence_corrections runs task_routines task_routine_runs maintenance_purge_receipts""".split())


def catalog_shape(catalog):
    return {table: {k: v for k, v in entry.items() if k != "row_count"}
            for table, entry in catalog.items()}


class Source:
    def __init__(self, url, token, principal, thread):
        self.origin = origin(url)
        if not token or not principal or not thread:
            raise ValueError("source authentication and attribution required")
        self.headers = {"Authorization": "Bearer " + token,
                        "x-centaur-principal-id": principal, "x-centaur-thread-key": thread}
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def read(self, route, **query):
        if route not in ("tables", "table-rows"):
            raise ValueError("only read-only inventory routes are supported")
        url = self.origin + "/api/v2/maintenance/" + route
        if query:
            url += "?" + urlencode(query)
        try:
            with self.opener.open(Request(url, headers=self.headers), timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"Source HTTP {error.code}; no export published") from None
        except (URLError, TimeoutError):
            raise RuntimeError("Source connection interrupted; no export published") from None


def collect(selection, source):
    """Retain selected rows only; two equal observations are not an atomic snapshot."""
    full = selection["scope"] == "full"
    if (selection["version"], selection["scope"]) not in ((VERSION, "sample"), (FULL_VERSION, "full")):
        raise ValueError("explicit versioned selection required")
    if full:
        check_snapshot(selection["snapshot"])
    for name in ("source_store", "source_revision", "snapshot_id"):
        if not isinstance(selection[name], str) or not selection[name].strip():
            raise ValueError("explicit source and snapshot identity required")
    if selection["origin"] != source.origin:
        raise ValueError("source origin mismatch")
    tables = selection["tables"]
    if not tables or set(tables) - TABLES:
        raise ValueError("unsupported source table; no implicit export")
    if full and any(value != "all" for value in tables.values()):
        raise ValueError("full snapshot requires all rows of each named table")
    if not full and not sum(len(keys) for keys in tables.values()):
        raise ValueError("selection requires explicit row keys")

    def catalog():
        entries = source.read("tables")["data"]
        names = [entry["name"] for entry in entries]
        if len(set(names)) != len(names):
            raise ValueError("duplicate catalog table")
        by_name = {entry["name"]: entry for entry in entries}
        if full:
            excluded = selection["excluded_tables"]
            if (set(tables) != TABLES.intersection(by_name)
                    or set(excluded) != set(by_name) - set(tables)
                    or any(not isinstance(reason, str) or not reason.strip() for reason in excluded.values())):
                raise ValueError("full snapshot requires every supported table and explicit disposition of other tables")
        return {table: by_name[table] for table in sorted(tables)}

    opening = catalog()
    wanted = {}
    for table, keys in tables.items():
        pk = opening[table]["primary_key"]
        if full:
            if not pk:
                raise ValueError("full snapshot requires table primary keys")
            wanted[table] = None
            continue
        if (not pk or not keys or any(not isinstance(key, dict) or set(key) != set(pk)
                                     or any(value is None for value in key.values()) for key in keys)):
            raise ValueError("selection must supply every primary-key column")
        wanted[table] = {encoded(key) for key in keys}
        if len(wanted[table]) != len(keys):
            raise ValueError("duplicate selected key")

    def scan():
        retained, observed_counts = {}, {}
        for table in sorted(tables):
            found, seen, cursors = {}, set(), set()
            query = dict(table=table, limit=200)
            while True:
                page = source.read("table-rows", **query)
                for entry in page["data"]:
                    key = entry["key"]
                    if set(key) != set(opening[table]["primary_key"]):
                        raise ValueError("source key contract changed")
                    if any(entry["row"].get(column) != value for column, value in key.items()):
                        raise ValueError("row identity disagrees with key")
                    key_bytes = encoded(key)
                    if key_bytes in seen:
                        raise ValueError("duplicate source row across pages")
                    seen.add(key_bytes)
                    if full or key_bytes in wanted[table]:
                        if not re.fullmatch(r"[0-9a-f]{64}", entry["row_sha256"]):
                            raise ValueError("invalid source digest")
                        # Retain server digest verbatim. Python/Rust float serialization differs.
                        found[key_bytes] = copy.deepcopy(entry)
                cursor = page["next_cursor"]
                if cursor is None:
                    break
                if not isinstance(cursor, str) or not cursor or cursor in cursors:
                    raise ValueError("invalid or repeated source cursor")
                cursors.add(cursor)
                query["cursor"] = cursor  # Opaque JSONB text, never parse/reformat it.
            if not full and set(found) != wanted[table]:
                raise ValueError("selected row missing; no partial export")
            if full and len(found) != opening[table]["row_count"]:
                raise ValueError("full snapshot table count changed while paging")
            retained[table] = [found[key] for key in sorted(found)]
            observed_counts[table] = len(seen)
        return retained, observed_counts

    first, first_counts = scan()
    second, second_counts = scan()
    closing = catalog()
    if encoded(first) != encoded(second) or catalog_shape(opening) != catalog_shape(closing):
        raise ValueError("selected source rows or table schema changed; reselect before exporting")
    if full and opening != closing:
        raise ValueError("full snapshot catalog counts changed")
    result = dict(version=RAW_VERSION, selection=copy.deepcopy(selection),
                  opening_catalog=opening, closing_catalog=closing, rows=first,
                  observed_counts=[first_counts, second_counts],
                  consistency=("fenced_full_snapshot_two_equal_observations" if full
                               else "two_equal_observations_not_an_atomic_snapshot"))
    return result


def normalize_message(row, sender):
    """Map a current physical message row without changing its original envelope."""
    if sender["object_id"] != row["sender_user_object_id"] or sender["user_kind"] not in ("human", "agent"):
        raise ValueError("message requires its selected historical User; no inferred identity")
    position = row["ingestion_sequence"]
    if type(position) is not int or position < 0:
        raise ValueError("invalid original ingestion sequence")
    if "ingested_sequence" in row and row["ingested_sequence"] != position:
        raise ValueError("contradictory source sequence fields")
    return dict(type="message", message=dict(chat_id=row["chat_object_id"],
        item=dict(id=row["id"], source_item_id=row["provider_message_id"], position=position,
                  kind="message", role=sender["user_kind"], speaker_id=sender["object_id"],
                  body=row["content"], source_created_at=row["source_created_at"]),
        source_ingested_at=row["ingested_at"], original=copy.deepcopy(row)))


def normalize_artifact(row, binary, *, created_by):
    """Preserve physical captures and bytes; refuse unsupported or inconsistent mappings."""
    if row["media_type"] is not None and (not isinstance(row["media_type"], str) or not row["media_type"]):
        raise ValueError("invalid Artifact media_type")
    fields = {key: copy.deepcopy(row[key]) for key in (
        "kind", "title", "uri", "media_type", "language", "capture_outcome", "capture_reason",
        "expected_size_bytes", "semantic_indexing_enabled", "metadata", "supersedes_artifact_id", "captured_at")}
    fields["body"] = row["content"]
    original = dict(artifact=copy.deepcopy(row), binary=None)
    if binary is not None:
        if binary["artifact_id"] != row["id"] or binary["media_type"] != row["media_type"]:
            raise ValueError("binary identity/media type disagrees with Artifact")
        if (row["media_type"] not in ("image/png", "image/jpeg")
                or row["content"] not in (None, "") or row["semantic_indexing_enabled"]
                or row["capture_outcome"] != "complete"):
            raise ValueError("binary Artifact shape unsupported; no text or flags discarded")
        value = binary["bytes"]
        if not isinstance(value, str) or not re.fullmatch(r"\\x(?:[0-9a-fA-F]{2})+", value):
            raise ValueError("unsupported source bytea encoding; PostgreSQL hex required")
        data = bytes.fromhex(value[2:])
        fields["image_base64"] = base64.b64encode(data).decode("ascii")
        # The binary is stored once, in image_base64; every other physical field remains original.
        original["binary"] = {key: copy.deepcopy(value) for key, value in binary.items() if key != "bytes"}
        original["binary_encoding"] = "postgres_hex"
    else:
        if (row["kind"] == "research_visual"
                or (row["media_type"] or "").startswith("image/") and row["capture_outcome"] == "complete"):
            raise ValueError("image payload missing from selection; no reference-only substitution")
        if row["content"] is not None:
            data = row["content"].encode("utf-8")
        else:
            if row["capture_outcome"] == "complete":
                raise ValueError("complete capture lacks original content")
            data = (row["uri"] or "").encode("utf-8")
    if type(row["size_bytes"]) is not int or len(data) != row["size_bytes"] or digest(data) != row["sha256"]:
        raise ValueError("source Artifact byte length/hash mismatch; no partial normalization")
    return dict(type="artifact", id=row["id"], object_id=row["object_id"], created_by=created_by,
                created_at=row["created_at"], sha256=row["sha256"], artifact=fields, provenance=original)


def normalize_run(row, references, *, actor_id):
    """Keep historical execution inert and retain repeated references with explicit evidence."""
    consulted = row["consulted_object_ids"]
    represented = [reference["object_id"] for reference in references]
    if len(set(represented)) != len(represented) or set(represented) != set(consulted):
        raise ValueError("Run reference dispositions must cover every distinct original ID exactly once")
    for reference in references:
        state, receipts = reference["state"], reference.get("purge_evidence", [])
        if state not in ("present", "missing", "deleted"):
            raise ValueError("unknown Run reference disposition")
        if state != "present" and row["status"] not in (
                "completed", "failed", "reversed", "cancelled", "delivered", "accepted", "suppressed"):
            raise ValueError("nonterminal Run has absent references; explicit reconciliation required")
        if state != "deleted" and receipts or state == "deleted" and not receipts:
            raise ValueError("only deleted Run targets require original purge receipts")
        for receipt in receipts:
            if not any(item["table"] == "objects" and item["key"].get("id") == reference["object_id"]
                       and re.fullmatch(r"[0-9a-fA-F]{64}", item["row_sha256"])
                       for item in receipt["rows"]):
                raise ValueError("purge evidence does not identify the original missing Object")
    run = {key: copy.deepcopy(row[key]) for key in (
        "id", "parent_run_id", "kind", "status", "primary_object_id", "input", "trace", "result",
        "error", "consulted_object_ids", "started_at", "completed_at")}
    run.update(source_run_id=row["id"], source_created_at=row["created_at"], actor_id=actor_id,
               review=dict(verdict=row["verdict"], notes=row["review_notes"],
                           reviewed_by=row["reviewed_by"], reviewed_at=row["reviewed_at"]))
    return dict(type="run", run=dict(run=run, chat_object_id=row["chat_object_id"],
                                    references=copy.deepcopy(references), original=copy.deepcopy(row)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", help="owner-only JSON with explicit table/key selection")
    parser.add_argument("output", help="new private directory, outside Git on source host")
    parser.add_argument("--principal", required=True)
    parser.add_argument("--thread", required=True)
    args = parser.parse_args()
    try:
        path = Path(args.selection).expanduser()
        private(path)
        selection = json.loads(path.read_bytes())
        source = Source(selection["origin"], getpass.getpass("Existing maintenance token (not saved): "),
                        args.principal, args.thread)
        result = collect(selection, source)
        root = Path(args.output).expanduser()
        root.mkdir(mode=0o700)  # Never overwrite a prior export or resume changing source rows.
        private(root, directory=True)
        payload = encoded(result)
        with os.fdopen(os.open(root / "rows.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
            output.write(payload)
        print(json.dumps(dict(rows_sha256=digest(payload),
                              selected_counts={table: len(rows) for table, rows in result["rows"].items()},
                              consistency=result["consistency"])))
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, TypeError, OSError):
        print("Source read stopped. Inspect private selection, source contract, permissions and "
              "concurrent changes locally. No destination writes were made.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
