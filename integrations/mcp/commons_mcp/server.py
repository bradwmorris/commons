"""Official-SDK stdio adapter; schemas and execution stay in product tools/."""

from __future__ import annotations

import asyncio
import argparse
import json
import sys

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from tools import TOOLS
from tools.client import CommonsError

from . import __version__
from .client import Config, HttpClient


def create_server(client, modules=None):
    modules = TOOLS if modules is None else modules
    definitions = {module.NAME: module for module in modules}
    if len(definitions) != 3:
        raise ValueError("Commons MCP requires three distinct product tools")

    async def list_tools(_context, _params):
        return types.ListToolsResult(tools=[types.Tool(
            name=module.NAME, description=module.DESCRIPTION, inputSchema=module.INPUT_SCHEMA,
            outputSchema=getattr(module, "OUTPUT_SCHEMA", None),
        ) for module in definitions.values()])

    async def call_tool(_context, params):
        module = definitions.get(params.name)
        if module is None:
            return failure(CommonsError("unknown_tool", "Unknown Commons tool", saved=False))
        try:
            result = await module.execute(params.arguments or {}, client)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structuredContent=result,
            )
        except CommonsError as error:
            return failure(error)
        except Exception:
            # Tool/API error integration is tested against the shared tools contract.
            # Unexpected errors never reflect arguments, tokens or response payloads.
            return failure(CommonsError("internal_error", "Commons tool failed; check arguments and server compatibility. "
                                        "For a write reconcile the original key/body; no automatic retry occurred"))

    # Canonical tool modules validate their own published schemas and return the
    # shared structured error contract. Avoid a second SDK validation/error path.
    return Server("commons", version=__version__, on_list_tools=list_tools, on_call_tool=call_tool)


def failure(error):
    result = error.as_dict()
    return types.CallToolResult(isError=True, structuredContent=result,
                               content=[types.TextContent(type="text", text=json.dumps(result))])


async def serve():
    config = Config.from_environment()
    async with HttpClient(config) as client:
        await client.check_compatibility()
        server = create_server(client)
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="Serve Commons product tools over local MCP stdio")
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args()
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
    except CommonsError as error:
        print("Commons MCP connection refused: " + error.message, file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("Commons MCP startup failed; check package, COMMONS_URL and COMMONS_TOKEN", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
