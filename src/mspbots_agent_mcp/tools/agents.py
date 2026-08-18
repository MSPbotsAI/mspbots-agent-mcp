import json
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN

# Permissions (7), evaluation (8) and human-in-loop approval (9) all live on the
# SAME agent record. Reads share one GET /api/agents/:id; writes share one
# partial PUT /api/agents/:id. Because writes are partial patches, two concurrent
# PUTs to the same agent can clobber each other — callers must not update the
# same agent in parallel.
#
# These settings govern the agent's actual runtime behavior (what it is allowed
# to do, when it must pause, when a human must approve). That's distinct from
# the SOP-author tools (sop_author.py), which manage a documentation/planning
# artifact — the agent's written standard operating procedure — rather than
# enforced runtime policy.


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
    async def mspbotsagent_get_agent_permissions(
        agent_id: Annotated[str, Field(description="The agent to read. Required.")],
    ) -> str:
        """Read an agent's tool-permission and interrupt settings.

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
        agent_id: Annotated[str, Field(description="The agent to update. Required.")],
        permission: Annotated[
            dict | None,
            Field(
                description=(
                    'Map of tool -> "allow" | "ask" | "deny". Example: '
                    '{"qbo.createInvoice": "ask", "shell.exec": "deny"}'
                )
            ),
        ] = None,
        interrupt_on: Annotated[
            dict | None,
            Field(
                description=(
                    "Map of tool -> true, or "
                    '{"allowed_decisions": ["approve","reject"], "description": "..."}. '
                    'Example: {"email.send": true}'
                )
            ),
        ] = None,
        owners: Annotated[
            list[dict] | None,
            Field(
                description=(
                    "List of owner objects who own the agent, each: "
                    '{"userId": "user-123", "name": "Kaka", "email": "kaka@x.com"}'
                )
            ),
        ] = None,
    ) -> str:
        """Update an agent's permissions, interrupt settings, and/or owners (partial).

        The three keys are independent — only the ones you pass are changed;
        omitted keys are left untouched. Provide at least one of `permission`,
        `interrupt_on`, or `owners`. You may send `owners` on its own to just
        change ownership.

        When the agent has policyError=true, permission/interrupt_on are unreliable
        and writing them is refused; owners-only updates are still allowed.

        Do not update the same agent from two calls at once — writes are partial
        and would overwrite each other.

        Returns the updated agent record as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        if permission is None and interrupt_on is None and owners is None:
            return "Error: provide at least one of 'permission', 'interrupt_on', or 'owners'"

        body: dict = {}
        if permission is not None:
            body["permission"] = permission
        if interrupt_on is not None:
            body["interruptOn"] = interrupt_on
        if owners is not None:
            body["owners"] = owners

        # policyError only makes permission/interruptOn unreliable — guard those,
        # but let an owners-only update through.
        if "permission" in body or "interruptOn" in body:
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
    async def mspbotsagent_get_agent_evaluation(
        agent_id: Annotated[str, Field(description="The agent to read. Required.")],
    ) -> str:
        """Read an agent's self-evaluation (review) configuration.

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
        agent_id: Annotated[str, Field(description="The agent to update. Required.")],
        rules: Annotated[
            list[dict],
            Field(
                description=(
                    "List of rule objects. Empty list disables self-eval. "
                    "Each rule: "
                    '{ "rubric": "The reply cites the source ticket id.", '
                    '"name": "cite-source", '
                    '"description": "Apply to any customer-facing reply.", '
                    '"triggers": ["ticket", "#\\d+"] }   # regex/keywords'
                )
            ),
        ],
        max_iterations: Annotated[
            int | None, Field(description="Max self-review passes (e.g. 3). Optional.")
        ] = None,
    ) -> str:
        """Set or update an agent's self-evaluation rules.

        The agent reviews its own output against these rules and may revise it.
        Pass an empty list for `rules` to turn self-evaluation OFF.

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
    async def mspbotsagent_get_agent_approval(
        agent_id: Annotated[str, Field(description="The agent to read. Required.")],
    ) -> str:
        """Read an agent's human-in-the-loop approval rules.

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
        agent_id: Annotated[str, Field(description="The agent to update. Required.")],
        rules: Annotated[
            list[dict],
            Field(
                description=(
                    "List of approval-rule objects. Each rule: "
                    '{ "name": "gate-refunds", '
                    '"intent": "Issuing a refund over $100", '
                    '"triggers": ["refund", "\\$\\d{3,}"],   # regex/keywords '
                    '"tools": ["qbo.createRefund"], '
                    '"decisions": ["approve", "reject"] }'
                )
            ),
        ],
    ) -> str:
        """Set or update an agent's human-in-the-loop approval rules.

        Each rule gates a sensitive action so a human must approve/reject before
        the agent proceeds. Pass an empty list to remove all approval gates.

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
