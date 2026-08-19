from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .._json import dump_json_capped
from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_connectors() -> str:
        """List the tenant's Agent Platform connectors and their status.

        Returns one row per connector: name, integration key, scope, managed
        method, whether it's installed, whether it's currently connected, and
        a derived status (not_installed / connected / installed_disconnected).
        The large base64 logo field is stripped to keep the response compact.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get("/api/capabilities/connectors")
        except AgentError as e:
            return e.to_envelope()

        items = (result or {}).get("data", {}).get("list", []) or []
        rows = []
        for c in items:
            enabled = bool(c.get("enabled"))
            connected = bool(c.get("connected"))
            if not enabled:
                status = "not_installed"
            elif connected:
                status = "connected"
            else:
                status = "installed_disconnected"
            rows.append(
                {
                    "name": c.get("name"),
                    "integration": c.get("integration"),
                    "scope": c.get("scope"),
                    "managed": c.get("managed"),
                    "installed": enabled,
                    "connected": connected,
                    "status": status,
                }
            )
        return dump_json_capped({"count": len(rows), "connectors": rows})
