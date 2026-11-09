"""Boundary tests; HTTP integration and real-agent checks are separate evidence."""
import copy
import unittest
from uuid import uuid4
from tools import TOOLS, commons_read as read, commons_search as search, commons_write as write
from tools.client import CommonsError
from tools.schema import validate

OID = str(uuid4())
OTHER = str(uuid4())


class Client:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result if result is not None else {"ok": True}
        self.error = error

    async def request(self, method, path, *, params=None, json=None):
        self.calls.append((method, path, copy.deepcopy(params), copy.deepcopy(json)))
        if self.error:
            raise self.error
        return self.result


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_exactly_three_transport_independent_modules(self):
        self.assertEqual([m.NAME for m in TOOLS], ["commons_search", "commons_read", "commons_write"])
        for module in TOOLS:
            self.assertEqual(module.INPUT_SCHEMA["additionalProperties"], False)
            self.assertTrue(module.DESCRIPTION)

    async def test_filtered_extended_discovery_maps_to_same_server_query(self):
        c = Client()
        await search.execute({"query": "cold parcels", "kind": "source", "scope": "artifacts",
                              "object_id": OID, "limit": 2, "neighbours": 1}, c)
        self.assertEqual(c.calls, [("GET", "/api/retrieve", {"q": "cold parcels", "kind": "source",
            "scope": "artifacts", "object_id": OID, "limit": 2, "neighbours": 1}, None)])

    async def test_invalid_search_is_rejected_before_http(self):
        c = Client()
        for args in ({"query": " "}, {"query": "東京" * 100}, {"query": "x", "kind": "memory"},
                     {"query": "x", "limit": True}, {"query": "x", "url": "https://elsewhere"}):
            with self.assertRaises(CommonsError):
                await search.execute(args, c)
        self.assertEqual(c.calls, [])

    async def test_object_read_and_revision_checked_continuation(self):
        c = Client()
        await read.execute({"resource": "object", "id": OID, "offset": 20, "expected_revision": 3}, c)
        self.assertEqual(c.calls[0][2], {"limit": 20, "offset": 20, "expected_revision": 3})
        with self.assertRaises(CommonsError):
            await read.execute({"resource": "object", "id": OID, "offset": 20}, c)
        self.assertEqual(len(c.calls), 1)

    async def test_connection_filter_and_explanation_search(self):
        c = Client()
        await read.execute({"resource": "connections", "object_id": OID, "query": "supports", "limit": 5}, c)
        self.assertEqual(c.calls[0][:3], ("GET", "/api/connections", {"limit": 5, "offset": 0, "q": "supports", "object_id": OID}))

    async def test_related_endpoint_summaries_preserve_owning_object_and_typed_reads(self):
        own = {"id": OID, "body": "Complete owning body", "fields": {"intent": "fact"}}
        link = {"id": OTHER, "kind": "derived_from", "explanation": "Supported by this evidence.", "revision": 4,
                "from_object": {**own, "title": "A Note", "endpoint_type": "object", "metadata": {"large": "omitted"}},
                "to_object": {"id": OTHER, "title": "Original evidence", "endpoint_type": "artifact", "kind": "artifact", "object_id": OID}}
        payload = {"object": own, "connections": [link], "page": {"next_offset": 20}}
        c = Client(copy.deepcopy(payload))
        result = await read.execute({"resource": "object", "id": OID}, c)
        self.assertEqual(result["object"], own)
        self.assertEqual(result["page"], payload["page"])
        projected = result["connections"][0]
        self.assertEqual(projected["explanation"], link["explanation"])
        self.assertEqual(projected["revision"], 4)
        self.assertNotIn("body", projected["from_object"])
        self.assertNotIn("fields", projected["from_object"])
        self.assertNotIn("metadata", projected["from_object"])
        self.assertEqual(projected["to_object"]["read"], {"resource": "artifact", "id": OTHER})
        self.assertEqual(c.result, payload)
        for resource in ("user", "trace"):
            c = Client({"connection": {"to_object": {"id": OTHER, "endpoint_type": resource, "metadata": {"not": "expanded"}}}})
            r = await read.execute({"resource": "connection", "id": OID}, c)
            self.assertEqual(r["connection"]["to_object"]["read"], {"resource": resource, "id": OTHER})

    async def test_bad_enum_and_limit_return_choices_without_an_http_call(self):
        c = Client()
        with self.assertRaises(CommonsError) as caught:
            await write.execute({"idempotency_key": "intent", "operations": [{"op": "create_object", "local_ref": "note", "kind": "note",
                "title": "A decision", "description": "A note recording a decision.", "fields": {"intent": "decision"}}]}, c)
        self.assertIn('accepted: "idea", "excerpt", "fact", "insight", "question"', caught.exception.message)
        with self.assertRaises(CommonsError) as caught:
            await search.execute({"query": "test", "limit": 20}, c)
        self.assertIn("maximum=10", caught.exception.message)
        self.assertEqual(c.calls, [])

    async def test_evidence_window_and_binary_metadata_do_not_expand_body(self):
        c = Client({"artifact": {"id": OID, "body": "private long original", "bytes": "binary", "metadata": {"large": "content"}}})
        result = await read.execute({"resource": "artifact_metadata", "id": OID}, c)
        self.assertNotIn("body", result["artifact"])
        self.assertNotIn("bytes", result["artifact"])
        self.assertNotIn("metadata", result["artifact"])
        await read.execute({"resource": "artifact", "id": OID, "offset": 20, "limit": 1000}, c)
        self.assertEqual(c.calls[-1][1:3], (f"/api/artifacts/{OID}/text", {"offset": 20, "limit": 1000}))

    async def test_corrected_unicode_window_addresses_the_named_representation(self):
        text = "Préface 東京 🌿. Corrected shelter."
        c = Client({"correction": {"id": OTHER, "target_id": OID, "representation": {"body": text, "other": "not returned"}}})
        result = await read.execute({"resource": "correction", "id": OTHER, "field": "body", "offset": 8, "limit": 6}, c)
        self.assertEqual(result["text"], text[8:14])
        self.assertEqual(result["field"], "representation.body")
        self.assertEqual(result["next_offset"], 14)
        self.assertEqual(c.calls[0][1], f"/api/corrections/{OTHER}")
        self.assertIsNone(c.calls[0][2])
        self.assertNotIn("representation", result)
        with self.assertRaises(CommonsError):
            await read.execute({"resource": "correction", "id": OTHER, "field": "text"}, c)

    async def test_browse_returns_selectable_objects_without_agent_filter(self):
        c = Client({"objects": [{"id": OID, "title": "Record", "body": "long", "fields": {"large": "body"}, "provenance": {"secret": "x"}}], "next_offset": 5})
        result = await read.execute({"resource": "objects", "kind": "note"}, c)
        self.assertEqual(result["objects"], [{"id": OID, "title": "Record", "read": f"/api/objects/{OID}"}])
        self.assertEqual(result["next_offset"], 5)

    async def test_resource_specific_arguments_never_silently_ignored(self):
        c = Client()
        for args in ({"resource": "schema", "id": OID}, {"resource": "object"},
                     {"resource": "users", "query": "secret"}, {"resource": "object", "id": OID, "limit": 201}):
            with self.assertRaises(CommonsError):
                await read.execute(args, c)
        self.assertEqual(c.calls, [])

    async def test_identity_schema_history_and_trace_have_explicit_routes(self):
        c = Client()
        for resource, path in [("user", f"/api/users/{OID}"), ("schema", "/api/schema"),
                               ("contract", "/api/contract"), ("trace_history", f"/api/traces/{OID}/history")]:
            await read.execute({"resource": resource, **({"id": OID} if resource in ("user", "trace_history") else {})}, c)
            self.assertEqual(c.calls[-1][1], path)

    async def test_validate_default_and_execute_preserve_payload(self):
        c = Client()
        args = {"idempotency_key": "retry-key", "operations": [{"op": "update_object", "object_id": OID,
                "expected_revision": 4, "fields": {"blocked_reason": None}}]}
        original = copy.deepcopy(args)
        await write.execute(args, c)
        await write.execute({**args, "execute": True}, c)
        self.assertTrue(c.calls[0][3]["validate_only"])
        self.assertFalse(c.calls[1][3]["validate_only"])
        self.assertEqual(c.calls[1][3]["operations"], original["operations"])
        self.assertEqual(args, original)

    async def test_human_context_preserves_explicit_unknown_and_is_not_assignment(self):
        args={"idempotency_key":"context-key","operations":[{"op":"update_object","object_id":OID,"expected_revision":1,"body":"A contribution."}]}
        for human in (OTHER,None):
            c=Client();await write.execute({**args,"on_behalf_of":human},c)
            self.assertIn("on_behalf_of",c.calls[0][3]);self.assertEqual(c.calls[0][3]["on_behalf_of"],human)
        c=Client();await write.execute(args,c);self.assertNotIn("on_behalf_of",c.calls[0][3])

    async def test_conflict_or_unknown_save_never_retried(self):
        args = {"idempotency_key": "keep-me", "execute": True,
                "operations": [{"op": "update_object", "object_id": OID, "expected_revision": 4, "body": "new"}]}
        for error in (CommonsError("conflict", "reload", status=409, saved=False),
                      CommonsError("transport_error", "connection lost", saved=None)):
            c = Client(error=error)
            with self.assertRaises(CommonsError) as caught:
                await write.execute(args, c)
            self.assertIs(caught.exception, error)
            self.assertEqual(len(c.calls), 1)
            self.assertEqual(c.calls[0][3]["idempotency_key"], "keep-me")
            self.assertEqual(error.as_dict()["error"]["saved"], error.saved)

    async def test_connection_has_one_typed_endpoint_and_revisions(self):
        c = Client()
        link = {"op": "create_connection", "from_id": OID, "to_artifact_id": OTHER,
                "from_revision": 3, "kind": "derived_from", "explanation": "The Note states a conclusion supported by this source."}
        await write.execute({"idempotency_key": "link", "operations": [link]}, c)
        self.assertEqual(c.calls[0][3]["operations"], [link])
        for bad in ({**link, "from_user_id": OTHER}, {k: v for k, v in link.items() if k != "from_revision"}):
            with self.assertRaises(CommonsError):
                await write.execute({"idempotency_key": "bad", "operations": [bad]}, c)
        self.assertEqual(len(c.calls), 1)

    async def test_wrong_endpoint_revision_names_explain_exact_supported_arguments(self):
        c = Client()
        bad = {"op": "create_connection", "from_id": OID, "to_id": OTHER,
               "expected_from_revision": 3, "expected_to_revision": 2,
               "kind": "related_to", "explanation": "A supported relationship."}
        with self.assertRaises(CommonsError) as caught:
            await write.execute({"idempotency_key": "bad-revisions", "execute": True, "operations": [bad]}, c)
        message = caught.exception.message
        self.assertIn("expected_from_revision", message)
        self.assertIn("expected_to_revision", message)
        self.assertIn("Endpoint revisions are from_revision and to_revision", message)
        self.assertIn("create_connection", message)
        self.assertFalse(caught.exception.saved)
        self.assertEqual(c.calls, [])
        for name in ("update_connection", "delete_connection"):
            op = {"op": name, "connection_id": OID, "expected_revision": 1, "expected_from_revision": 3}
            if name == "update_connection":
                op["explanation"] = "Updated supported reason."
            with self.assertRaises(CommonsError) as caught:
                await write.execute({"idempotency_key": "bad", "operations": [op]}, c)
            self.assertIn("Connection's own revision", caught.exception.message)

    async def test_no_arbitrary_tables_or_server_attribution(self):
        c = Client()
        for operation in ({"op": "create_object", "local_ref": "x", "kind": "user", "title": "x", "description": "x", "fields": {}},
                          {"op": "update_object", "object_id": OID, "expected_revision": 1, "metadata": {}},
                          {"op": "set_lifecycle", "object_id": OID, "expected_revision": 1, "archived": True}):
            with self.assertRaises(CommonsError):
                await write.execute({"idempotency_key": "bad", "operations": [operation]}, c)
        self.assertEqual(c.calls, [])

    async def test_all_write_operation_shapes_are_discoverable(self):
        names = {s["properties"]["op"]["const"] for s in write.INPUT_SCHEMA["properties"]["operations"]["items"]["oneOf"]}
        self.assertEqual(names, {"create_object", "ensure_task", "update_object", "append_artifact", "save_artifact",
                                "create_connection", "update_connection", "delete_connection", "delete_object", "correct_evidence"})
        validate({"idempotency_key": "x", "operations": [{"op": "create_object", "local_ref": "new", "kind": "note",
            "title": "A decision", "description": "A decision about the delivery route.", "body": "Use the east entrance.", "fields": {"intent": "fact"}}]}, write.INPUT_SCHEMA)


if __name__ == "__main__":
    unittest.main()
