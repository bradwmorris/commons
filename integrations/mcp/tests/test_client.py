import unittest

import httpx

from commons_mcp.client import Config, HttpClient
from tools.client import CommonsError


class ConfigurationTests(unittest.TestCase):
    def test_destination_is_explicit_and_credentials_stay_out_of_repr(self):
        for url in ("http://127.0.0.1:49152", "http://[::1]:49152", "https://commons.example"):
            config = Config(url, "synthetic-secret")
            self.assertNotIn("synthetic-secret", repr(config))
        for url in ("", "http://commons.example", "https://user:pass@example.com",
                    "https://example.com/api", "https://example.com?token=x", "https://example.com:bad",
                    "https://example.com\n.invalid"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Config(url, "synthetic-secret")


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwards_identity_body_key_and_revision_without_mutating(self):
        received = []

        async def handle(request):
            received.append(request)
            return httpx.Response(200, json={"revision": 4})

        body = {"idempotency_key": "synthetic-key", "expected_revision": 3}
        async with HttpClient(Config("https://commons.example", "synthetic-user-a"),
                              transport=httpx.MockTransport(handle)) as client:
            self.assertEqual(await client.request("POST", "/api/apply", json=body), {"revision": 4})
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].headers["authorization"], "Bearer synthetic-user-a")
        self.assertEqual(received[0].content, b'{"idempotency_key":"synthetic-key","expected_revision":3}')
        self.assertEqual(body, {"idempotency_key": "synthetic-key", "expected_revision": 3})

    async def test_explicit_context_overrides_configured_default_without_affecting_identity(self):
        received=[]
        async def handle(request):
            received.append(request);return httpx.Response(200,json={"ok":True})
        async with HttpClient(Config("https://commons.example","synthetic-token","configured-human"),transport=httpx.MockTransport(handle)) as client:
            await client.request("GET","/api/users")
            await client.request("POST","/api/apply",json={"operations":[]})
            await client.request("POST","/api/apply",json={"on_behalf_of":None})
        self.assertNotIn("x-commons-on-behalf-of",received[0].headers)
        self.assertEqual(received[1].headers["x-commons-on-behalf-of"],"configured-human")
        self.assertNotIn("x-commons-on-behalf-of",received[2].headers)
        self.assertTrue(all(r.headers["authorization"]=="Bearer synthetic-token" for r in received))

    async def test_redirect_denial_and_safe_errors_do_not_retry(self):
        for status in (302, 401, 403, 409, 422, 500):
            calls = []

            async def handle(request):
                calls.append(request)
                return httpx.Response(status, headers={"location": "https://elsewhere.example"},
                                      text="sensitive server body synthetic-secret")

            async with HttpClient(Config("https://commons.example", "synthetic-secret"),
                                  transport=httpx.MockTransport(handle)) as client:
                with self.assertRaises(CommonsError) as error:
                    await client.request("POST", "/api/apply", json={"idempotency_key": "same-key"})
            self.assertEqual(len(calls), 1)
            self.assertEqual(error.exception.status, status)
            self.assertIs(error.exception.saved, False if status in (401, 403, 409, 422) else None)
            self.assertNotIn("sensitive", str(error.exception))
            self.assertNotIn("synthetic-secret", str(error.exception))

    async def test_uncertain_write_timeout_is_explicit_and_not_retried(self):
        calls = []

        async def handle(request):
            calls.append(request)
            raise httpx.ReadTimeout("synthetic-secret", request=request)

        async with HttpClient(Config("https://commons.example", "synthetic-secret"),
                              transport=httpx.MockTransport(handle)) as client:
            with self.assertRaisesRegex(CommonsError, "outcome may be unknown") as error:
                await client.request("POST", "/api/apply", json={"idempotency_key": "same-key"})
            self.assertIsNone(error.exception.saved)
        self.assertEqual(len(calls), 1)

    async def test_response_bounds_and_shape(self):
        for payload in (b"x" * 65, b"not json", b"[]"):
            async with HttpClient(Config("https://commons.example", "synthetic-secret"),
                                  transport=httpx.MockTransport(lambda _: httpx.Response(200, content=payload)),
                                  max_response_bytes=64) as client:
                with self.assertRaises(CommonsError):
                    await client.request("GET", "/api/objects")

    async def test_absolute_or_escaping_routes_never_send_credentials(self):
        calls = []
        async with HttpClient(Config("https://commons.example", "synthetic-secret"),
                              transport=httpx.MockTransport(lambda request: calls.append(request))) as client:
            for path in ("https://elsewhere.example/api/objects", "//elsewhere.example/api/objects",
                         "/api/../tokens", "/api/%2e%2e/tokens", "/api/objects?secret=x"):
                with self.assertRaises(CommonsError):
                    await client.request("GET", path)
        self.assertEqual(calls, [])

    async def test_safe_api_validation_is_actionable_but_extra_payloads_and_tokens_are_hidden(self):
        safe = "Not saved: Object uses 501 tokens; limit is 500. Move extended material to an Artifact."
        for payload, expected in (({"error": safe}, safe),
                                  ({"error": "synthetic-secret"}, "Request rejected"),
                                  ({"error": safe, "private": "original payload"}, "Request rejected")):
            async with HttpClient(Config("https://commons.example", "synthetic-secret"),
                    transport=httpx.MockTransport(lambda _: httpx.Response(422, json=payload))) as client:
                with self.assertRaises(CommonsError) as caught:
                    await client.request("POST", "/api/apply", json={})
                self.assertIn(expected, caught.exception.message)
                self.assertNotIn("synthetic-secret", caught.exception.message)
                self.assertIs(caught.exception.saved, False)

    async def test_malformed_or_oversize_successful_post_remains_unknown(self):
        for payload in (b"x" * 65, b"invalid json", b"[]"):
            async with HttpClient(Config("https://commons.example", "synthetic-secret"),
                    transport=httpx.MockTransport(lambda _: httpx.Response(200, content=payload)),
                    max_response_bytes=64) as client:
                with self.assertRaises(CommonsError) as caught:
                    await client.request("POST", "/api/apply", json={})
                self.assertIsNone(caught.exception.saved)

    async def test_maximum_artifact_body_and_json_escaping_fit_transport(self):
        # Maximum supported stored text, with worst-case six-byte JSON escaping.
        body = "\x01" * (16 * 1024 * 1024)
        async with HttpClient(Config("https://commons.example", "synthetic-secret"),
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"artifact": {"body": body}}))) as client:
            result = await client.request("GET", "/api/artifacts/00000000-0000-4000-8000-000000000001")
            self.assertEqual(len(result["artifact"]["body"]), len(body))

    async def test_connection_gate_is_read_only_and_rejects_missing_old_or_future_schema(self):
        for schema in (None, 9, 10, 11, 12, 13):
            calls = []
            async def handle(request):
                calls.append(request)
                return httpx.Response(200, json={"schema_version": schema, "contract_version": "commons/0.1"})
            async with HttpClient(Config("https://commons.example", "synthetic-secret"),
                                  transport=httpx.MockTransport(handle)) as client:
                if schema in (10, 11, 12):
                    self.assertEqual((await client.check_compatibility())["schema_version"], schema)
                else:
                    with self.assertRaises(CommonsError) as caught:
                        await client.check_compatibility()
                    self.assertEqual(caught.exception.code, "incompatible_api")
                    self.assertFalse(caught.exception.saved)
                    self.assertIn("requires schema10", caught.exception.message)
            self.assertEqual([(r.method, r.url.path) for r in calls], [("GET", "/api/contract")])
