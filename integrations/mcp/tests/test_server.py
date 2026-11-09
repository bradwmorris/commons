import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from threading import Thread

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from tools import TOOLS
from tools.client import CommonsError

from commons_mcp.client import Config, HttpClient
from commons_mcp.server import create_server
import httpx


def fixture_modules():
    async def execute(arguments, client):
        if arguments["value"] == "denied":
            raise CommonsError("http_error", "Commons HTTP 403: Permission denied", status=403, saved=False)
        if arguments["value"] == "crash":
            raise RuntimeError("private internal contents")
        return {"observed": arguments["value"]}

    return tuple(SimpleNamespace(
        NAME=name, DESCRIPTION="Synthetic " + name,
        INPUT_SCHEMA={"type": "object", "properties": {"value": {"type": "string"}},
                      "required": ["value"], "additionalProperties": False},
        execute=execute,
    ) for name in ("commons_search", "commons_read", "commons_write"))


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_dispatch_and_errors_in_both_protocol_eras(self):
        for mode in ("auto", "legacy"):
            with self.subTest(mode=mode):
                modules = fixture_modules()
                async with Client(create_server(None, modules), mode=mode) as client:
                    tools = (await client.list_tools()).tools
                    self.assertEqual([tool.name for tool in tools], [m.NAME for m in modules])
                    self.assertEqual(tools[0].input_schema, modules[0].INPUT_SCHEMA)
                    for module in modules:
                        result = await client.call_tool(module.NAME, {"value": "synthetic"})
                        self.assertFalse(result.is_error)
                        self.assertEqual(result.structured_content, {"observed": "synthetic"})
                    invalid = await client.call_tool("commons_search", {"unexpected": "x"})
                    self.assertTrue(invalid.is_error)
                    denied = await client.call_tool("commons_read", {"value": "denied"})
                    self.assertTrue(denied.is_error)
                    self.assertIn("403", denied.content[0].text)
                    crash = await client.call_tool("commons_write", {"value": "crash"})
                    self.assertTrue(crash.is_error)
                    self.assertNotIn("private internal", crash.content[0].text)

    async def test_real_stdio_subprocess_imports_actual_definitions_and_exits_cleanly(self):
        import json
        class ContractFixture(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"schema_version": 10, "contract_version": "commons/0.1"}).encode())
        api = ThreadingHTTPServer(("127.0.0.1", 0), ContractFixture)
        thread = Thread(target=api.serve_forever, daemon=True)
        thread.start()
        adapter = str(Path(__file__).resolve().parents[1])
        root = str(Path(__file__).resolve().parents[3])
        try:
            with tempfile.TemporaryDirectory() as directory:
                params = StdioServerParameters(command=sys.executable,
                    args=["-B", "-m", "commons_mcp.server"], cwd=directory,
                    env={"PYTHONPATH": os.pathsep.join((root, adapter)),
                         "COMMONS_URL": f"http://127.0.0.1:{api.server_port}", "COMMONS_TOKEN": "synthetic-only"})
                async with Client(params) as client:
                    tools = (await client.list_tools()).tools
                    self.assertEqual([t.name for t in tools], [m.NAME for m in TOOLS])
                    self.assertEqual([t.input_schema for t in tools], [m.INPUT_SCHEMA for m in TOOLS])
                    result = await client.call_tool("commons_read", {"resource": "object"})
                    self.assertTrue(result.is_error)
                    self.assertEqual(result.structured_content["error"]["code"], "invalid_arguments")
                    self.assertIs(result.structured_content["error"]["saved"], False)
        finally:
            api.shutdown()
            api.server_close()
            thread.join()

    async def test_updated_operation_errors_and_correction_unicode_windows(self):
        oid = "00000000-0000-4000-8000-000000000001"
        text = "Alpha 🚢 café 東京 corrected evidence"
        calls = []
        async def handle(request):
            calls.append(request)
            return httpx.Response(200, json={"correction": {"id": oid, "target_id": oid,
                                                           "representation": {"body": text}}})
        async with HttpClient(Config("https://commons.example", "synthetic-secret"),
                              transport=httpx.MockTransport(handle)) as http:
            async with Client(create_server(http)) as client:
                rejected = await client.call_tool("commons_write", {"idempotency_key": "bad-keys", "operations": [{
                    "op": "create_connection", "from_id": oid, "to_id": oid,
                    "expected_from_revision": 1, "expected_to_revision": 1, "kind": "derived_from", "explanation": "Synthetic link"}]})
                self.assertTrue(rejected.is_error)
                self.assertIn("expected_from_revision", rejected.structured_content["error"]["message"])
                self.assertIn("from_revision", rejected.structured_content["error"]["message"])
                self.assertEqual(calls, [])
                result = await client.call_tool("commons_read", {"resource": "correction", "id": oid,
                                                                 "field": "body", "offset": 6, "limit": 8})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["text"], text[6:14])
                self.assertEqual(result.structured_content["field"], "representation.body")
                self.assertEqual(result.structured_content["next_offset"], 14)
                self.assertEqual(calls[-1].url.path, "/api/corrections/" + oid)

    async def test_actual_modules_route_calls_and_preserve_structured_errors(self):
        import json
        oid = "00000000-0000-4000-8000-000000000001"
        for mode in ("auto", "legacy"):
            requests = []

            async def handle(request):
                requests.append(request)
                if request.url.path == "/api/apply":
                    body = json.loads(request.content)
                    if body["operations"][0]["title"] == "Reject":
                        return httpx.Response(422, json={"error": "Not saved: body exceeds 32 KiB; long content belongs in an Artifact"})
                    return httpx.Response(200, json={"validated_only": body["validate_only"], "changes": [{"id": oid, "revision": 1}]})
                return httpx.Response(200, json={"objects": [], "mode": "keyword"})

            async with HttpClient(Config("https://commons.example", "synthetic-user"),
                    transport=httpx.MockTransport(handle)) as http:
                async with Client(create_server(http), mode=mode) as client:
                    tools = (await client.list_tools()).tools
                    self.assertEqual([t.description for t in tools], [m.DESCRIPTION for m in TOOLS])
                    search = await client.call_tool("commons_search", {"query": "synthetic", "scope": "artifacts"})
                    self.assertFalse(search.is_error)
                    self.assertEqual(requests[-1].url.params["scope"], "artifacts")
                    read = await client.call_tool("commons_read", {"resource": "object", "id": oid})
                    self.assertFalse(read.is_error)
                    self.assertEqual(requests[-1].url.path, "/api/objects/" + oid)
                    op = {"op": "create_object", "local_ref": "note", "kind": "note", "title": "Synthetic",
                          "description": "A synthetic note", "fields": {}}
                    for execute in (False, True):
                        written = await client.call_tool("commons_write", {"idempotency_key": "same-key", "operations": [op], "execute": execute})
                        self.assertFalse(written.is_error)
                        self.assertEqual(written.structured_content["validated_only"], not execute)
                        self.assertEqual(json.loads(requests[-1].content)["idempotency_key"], "same-key")
                    rejected = await client.call_tool("commons_write", {"idempotency_key": "reject-key", "operations": [{**op, "title": "Reject"}], "execute": True})
                    self.assertTrue(rejected.is_error)
                    self.assertEqual(rejected.structured_content["error"]["status"], 422)
                    self.assertIs(rejected.structured_content["error"]["saved"], False)
                    self.assertIn("Artifact", rejected.structured_content["error"]["message"])
                    invalid = await client.call_tool("commons_read", {"resource": "object", "id": oid, "offset": 1})
                    self.assertTrue(invalid.is_error)
                    self.assertIn("expected_revision", invalid.structured_content["error"]["message"])

    async def test_actual_write_unknown_response_survives_mcp(self):
        async with HttpClient(Config("https://commons.example", "synthetic-user"),
                transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"broken"))) as http:
            async with Client(create_server(http)) as client:
                result = await client.call_tool("commons_write", {"idempotency_key": "same-key", "execute": True,
                    "operations": [{"op": "create_object", "local_ref": "note", "kind": "note", "title": "Synthetic",
                                    "description": "Synthetic note", "fields": {}}]})
                self.assertTrue(result.is_error)
                self.assertIsNone(result.structured_content["error"]["saved"])

    def test_invalid_startup_never_prints_credentials_or_protocol_noise(self):
        env = {**os.environ, "COMMONS_URL": "http://remote.example", "COMMONS_TOKEN": "synthetic-secret"}
        result = subprocess.run([sys.executable, "-m", "commons_mcp.server"],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("synthetic-secret", result.stderr)

    def test_legacy_api_is_refused_before_any_tool_operation(self):
        calls = []
        class LegacyFixture(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                calls.append(("GET", self.path))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"contract_version":"commons/0.1"}')
        api = ThreadingHTTPServer(("127.0.0.1", 0), LegacyFixture)
        thread = Thread(target=api.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run([sys.executable, "-B", "-m", "commons_mcp.server"], input="",
                env={**os.environ, "COMMONS_URL": f"http://127.0.0.1:{api.server_port}", "COMMONS_TOKEN": "synthetic-secret"},
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertIn("requires schema10", result.stderr)
            self.assertNotIn("synthetic-secret", result.stderr)
            self.assertEqual(calls, [("GET", "/api/contract")])
        finally:
            api.shutdown()
            api.server_close()
            thread.join()
