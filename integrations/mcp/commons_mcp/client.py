"""Bounded authenticated HTTP transport; no business-operation policy."""

from __future__ import annotations

import ipaddress
import json as json_module
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from tools.client import CommonsError
from . import __version__


@dataclass(frozen=True)
class Config:
    base_url: str
    token: str = field(repr=False)
    on_behalf_of: str | None = None

    def __post_init__(self):
        try:
            parsed = urlsplit(self.base_url)
            host = parsed.hostname
            port = parsed.port
            loopback = host == "localhost" or bool(host and ipaddress.ip_address(host).is_loopback)
        except ValueError:
            loopback = False
            # DNS hostnames are valid for HTTPS; malformed ports are not.
            try:
                parsed = urlsplit(self.base_url)
                host, port = parsed.hostname, parsed.port
            except ValueError:
                raise ValueError("Invalid Commons API URL") from None
        if (not host or any(c.isspace() for c in self.base_url) or parsed.scheme not in ("https", "http")
                or (parsed.scheme == "http" and not loopback)
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or (port is not None and port == 0)):
            raise ValueError("Use an HTTPS Commons origin; HTTP is allowed only on loopback")
        if not self.token or any(ord(c) < 33 or ord(c) > 126 for c in self.token):
            raise ValueError("A nonblank Commons API token is required")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("COMMONS_URL", ""), os.environ.get("COMMONS_TOKEN", ""), os.environ.get("COMMONS_ON_BEHALF_OF") or None)


class HttpClient:
    """One configured destination and credential; mutations are never retried here."""

    def __init__(self, config: Config, *, transport=None, max_response_bytes=128 * 1024 * 1024):
        self.max_response_bytes = max_response_bytes
        self._token = config.token
        self._on_behalf_of = config.on_behalf_of
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": "Bearer " + config.token, "Accept": "application/json"},
            follow_redirects=False, trust_env=False, timeout=httpx.Timeout(90, connect=10),
            transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._http.aclose()

    async def check_compatibility(self):
        """Read-only connection gate; never try new-schema writes on legacy APIs."""
        contract = await self.request("GET", "/api/contract")
        if contract.get("schema_version") not in (10, 11, 12) or contract.get("contract_version") != "commons/0.1":
            raise CommonsError("incompatible_api", f"Commons MCP {__version__} requires schema10/11/12 and commons/0.1. "
                               "Configured API is incompatible; no tool operation was run. "
                               "Use the matching reviewed API/package candidate", saved=False)
        return contract

    async def request(self, method, path, *, params=None, json=None):
        # The imported product modules select routes. Never accept another origin.
        if (method not in ("GET", "POST") or not isinstance(path, str)
                or not path.startswith("/api/") or any(c in path for c in ("?", "#", "\\"))
                or any(part in (".", "..") for part in path.split("/"))
                or "%" in path or any(ord(c) < 32 for c in path)):
            raise CommonsError("invalid_route", "Invalid Commons API route", saved=False)
        saved = None if method == "POST" else False
        try:
            async with self._http.stream(method, path, params=params, json=json, headers={"X-Commons-On-Behalf-Of": self._on_behalf_of} if method == "POST" and self._on_behalf_of and not (isinstance(json, dict) and "on_behalf_of" in json) else None) as response:
                if not 200 <= response.status_code < 300:
                    guidance = {
                        401: "Credential invalid, expired or revoked; renew it",
                        403: "Permission denied; check the credential scope",
                        409: "Conflict; read current revision or reconcile the original key/body",
                        422: "Request rejected; check the live schema and arguments",
                    }.get(response.status_code, "Request failed; check Commons availability and configuration")
                    # Only the bounded public JSON error field from known API
                    # denials is safe to expose; never reflect arbitrary bodies.
                    denial = response.status_code in (400, 401, 403, 404, 409, 410, 413, 422, 429)
                    if denial:
                        saved = False
                        public = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(public) + len(chunk) > 8192:
                                break
                            public.extend(chunk)
                        try:
                            error = json_module.loads(public)
                            message = error.get("error") if isinstance(error, dict) else None
                            if (set(error) == {"error"} and isinstance(message, str)
                                    and 0 < len(message) <= 1024
                                    and not any(ord(c) < 32 for c in message)
                                    and self._token not in message):
                                guidance = message
                        except (ValueError, TypeError, UnicodeError):
                            pass
                    raise CommonsError("http_error", f"Commons HTTP {response.status_code}: {guidance}",
                                       status=response.status_code, saved=False if denial else saved)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self.max_response_bytes:
                        raise CommonsError("response_too_large", "Commons response exceeds transport limit; "
                                           "request smaller pages. For a write, reconcile the original key/body",
                                           saved=saved)
                    content.extend(chunk)
                try:
                    result = json_module.loads(content)
                except (ValueError, UnicodeError):
                    raise CommonsError("invalid_response", "Commons returned invalid JSON; "
                                       "for a write reconcile the original key/body", saved=saved) from None
                if not isinstance(result, dict):
                    raise CommonsError("invalid_response", "Commons returned an unexpected response shape; "
                                       "for a write reconcile the original key/body", saved=saved)
                return result
        except httpx.RequestError:
            raise CommonsError("transport_error", "Commons unavailable or timed out; write outcome may be unknown. "
                               "Reconcile and reuse the original key/body; no automatic retry occurred",
                               saved=saved) from None
