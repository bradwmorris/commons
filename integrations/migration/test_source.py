"""Synthetic maintenance HTTP contract; never connects to a live source."""
import base64
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from context_source import Source, VERSION, FULL_VERSION, collect, normalize_artifact, normalize_message, normalize_run


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.mode = "stable"
        self.passes = 0
        self.extra_catalog = []
        self.cursor = '{"category_id": "b&+雪", "entity_object_id": "a"}'
        self.rows = [dict(key=dict(entity_object_id="a", category_id=category), row_sha256=str(i) * 64,
                          row=dict(entity_object_id="a", category_id=category, original="Exact α\r\n"))
                     for i, category in enumerate(("b&+雪", "selected"), 1)]
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if (self.headers.get("Authorization") != "Bearer synthetic-only"
                        or self.headers.get("x-centaur-principal-id") != "synthetic-principal"
                        or self.headers.get("x-centaur-thread-key") != "synthetic-thread"):
                    self.send_error(403)
                    return
                url = urlsplit(self.path)
                if url.path == "/api/v2/maintenance/tables":
                    result = dict(data=[dict(name="entity_category_assignments", row_count=2,
                        primary_key=["entity_object_id", "category_id"], category="application_table")])
                    result["data"].extend(owner.extra_catalog)
                    if owner.mode in ("unrelated", "unrelated-and-selected"):
                        result["data"][0]["row_count"] = 7 if owner.passes else 2
                    if owner.mode == "schema" and owner.passes:
                        result["data"][0]["primary_key"] = ["category_id"]
                elif url.path == "/api/v2/maintenance/table-rows":
                    query = parse_qs(url.query)
                    if query.get("table") != ["entity_category_assignments"] or query.get("limit") != ["200"]:
                        self.send_error(400)
                        return
                    if "cursor" not in query:
                        owner.passes += 1
                        result = dict(data=copy.deepcopy(owner.rows[:1]), next_cursor=owner.cursor)
                    elif query["cursor"] == [owner.cursor]:
                        result = dict(data=copy.deepcopy(owner.rows[1:]), next_cursor=None)
                        if owner.mode in ("change", "unrelated-and-selected") and owner.passes == 2:
                            result["data"][0]["row"]["original"] = "changed without a count change"
                        if owner.mode == "duplicate":
                            result["data"] = copy.deepcopy(owner.rows[:1])
                        if owner.mode == "loop":
                            result = dict(data=[], next_cursor=owner.cursor)
                    else:
                        self.send_error(400)  # Re-encoding JSONB whitespace/Unicode is incorrect.
                        return
                else:
                    self.send_error(404)
                    return
                payload = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever)
        self.worker.start()
        self.source = Source(f"http://127.0.0.1:{self.server.server_port}", "synthetic-only",
                             "synthetic-principal", "synthetic-thread")
        self.selection = dict(version=VERSION, scope="sample", source_store="synthetic:brad",
            source_revision="synthetic-schema", snapshot_id="selected-rows", origin=self.source.origin,
            tables=dict(entity_category_assignments=[self.rows[1]["key"]]))

    def tearDown(self):
        self.server.shutdown()
        self.worker.join()
        self.server.server_close()

    def test_paged_selection_preserves_opaque_cursor_original_and_server_digest(self):
        result = collect(self.selection, self.source)
        self.assertEqual(result["rows"], dict(entity_category_assignments=[self.rows[1]]))
        self.assertEqual(result["opening_catalog"], result["closing_catalog"])
        self.assertEqual(result["consistency"], "two_equal_observations_not_an_atomic_snapshot")
        self.mode, self.passes = "unrelated", 0
        result = collect(self.selection, self.source)
        self.assertEqual(result["rows"], dict(entity_category_assignments=[self.rows[1]]))
        self.assertEqual(result["closing_catalog"]["entity_category_assignments"]["row_count"], 7)
        self.assertEqual(result["observed_counts"], [{"entity_category_assignments":2}]*2)

    def test_changed_rows_missing_selection_duplicate_and_loop_stop_export(self):
        for mode, error in (("change", "changed"), ("duplicate", "duplicate"), ("loop", "cursor"),
                            ("unrelated-and-selected", "changed"), ("schema", "schema changed")):
            with self.subTest(mode=mode):
                self.mode, self.passes = mode, 0
                with self.assertRaisesRegex(ValueError, error):
                    collect(self.selection, self.source)
        self.mode = "stable"
        self.selection["tables"]["entity_category_assignments"][0] = dict(entity_object_id="absent", category_id="absent")
        with self.assertRaisesRegex(ValueError, "missing"):
            collect(self.selection, self.source)
        self.selection["tables"] = {"context_apply_requests": [{"id": "no-credential-receipts"}]}
        with self.assertRaisesRegex(ValueError, "unsupported"):
            collect(self.selection, self.source)

    def test_full_snapshot_requires_fence_all_rows_and_complete_table_dispositions(self):
        self.selection.update(version=FULL_VERSION, scope="full",
            tables={"entity_category_assignments": "all"}, excluded_tables={},
            snapshot=dict(kind="isolated_restore", backup_sha256="a"*64,
                          writer_fence="Synthetic restored DB; all writers disabled"))
        result = collect(self.selection, self.source)
        self.assertEqual(result["rows"]["entity_category_assignments"], self.rows)
        self.assertEqual(result["consistency"], "fenced_full_snapshot_two_equal_observations")
        self.mode, self.passes = "unrelated", 0
        with self.assertRaisesRegex(ValueError, "counts changed"):
            collect(self.selection, self.source)
        self.mode, self.passes = "change", 0
        with self.assertRaisesRegex(ValueError, "rows.*changed"):
            collect(self.selection, self.source)
        self.mode, self.passes = "stable", 0
        self.extra_catalog = [dict(name="accounts", row_count=1, primary_key=["id"])]
        with self.assertRaisesRegex(ValueError, "disposition"):
            collect(self.selection, self.source)
        self.selection["excluded_tables"] = {"accounts": "Credentials remain only in protected original backup"}
        self.assertNotIn("accounts", collect(self.selection, self.source)["rows"])
        self.extra_catalog[0]["name"] = "notes"
        self.selection["excluded_tables"] = {"notes": "Must not exclude canonical content"}
        with self.assertRaisesRegex(ValueError, "every supported table"):
            collect(self.selection, self.source)
        self.selection["snapshot"]["writer_fence"] = ""
        with self.assertRaisesRegex(ValueError, "writer-fence"):
            collect(self.selection, self.source)

    def test_message_normalization_preserves_source_without_inventing_alias_or_sender(self):
        row = dict(id="message", chat_object_id="chat", provider_message_id="provider-id",
            ingestion_sequence=19, content="α\r\n", sender_user_object_id="agent", source_created_at=None,
            ingested_at="2025-03-03T13:02:01+11:00", extra_original={"retained": True})
        sender = dict(object_id="agent", user_kind="agent", identities=[])
        record = normalize_message(row, sender)["message"]
        self.assertEqual(record["original"], row)
        self.assertEqual(record["item"], dict(id="message", source_item_id="provider-id", position=19,
            kind="message", role="agent", speaker_id="agent", body="α\r\n", source_created_at=None))
        self.assertEqual(record["source_ingested_at"], "2025-03-03T13:02:01+11:00")
        self.assertNotIn("ingested_sequence", record["original"])
        with self.assertRaisesRegex(ValueError, "historical User"):
            normalize_message(row, {**sender, "object_id": "another-user"})
        with self.assertRaisesRegex(ValueError, "contradictory"):
            normalize_message({**row, "ingested_sequence": 18}, sender)

    def test_capture_bytes_references_and_unsupported_mappings(self):
        data = "α\r\n".encode()
        row = dict(id="artifact", object_id="source", kind="document", title="Original",
            content="α\r\n", uri="opaque:original", media_type="text/plain", language=None,
            sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), capture_outcome="complete",
            capture_reason=None, expected_size_bytes=None, semantic_indexing_enabled=True,
            metadata={"document_key": "original", "version": 2}, supersedes_artifact_id="older",
            captured_at=None, created_at="2020-02-01T00:00:00Z")
        saved = normalize_artifact(row, None, created_by=None)
        self.assertEqual(saved["artifact"]["body"], "α\r\n")
        self.assertEqual(saved["artifact"]["supersedes_artifact_id"], "older")
        self.assertEqual(saved["artifact"]["metadata"], {"document_key": "original", "version": 2})
        self.assertEqual(saved["provenance"], {"artifact": row, "binary": None})
        unknown = normalize_artifact({**row, "media_type": None}, None, created_by=None)
        self.assertIsNone(unknown["artifact"]["media_type"])
        self.assertEqual(unknown["artifact"]["body"], "α\r\n")
        self.assertIsNone(unknown["provenance"]["artifact"]["media_type"])
        for changed, error in (({**row, "content": "α\n"}, "hash mismatch"),
                               ({**row, "size_bytes": len(data) + 1}, "hash mismatch"),
                               ({**row, "media_type": ""}, "invalid")):
            with self.assertRaisesRegex(ValueError, error):
                normalize_artifact(changed, None, created_by=None)
        # Empty text is authoritative when supplied: never hash the URI instead.
        empty = {**row, "content": "", "size_bytes": 0,
                 "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
        self.assertEqual(normalize_artifact(empty, None, created_by=None)["artifact"]["body"], "")
        for media in ("application/pdf", "image/jpeg"):
            missing = {**row, "content": None, "media_type": media, "capture_outcome": "unavailable",
                "capture_reason": "Original unavailable at source", "size_bytes": len(row["uri"].encode()),
                "sha256": hashlib.sha256(row["uri"].encode()).hexdigest()}
            result = normalize_artifact(missing, None, created_by=None)
            self.assertIsNone(result["artifact"]["body"])
            self.assertEqual(result["artifact"]["uri"], "opaque:original")
            self.assertEqual(result["artifact"]["capture_outcome"], "unavailable")
        # Unit mapping does not decode images; the real-API case tests a valid asymmetric PNG.
        pixels = b"\xff\x00A"
        image = {**row, "kind": "research_visual", "content": None, "media_type": "image/png",
            "semantic_indexing_enabled": False, "size_bytes": len(pixels),
            "sha256": hashlib.sha256(pixels).hexdigest()}
        binary = dict(artifact_id="artifact", bytes="\\xff0041", media_type="image/png", width=2, height=1)
        saved = normalize_artifact(image, binary, created_by=None)
        self.assertEqual(base64.b64decode(saved["artifact"]["image_base64"]), pixels)
        self.assertIsNone(saved["artifact"]["body"])
        self.assertEqual(saved["provenance"]["binary"],
                         dict(artifact_id="artifact", media_type="image/png", width=2, height=1))
        for changed in (None, {**binary, "artifact_id": "other"}, {**binary, "bytes": "ff0041"},
                        {**binary, "bytes": "\\xff004"}, {**binary, "bytes": "\\xff0141"}):
            with self.assertRaises(ValueError):
                normalize_artifact(image, changed, created_by=None)

    def test_run_preserves_repeated_missing_targets_and_requires_real_dispositions(self):
        row = dict(id="run", parent_run_id=None, chat_object_id=None, primary_object_id=None,
            kind="curator", status="completed", actor_type="system", actor_id="historical-only",
            input={"original": True}, trace=[{"attempt": 1}], result={"original": "α\r\n"},
            error=None, consulted_object_ids=["present", "deleted", "missing", "deleted"],
            verdict="mixed", review_notes="Original review", reviewed_by="old-reviewer",
            reviewed_at="2020-02-02T00:00:00Z", created_at="2020-02-01T00:00:00Z",
            started_at=None, completed_at=None, pinned=True, available_at=None)
        receipt = dict(rows=[dict(table="objects", key={"id": "deleted"}, row_sha256="a" * 64)])
        refs = [dict(object_id="present", state="present"),
                dict(object_id="deleted", state="deleted", purge_evidence=[receipt]),
                dict(object_id="missing", state="missing")]
        saved = normalize_run(row, refs, actor_id=None)["run"]
        self.assertEqual(saved["original"], row)
        self.assertEqual(saved["references"], refs)
        self.assertEqual(saved["run"]["consulted_object_ids"], ["present", "deleted", "missing", "deleted"])
        self.assertEqual(saved["run"]["review"]["notes"], "Original review")
        self.assertIsNone(saved["run"]["actor_id"])
        for invalid in (refs[:2], refs + [refs[0]], [refs[0], {**refs[1], "purge_evidence": []}, refs[2]],
                        [refs[0], {**refs[1], "object_id": "wrong"}, refs[2]],
                        [refs[0], {**refs[1], "purge_evidence": [{"rows": []}]}, refs[2]]):
            with self.assertRaises(ValueError):
                normalize_run(row, invalid, actor_id=None)
        with self.assertRaisesRegex(ValueError, "nonterminal"):
            normalize_run({**row, "status": "running"}, refs, actor_id=None)


if __name__ == "__main__":
    unittest.main()
