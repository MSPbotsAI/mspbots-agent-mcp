import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    @mcp.tool()
    async def mspbotsagent_get_connectors() -> str:
        """List the tenant's MSPbots Agent connectors (name, installed, status).

        ✅ Verified live against a real tenant.

        API: GET /apps/mb-platform-agent/api/capabilities/connectors

        Returns one row per connector with:
            name         — display name of the connector
            integration  — connector/integration key (e.g. "connectwise-command")
            scope        — connector scope (e.g. "mspbots")
            managed      — how it is managed (e.g. "gateway")
            installed    — whether the connector is installed/enabled (bool)
            connected    — whether it is currently connected (bool)
            status       — derived: "not_installed" | "connected" |
                           "installed_disconnected"

        The large base64 `logo` field returned by the API is stripped to keep
        the response compact. Credentials come from the request headers
        (X-MSP-Token / X-MSP-Tenant-Id / X-MSP-Host) — no arguments needed.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get("/connectors")
        except AgentError as e:
            return f"Error: {e}"

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
                    "installed": enabled,  # 是否安装
                    "connected": connected,
                    "status": status,  # 状态
                }
            )
        return json.dumps(
            {"count": len(rows), "connectors": rows},
            indent=2,
            ensure_ascii=False,
        )
