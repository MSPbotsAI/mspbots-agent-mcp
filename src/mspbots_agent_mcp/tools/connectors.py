from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .._json import dump_json_capped
from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_connectors() -> str:
        """TENANT-WIDE connector inventory. No agent_id — same for every agent.

        Use for tenant-level questions ("what integrations do we have", "is
        ConnectWise connected") or to look up a real `integration` key. For
        what ONE agent uses, call mspbotsagent_get_sop_data_sources.

        One row per connector: id/name/integration/scope/managed, org (false =
        platform, true = org-built), status (not_installed / connected /
        installed_disconnected). Discovery only — no credentials, not a way
        to connect to that server.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get("/api/capabilities/connectors/catalog")
        except AgentError as e:
            return e.to_envelope()

        items = (result or {}).get("data", []) or []
        rows = []
        for c in items:
            enabled = bool(c.get("enabled"))
            raw_connected = c.get("connected")
            if not enabled:
                status = "not_installed"
            elif raw_connected is False:
                status = "installed_disconnected"
            else:
                # True, or not-applicable (undefined, e.g. a non-gateway
                # platform connector with no per-tenant credential to
                # track) — both mean "ready".
                status = "connected"
            rows.append(
                {
                    "id": c.get("id"),
                    "org": c.get("org"),
                    "name": c.get("name"),
                    "integration": c.get("integration"),
                    "scope": c.get("scope"),
                    "managed": c.get("managed"),
                    "installed": enabled,
                    "connected": bool(raw_connected),
                    "status": status,
                }
            )
        return dump_json_capped({"count": len(rows), "connectors": rows})
