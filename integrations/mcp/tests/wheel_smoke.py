"""Clean-wheel stdio/HTTP-contract smoke; not a real Commons API/client pilot.

Run with the Python belonging to the isolated wheel installation, passing the
installed commons-mcp executable. The only HTTP server is this synthetic fixture.
"""

import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from tools import TOOLS


OID = "00000000-0000-4000-8000-000000000001"
REQUESTS = []


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, payload):
        if self.headers.get("Authorization") != "Bearer synthetic-wheel-user":
            self.send_response(401)
            payload = {"error": "credential invalid or expired"}
        else:
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self):
        if self.path == "/api/contract":
            self.respond({"schema_version": 10, "contract_version": "commons/0.1"})
            return
        REQUESTS.append(("GET", self.path, None))
        self.respond({"objects": [{"id": OID, "kind": "note", "title": "Synthetic", "revision": 1}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append(("POST", self.path, body))
        self.respond({"changes": [{"id": OID, "revision": 1}], "validated_only": body["validate_only"]})


async def probe(executable, url):
    with tempfile.TemporaryDirectory(prefix="commons-mcp-wheel-cwd-") as directory:
        params = StdioServerParameters(command=executable, cwd=directory,
            env={"COMMONS_URL": url, "COMMONS_TOKEN": "synthetic-wheel-user", "PYTHONDONTWRITEBYTECODE": "1"})
        for mode in ("auto", "legacy"):
            async with Client(params, mode=mode) as client:
                definitions = (await client.list_tools()).tools
                assert [t.name for t in definitions] == [m.NAME for m in TOOLS]
                assert [t.input_schema for t in definitions] == [m.INPUT_SCHEMA for m in TOOLS]
                assert [t.description for t in definitions] == [m.DESCRIPTION for m in TOOLS]
                assert not (await client.call_tool("commons_search", {"query": "synthetic"})).is_error
                assert not (await client.call_tool("commons_read", {"resource": "object", "id": OID})).is_error
                result = await client.call_tool("commons_write", {"idempotency_key": "wheel-key", "execute": True,
                    "operations": [{"op": "create_object", "local_ref": "note", "kind": "note", "title": "Synthetic",
                                    "description": "A synthetic note", "fields": {}}]})
                assert not result.is_error and result.structured_content["changes"][0]["id"] == OID
                assert REQUESTS[-1][2]["idempotency_key"] == "wheel-key"
                assert REQUESTS[-1][2]["validate_only"] is False
                invalid = await client.call_tool("commons_read", {"resource": "object"})
                assert invalid.is_error and invalid.structured_content["error"]["saved"] is False
    assert len(REQUESTS) == 6


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=lambda p: str(Path(p).resolve()))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(probe(args.executable, f"http://127.0.0.1:{server.server_port}"))
        print("PASS: real packaged tools, clean-cwd stdio, synthetic HTTP, both protocol eras")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
