"""Injected client/error interface shared by all three tools.

MCP owns HTTP transport, endpoint and credentials. Tools never select a destination,
load a token, retry a request or import the MCP server. Paths include /api/.
Client.request returns a decoded JSON object on success and raises CommonsError
otherwise. HTTP validation/conflict/auth denials have saved=False; an interrupted
POST has saved=None (unknown), never an invented failure or automatic retry.
"""
from typing import Any, Protocol


class CommonsError(Exception):
    def __init__(self, code: str, message: str, *, status: int | None = None,
                 saved: bool | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.saved = code, message, status, saved

    def as_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message,
                          "status": self.status, "saved": self.saved}}


class Client(Protocol):
    async def request(self, method: str, path: str, *,
                      params: dict | None = None, json: dict | None = None) -> dict[str, Any]: ...
