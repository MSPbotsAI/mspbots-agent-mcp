import json
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN

# Permissions (7), evaluation (8) and human-in-loop approval (9) all live on the
# SAME agent record. Reads share one GET /api/agents/:id; writes share one
# partial PUT /api/agents/:id. Because writes are partial patches, two concurrent
# PUTs to the same agent can clobber each other — callers must not update the
# same agent in parallel.


async def _fetch_agent_data(client: AgentClient, agent_id: str) -> Any:
    """GET the agent record and return its `data` payload."""
    result = await client.get(f"/api/agents/{agent_id}")
    return (result or {}).get("data", {}) or {}


async def _guard_policy(client: AgentClient, agent_id: str) -> str | None:
    """Return an error string if the agent must not be written back, else None.

    When the platform reports data.policyError=true the stored policy is in a
    bad state; writing on top of it would persist a broken config, so we refuse.
    """
    try:
        data = await _fetch_agent_data(client, agent_id)
    except AgentError as e:
        return f"Error: {e}"
    if data.get("policyError") is True:
        return (
            "Error: agent has policyError=true — refusing to write back to avoid "
            "persisting a broken policy. Resolve the policy error first."
        )
    return None


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    # ----- 7. permissions -------------------------------------------------

    @mcp.tool()
    async def mspbotsagent_get_agent_permissions(agent_id: str) -> str:
        """Read an agent's tool-permission and interrupt settings.

        Args:
            agent_id: The agent to read. Required.

        Returns JSON with:
            permission  — map of tool -> "allow" | "ask" | "deny"
            interruptOn — map of tool -> true, or { allowed_decisions, description }
            owners      — list of { userId, name, email } who own the agent
            tools       — read-only list of tools available to the agent
            policyError — if true, permission/interruptOn are unreliable; do NOT
                          write them back (owners is unaffected)
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            data = await _fetch_agent_data(client, agent_id)
        except AgentError as e:
            return f"Error: {e}"
        projected = {
            "permission": data.get("permission"),
            "interruptOn": data.get("interruptOn"),
            "owners": data.get("owners"),
            "tools": data.get("tools"),
            "policyError": data.get("policyError"),
        }
        return json.dumps(projected, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_upsert_agent_permissions(
        agent_id: str,
        permission: dict | None = None,
        interrupt_on: dict | None = None,
        approval: dict | None = None,
        owners: list[dict] | None = None,
    ) -> str:
        """Update an agent's action-governance settings and/or owners (partial). This tool covers
        the "can it act / must it pause" axis — permission, interrupt_on, approval — plus owners.
        It does NOT set `review` (that is the separate output-quality/self-review axis; use the
        review tool for that).

        The keys are independent — only the ones you pass are changed; omitted keys are left
        untouched. Provide at least one of `permission`, `interrupt_on`, `approval`, or `owners`.
        You may send `owners` alone to just change ownership.

        How the three action-governance keys relate:
          • permission  — per-tool gate, the baseline. {tool -> "allow" | "ask" | "deny"}.
              allow = call freely; deny = never call; ask = pause for a human before calling.
          • interrupt_on — the RICH form of "ask", per-tool. {tool -> true} or
              {tool -> {"allowed_decisions": ["approve","reject",...], "description": "..."}}.
              Use it when a paused tool should constrain what the reviewer may decide, or show a
              note. A tool is either allow/deny (permission) or paused; "paused" lives as
              permission:"ask" normally, or here in interrupt_on when you restrict its decisions.
              permission and interrupt_on for the same tool are two forms of one setting, not a
              conflict.
          • approval — INTENT-level, independent of per-tool ask and NOT keyed by tool name.
              {"rules": [{"name"?, "intent"?, "triggers"?: [regex], "tools"?: [tool],
              "decisions"?: [decision]}]}. A router judges each pending action against `intent`
              (the wording) and `triggers` (regexes that pre-filter which calls reach the rule);
              a match forces approval even if the tool itself is "allow". Send {"rules": []} to
              clear all approval intents. Invalid trigger regex is rejected.

        Args:
          agent_id      The agent to update. Required.
          permission    Map of tool -> "allow" | "ask" | "deny".
                        Example: {"qbo.createInvoice": "ask", "shell.exec": "deny"}
          interrupt_on  Map of tool -> true, or {"allowed_decisions": ["approve","reject"],
                        "description": "..."}.  Example: {"email.send": true}
          approval      {"rules": [ ... ]} as above.  Example:
                        {"rules": [{"intent": "refunds over $500", "triggers": ["refund"],
                        "decisions": ["approve","reject"]}]}
          owners        List of owner objects: {"userId": "user-123", "name": "Kaka",
                        "email": "kaka@x.com"}

        When the agent has policyError=true, permission / interrupt_on / approval are all
        unreliable and writing them is refused (they share one assistant policy); owners-only
        updates are still allowed.

        Do not update the same agent from two calls at once — writes are partial and would
        overwrite each other. Returns the updated agent record as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        if permission is None and interrupt_on is None and approval is None and owners is None:
            return (
                "Error: provide at least one of 'permission', 'interrupt_on', "
                "'approval', or 'owners'"
            )

        body: dict = {}
        if permission is not None:
            body["permission"] = permission
        if interrupt_on is not None:
            body["interruptOn"] = interrupt_on
        if approval is not None:
            body["approval"] = approval
        if owners is not None:
            body["owners"] = owners

        # policyError only makes permission/interruptOn/approval unreliable — guard
        # those, but let an owners-only update through.
        if "permission" in body or "interruptOn" in body or "approval" in body:
            blocked = await _guard_policy(client, agent_id)
            if blocked:
                return blocked

        try:
            result = await client.put(f"/api/agents/{agent_id}", body)
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    # ----- 8. evaluation --------------------------------------------------

    @mcp.tool()
    async def mspbotsagent_get_agent_evaluation(agent_id: str) -> str:
        """Read an agent's self-evaluation (review) configuration.

        Args:
            agent_id: The agent to read. Required.

        Returns JSON with `review` = { rules, max_iterations } or null when no
        self-evaluation is configured.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            data = await _fetch_agent_data(client, agent_id)
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps({"review": data.get("review")}, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_upsert_agent_evaluation(
        agent_id: str,
        rules: list[dict],
        max_iterations: int | None = None,
    ) -> str:
        """Set or update an agent's self-evaluation rules.

        The agent reviews its own output against these rules and may revise it.
        Pass an empty list for `rules` to turn self-evaluation OFF.

        Args:
            agent_id:       The agent to update. Required.
            rules:          List of rule objects. Empty list disables self-eval.
                            Each rule: {
                              "rubric": "The reply cites the source ticket id.",
                              "name": "cite-source",
                              "description": "Apply to any customer-facing reply.",
                              "triggers": ["ticket", "#\\d+"]   # regex/keywords
                            }
            max_iterations: Max self-review passes (e.g. 3). Optional.

        Do not update the same agent from two calls at once.

        Returns the updated agent record as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN

        blocked = await _guard_policy(client, agent_id)
        if blocked:
            return blocked

        review: dict = {"rules": rules}
        if max_iterations is not None:
            review["max_iterations"] = max_iterations
        try:
            result = await client.put(f"/api/agents/{agent_id}", {"review": review})
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    # ----- 9. human-in-loop (approval) ------------------------------------

    @mcp.tool()
    async def mspbotsagent_get_agent_approval(agent_id: str) -> str:
        """Read an agent's human-in-the-loop approval rules.

        Args:
            agent_id: The agent to read. Required.

        Returns JSON with `approval` = list of rule objects (may be empty).
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            data = await _fetch_agent_data(client, agent_id)
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps({"approval": data.get("approval")}, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_upsert_agent_approval(
        agent_id: str,
        rules: list[dict],
    ) -> str:
        """Set or update an agent's human-in-the-loop approval rules.

        Each rule gates a sensitive action so a human must approve/reject before
        the agent proceeds. Pass an empty list to remove all approval gates.

        Args:
            agent_id: The agent to update. Required.
            rules:    List of approval-rule objects. Each rule: {
                        "name": "gate-refunds",
                        "intent": "Issuing a refund over $100",
                        "triggers": ["refund", "\\$\\d{3,}"],   # regex/keywords
                        "tools": ["qbo.createRefund"],
                        "decisions": ["approve", "reject"]
                      }

        Do not update the same agent from two calls at once.

        Returns the updated agent record as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN

        blocked = await _guard_policy(client, agent_id)
        if blocked:
            return blocked

        try:
            result = await client.put(
                f"/api/agents/{agent_id}", {"approval": {"rules": rules}}
            )
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)
