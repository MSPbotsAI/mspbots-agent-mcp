from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN

# Permissions, evaluation, and human-in-loop approval all live on the SAME
# agent record. Reads share one GET /api/agents/:id; writes share one partial
# PUT /api/agents/:id. Because writes are partial patches, two concurrent
# PUTs to the same agent can clobber each other — callers must not update the
# same agent in parallel.
#
# These settings govern the agent's actual runtime behavior (what it is
# allowed to do, when it must pause, when a human must approve). That's
# distinct from the SOP-author tools (sop_author.py), which manage a
# documentation/planning artifact rather than enforced runtime policy.


_KNOWN_BUILTIN_TOOL_IDS = {
    "execute",
    "read_file",
    "write_file",
    "edit_file",
    "download",
    "task",
    "start_async_task",
    "ask",
}


def _invalid_bare_tool_ids(keys: Any) -> list[str]:
    """Flag permission/interrupt_on keys that look like a built-in tool id
    (no "." — connector tool ids are always "vendor.action") but aren't one
    of the real built-ins. Catches a real failure mode: a model guessing a
    plausible-sounding id (e.g. "send_email") that doesn't exist, which
    otherwise gets forwarded to the backend silently rather than rejected.
    """
    if not isinstance(keys, dict):
        return []
    return [k for k in keys if isinstance(k, str) and "." not in k and k not in _KNOWN_BUILTIN_TOOL_IDS]


async def _fetch_agent_data(client: AgentClient, agent_id: str) -> Any:
    result = await client.get(f"/api/agents/{agent_id}")
    return (result or {}).get("data", {}) or {}


async def _guard_policy(client: AgentClient, agent_id: str) -> str | None:
    """Return an error envelope if the agent must not be written back, else None.

    When data.policyError=true the stored policy is in a bad state; writing
    on top of it would persist a broken config, so we refuse.
    """
    try:
        data = await _fetch_agent_data(client, agent_id)
    except AgentError as e:
        return e.to_envelope()
    if data.get("policyError") is True:
        return error_envelope(
            "invalid_argument",
            "Agent has policyError=true — refusing to write back to avoid persisting "
            "a broken policy. Resolve the policy error first.",
            False,
        )
    return None


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    # ----- permissions -----------------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_agent_permissions(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Check what an agent is allowed to do and when it must pause for a human.

        Use for questions like "what can this agent do", "is this agent
        allowed to send emails", "why does it keep asking for approval",
        "who owns this agent". Returns permission (tool -> allow/ask/deny),
        interruptOn, owners, the agent's available tools, and policyError.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            data = await _fetch_agent_data(client, agent_id)
        except AgentError as e:
            return e.to_envelope()
        projected = {
            "permission": data.get("permission"),
            "interruptOn": data.get("interruptOn"),
            "owners": data.get("owners"),
            "tools": data.get("tools"),
            "policyError": data.get("policyError"),
        }
        return dump_json_capped(projected)

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_upsert_agent_permissions(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        permission: Annotated[
            dict | None,
            Field(
                description=(
                    'Map of tool -> "allow" | "ask" | "deny". Keys are tool ids: '
                    "one of the built-ins listed below (bare, no dot), or a "
                    'connector id in "vendor.action" form (e.g. "qbo.createInvoice" '
                    "— call mspbotsagent_get_connectors first to find the real one; "
                    "guessing one is rejected). Example: "
                    '{"qbo.createInvoice": "ask", "execute": "deny"}'
                )
            ),
        ] = None,
        interrupt_on: Annotated[
            dict | None,
            Field(
                description=(
                    "Map of tool -> true, or "
                    '{"allowed_decisions": ["approve","edit","reject"], "description": "..."}. '
                    'Example: {"email.send": true}'
                )
            ),
        ] = None,
        approval: Annotated[
            dict | None,
            Field(
                description=(
                    'Intent-level approval rules: {"rules": [ ... ]}. Each rule: '
                    '{"name"?, "intent"?, "triggers"?: [regex], "tools"?: [tool], '
                    '"decisions"?: [decision]}. Example: '
                    '{"rules": [{"intent": "refunds over $500", '
                    '"triggers": ["refund"], "decisions": ["approve","reject"]}]}. '
                    'Send {"rules": []} to clear all intents.'
                )
            ),
        ] = None,
        owners: Annotated[
            list[dict] | None,
            Field(
                description=(
                    'List of {"userId", "name", "email"} objects who own the agent.'
                )
            ),
        ] = None,
    ) -> str:
        """Change what an agent can do, when it must pause for a human, or who owns it.

        Use for requests like "let this agent send emails without asking",
        "make this agent always ask before deleting anything", "never let
        it run shell commands", "make Jane an owner of this agent" — this
        is an ENFORCED, platform-checked gate, not documentation. For a
        dollar-threshold or other intent-based approval rule (e.g. "any
        refund over $500 needs approval"), use
        mspbotsagent_upsert_agent_approval instead. If the user is instead
        just describing the SOP's scope in prose (e.g. "it should draft
        but never send"), that's mspbotsagent_set_sop_purpose, not this.
        Updates an agent's action-governance settings and/or owners (partial). This tool covers
        the "can it act / must it pause" axis — permission, interrupt_on, approval — plus owners.
        It does NOT set `review` (that is the separate output-quality/self-review axis; use the
        review tool for that).

        Keys are independent — only the ones you pass change; omitted keys are left untouched.
        Provide at least one of `permission`, `interrupt_on`, `approval`, or `owners`. You may
        send `owners` alone to just change ownership.

        HOW THE THREE ACTION KEYS RELATE
          • permission   — per-tool baseline gate. {tool -> "allow" | "ask" | "deny"}.
              allow = call freely; deny = never call; ask = pause for a human before calling.
          • interrupt_on — the RICH form of "ask", per-tool. {tool -> true} or
              {tool -> {"allowed_decisions": [...], "description": "..."}}. Use it when a paused
              tool should restrict what the reviewer may decide, or show a note. permission:"ask"
              and interrupt_on for the same tool are two forms of ONE setting (pause), not a
              conflict: a full/empty decision set stays as permission:"ask"; a restricted set
              lives in interrupt_on. allow/deny only ever live in permission.
          • approval     — INTENT-level, independent of per-tool ask and NOT keyed by tool name.
              {"rules": [{"name"?, "intent"?, "triggers"?: [regex], "tools"?: [tool],
              "decisions"?: [decision]}]}. A router judges each pending action against `intent`
              (the wording) and `triggers` (regexes that pre-filter which calls reach the rule); a
              match forces approval even if the tool itself is "allow". Send {"rules": []} to
              clear all intents. Invalid trigger regex is rejected.

        KNOWN BUILT-IN TOOL IDS (keys for permission / interrupt_on)
          execute          Run shell commands / code
          read_file        Read files in the workspace
          write_file       Create or overwrite files
          edit_file        Modify existing files
          download         Hand a finished file to the user
          task             Delegate to a sub-agent
          start_async_task Start a background agent and carry on
          ask              Ask the user a question (HITL channel; a distinct toggle, not a preset
                           tool)
        Connector (MCP) tools use their own ids verbatim, e.g. "qbo.createInvoice".

        DECISION VALUES (for interrupt_on.allowed_decisions and approval.decisions)
          "approve" (Allow)   "edit" (Edit)   "reject" (Deny)
        Deny note: agentos also treats {tool: false} in a `tools` map as equivalent to permission
        "deny" (the two are unioned). Write denies via permission:"deny".

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

        bad_ids = _invalid_bare_tool_ids(permission) + _invalid_bare_tool_ids(interrupt_on)
        if bad_ids:
            return error_envelope(
                "invalid_argument",
                f"Not a recognized built-in tool id: {', '.join(sorted(set(bad_ids)))}. "
                f"Built-ins are: {', '.join(sorted(_KNOWN_BUILTIN_TOOL_IDS))}. A connector "
                "tool id must be in \"vendor.action\" form (e.g. \"qbo.createInvoice\") — "
                "call mspbotsagent_get_connectors first to find the real key.",
                False,
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
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    # ----- evaluation --------------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_agent_evaluation(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Check whether an agent reviews its own output before finishing.

        Use for questions like "does this agent double-check its work",
        "what quality rules does it follow". Returns review = {rules,
        max_iterations}, or null if unconfigured.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            data = await _fetch_agent_data(client, agent_id)
        except AgentError as e:
            return e.to_envelope()
        return dump_json_capped({"review": data.get("review")})

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_upsert_agent_evaluation(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        rules: Annotated[
            list[dict],
            Field(
                description=(
                    "List of rule objects; empty list disables self-eval. Each: "
                    '{"rubric": "...", "name": "...", "description": "...", '
                    '"triggers": ["regex or keyword", ...]}.'
                )
            ),
        ],
        max_iterations: Annotated[
            int | None, Field(description="Max self-review passes, e.g. 3.")
        ] = None,
    ) -> str:
        """Turn on/off or edit an agent's self-review rules before it finishes.

        Always this tool for "self-review"/"self-check"/"double-check X
        before Y"/"verify its math first"/"stop self-review" — never
        permissions, approval, or an SOP procedure step, however it's
        phrased. A vague `rubric` is enough (e.g. "checks the math is
        correct") — never wait for more specifics. Empty rules list turns
        it off. Do not call this twice concurrently for the same agent.
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
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    # ----- human-in-loop (approval) ------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_agent_approval(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Check which of an agent's actions need a human to approve first.

        Use for questions like "does this agent need approval to send
        refunds", "what needs sign-off before this agent does it". Returns
        approval = list of rule objects (may be empty).
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            data = await _fetch_agent_data(client, agent_id)
        except AgentError as e:
            return e.to_envelope()
        return dump_json_capped({"approval": data.get("approval")})

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_upsert_agent_approval(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        rules: Annotated[
            list[dict],
            Field(
                description=(
                    "List of approval-rule objects. Each: "
                    '{"name": "...", "intent": "...", '
                    '"triggers": ["regex or keyword", ...], "tools": [...], '
                    '"decisions": ["approve", "reject"]}.'
                )
            ),
        ],
    ) -> str:
        """Require a human's sign-off before an agent takes a sensitive action.

        Use for requests like "make a human approve any refund over $500
        before this agent sends it".

        rules FULL REPLACES the list, it does not append — read via
        mspbotsagent_get_agent_approval first, then pass the whole updated
        array back. Empty list clears all gates.

        Shares one PUT with the permissions/evaluation tools — never run
        two of the three concurrently on the same agent.
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
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()
