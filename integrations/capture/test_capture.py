"""Outbox contract tests; loopback synthetic receiver, not vendor compatibility proof."""
import contextlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import commons_capture as capture

SOURCE = {"provider": "synthetic", "namespace": "isolated-host", "thread_id": "thread-a"}
CHAT = "d424eaa6-7f3e-4a36-aef4-1f981c4519c6"


@contextlib.contextmanager
def receiver(codes):
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            code = codes.pop(0) if codes else 200
            self.send_response(code)
            if code == 302:
                self.send_header("Location", "/must-not-follow")
            self.end_headers()
            self.wfile.write(json.dumps({"chat_id": CHAT}).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", observed
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def envelope(batch="batch-a", **changes):
    return {"contract_version": capture.CONTRACT, "source": SOURCE, "batch_id": batch,
            "title": "Synthetic conversation", "items": [{"body": "private-synthetic-marker"}],
            **changes}


class OutboxTests(unittest.TestCase):
    def test_off_scope_restart_duplicate_and_disable(self):
        with tempfile.TemporaryDirectory() as root, receiver([]) as (url, observed):
            state = Path(root) / "outbox"
            with capture.database(state) as db:
                capture.initialize(db, url, "installation-a")
                with self.assertRaisesRegex(ValueError, "disabled"):
                    capture.enqueue(db, envelope())
                capture.set_enabled(db, SOURCE, True, "project-a/thread-a from activation")
                capture.enqueue(db, envelope(), "cursor-one")
                self.assertTrue(capture.enqueue(db, envelope())["duplicate"])
                with self.assertRaisesRegex(ValueError, "different content"):
                    capture.enqueue(db, envelope(title="changed"))
                with self.assertRaisesRegex(ValueError, "immutable"):
                    capture.initialize(db, url, "installation-b")
                with self.assertRaisesRegex(ValueError, "disabled"):
                    capture.enqueue(db, envelope(source={**SOURCE, "thread_id": "thread-b"}))
                capture.set_enabled(db, SOURCE, False)
            # Reopen durable state; disabled means queued content is not sent either.
            with capture.database(state) as db:
                self.assertEqual(capture.flush(db, "synthetic-token")["delivered"], 0)
                self.assertEqual(observed, [])
                capture.set_enabled(db, SOURCE, True, "project-a/thread-a from activation")
                self.assertEqual(capture.flush(db, "synthetic-token")["delivered"], 1)
                self.assertEqual(observed, [envelope()])
                self.assertEqual(capture.status(db)["pending_bytes"], 0)
                self.assertNotIn("private-synthetic-marker", json.dumps(capture.status(db)))
                self.assertEqual(capture.enqueue(db, envelope())["state"], "acknowledged")
                self.assertEqual(capture.flush(db, "synthetic-token")["delivered"], 0)

    def test_retry_order_terminal_denial_and_explicit_recovery(self):
        with tempfile.TemporaryDirectory() as root, receiver([503, 403]) as (url, observed):
            with capture.database(Path(root) / "outbox") as db:
                capture.initialize(db, url, "installation-a")
                capture.set_enabled(db, SOURCE, True, "synthetic scope")
                capture.enqueue(db, envelope())
                capture.enqueue(db, envelope("batch-b"))
                first = capture.flush(db, "synthetic-token")
                self.assertEqual(first["batches"][0]["state"], "queued")
                self.assertEqual(len(observed), 1)
                with patch.object(capture.time, "time", return_value=capture.time.time() + 600):
                    second = capture.flush(db, "synthetic-token")
                self.assertEqual(second["batches"][0]["state"], "failed")
                self.assertEqual(len(observed), 2)
                self.assertEqual(capture.flush(db, "replacement-token")["delivered"], 0)
                capture.retry(db, SOURCE, "batch-a")
                self.assertEqual(capture.flush(db, "replacement-token")["delivered"], 2)
                self.assertEqual([x["batch_id"] for x in observed],
                                 ["batch-a", "batch-a", "batch-a", "batch-b"])

    def test_deleted_source_clears_all_pending_copies_and_cannot_reenable(self):
        with tempfile.TemporaryDirectory() as root, receiver([410]) as (url, observed):
            state = Path(root) / "outbox"
            with capture.database(state) as db:
                capture.initialize(db, url, "installation-a")
                capture.set_enabled(db, SOURCE, True, "synthetic scope")
                capture.enqueue(db, envelope())
                capture.enqueue(db, envelope("batch-b"))
                result = capture.flush(db, "synthetic-token")
                self.assertEqual(result["pending_bytes"], 0)
                self.assertTrue(all(x["state"] == "deleted" for x in result["batches"]))
                self.assertEqual(len(observed), 1)
            with capture.database(state) as db:
                with self.assertRaisesRegex(ValueError, "deleted"):
                    capture.set_enabled(db, SOURCE, True, "synthetic scope")
                with self.assertRaisesRegex(ValueError, "deleted"):
                    capture.enqueue(db, envelope("batch-c"))
                self.assertEqual(capture.flush(db, "replacement-token")["delivered"], 0)
                offline = {**SOURCE, "thread_id": "never-uploaded"}
                capture.set_enabled(db, offline, True, "synthetic offline scope")
                capture.enqueue(db, envelope(source=offline))
                capture.set_enabled(db, offline, False)
            result = json.loads(subprocess.check_output([sys.executable, capture.__file__,
                "--state", str(state), "purge-local", "--provider", offline["provider"],
                "--namespace", offline["namespace"], "--thread", offline["thread_id"]], text=True))
            self.assertTrue(result["local_source_discarded"])
            self.assertFalse(result["server_deleted"])
            self.assertEqual(result["pending_bytes"], 0)
            self.assertEqual(len(observed), 1)  # Local purge needs no connection/credential.
            with capture.database(state) as db:
                with self.assertRaisesRegex(ValueError, "deleted"):
                    capture.set_enabled(db, offline, True, "synthetic offline scope")

    def test_limits_history_consent_and_redirect_denial(self):
        with tempfile.TemporaryDirectory() as root, receiver([302]) as (url, observed):
            with capture.database(Path(root) / "outbox") as db:
                capture.initialize(db, url, "installation-a")
                capture.set_enabled(db, SOURCE, True, "synthetic scope")
                with self.assertRaisesRegex(ValueError, "approve-history"):
                    capture.enqueue(db, envelope(history=True))
                with patch.object(capture, "MAX_BYTES", 1):
                    with self.assertRaisesRegex(ValueError, "cursor unchanged"):
                        capture.enqueue(db, envelope(), "must-not-advance")
                self.assertEqual(capture.status(db)["batches"], [])
                capture.enqueue(db, envelope(history=True), history_approved=True)
                result = capture.flush(db, "synthetic-token")
                self.assertEqual(result["batches"][0]["error"], "HTTP 302")
                self.assertEqual(result["batches"][0]["state"], "failed")
                self.assertEqual(len(observed), 1)
                with self.assertRaisesRegex(ValueError, "HTTPS"):
                    capture.origin("http://example.test")


if __name__ == "__main__":
    unittest.main()
