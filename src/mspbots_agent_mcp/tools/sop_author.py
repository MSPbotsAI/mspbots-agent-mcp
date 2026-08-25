from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN

# The "SOP author" resource holds an agent's standard-operating-procedure
# draft. It has five independent fields, each with its own read/write
# endpoint under /api/agents/:id/sop-author/<field>. Every write sends
# {"value": ...}.
#
# Although each field has its own endpoint (unlike the permissions/
# evaluation/approval trio in agents.py, which share one literal PUT
# /api/agents/:id), all five fields still live on the same underlying agent
# record. Treat concurrent writes to this agent's SOP fields the same way:
# do not update them from two calls at once.
#
# This is a documentation/planning artifact (the agent's written SOP),
# distinct from the tool-permission/evaluation/approval settings in
# agents.py, which govern the agent's actual runtime behavior.

_NAME = "/name"
_SOURCE = "/source"
_PURPOSE = "/purpose"
_DATA_SOURCES = "/data-sources-list"
_PROCEDURE = "/procedure"
_SECTION_VISIBILITY = "/section-visibility"

_MAX_NAME_LEN = 60


def _path(agent_id: str, field: str) -> str:
    return f"/api/agents/{agent_id}/sop-author{field}"


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    # ----- name -----------------------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_sop_name(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Check the name of the agent's SOP (Standard Operating Procedure) draft.

        Use when the conversation asks "what is this SOP called" or before
        renaming it.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _NAME))
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_set_sop_name(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        value: Annotated[
            str, Field(description="New name, non-empty and at most 60 characters.")
        ],
    ) -> str:
        """Name or rename the agent's SOP draft — e.g. "call this SOP 'Refund Handling'".

        Must be non-empty, at most 60 characters, and unique within the
        tenant (enforced server-side). Cannot be cleared. Do not call this
        twice concurrently for the same agent.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        stripped = (value or "").strip()
        if not stripped:
            return "Error: name cannot be empty"
        if len(stripped) > _MAX_NAME_LEN:
            return f"Error: name must be at most {_MAX_NAME_LEN} characters"
        try:
            result = await client.put(_path(agent_id, _NAME), {"value": value})
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    # ----- source ---------------------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_sop_source(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Check the original request/task description this SOP was authored from.

        Use when asked "what was this SOP originally built for" or "show me
        the raw request this came from".
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _SOURCE))
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_set_sop_source(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        value: Annotated[
            str | None, Field(description="New source text, or null to clear.")
        ],
    ) -> str:
        """Record or clear the original request this SOP was authored from.

        Use when the user restates or corrects what this SOP was originally
        asked to do. value is required so clearing (null) is always
        explicit. Do not call this twice concurrently for the same agent.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(_path(agent_id, _SOURCE), {"value": value})
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    # ----- purpose --------------------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_sop_purpose(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Check what this agent produces and its boundaries, per its SOP.

        Use for "what does this agent actually do" or "what's out of scope
        for this agent".
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _PURPOSE))
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_set_sop_purpose(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        value: Annotated[
            str,
            Field(
                description='Purpose markdown, e.g. "**Produces:** ...\\n**Boundary:** ...".'
            ),
        ],
    ) -> str:
        """Record what this agent produces and its boundaries, in its SOP.

        Use when the user is DOCUMENTING what the agent should produce or
        where its scope ends, e.g. "it should draft the reply but never
        send it" — this writes the SOP's stated scope, not a runtime
        permission gate. For an enforced restriction the platform actually
        blocks on (not just documents), use
        mspbotsagent_upsert_agent_permissions instead. Accepts markdown. Do
        not call this twice concurrently for the same agent.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(_path(agent_id, _PURPOSE), {"value": value})
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    # ----- data sources ---------------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_sop_data_sources(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Check which data sources/integrations this agent's SOP relies on.

        Use for "what does this agent pull data from" or "which integrations
        does this SOP depend on".
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _DATA_SOURCES))
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_set_sop_data_sources(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        value: Annotated[
            dict,
            Field(
                description=(
                    'Object with a "sources" array; each item is '
                    '{"integration": "<key>"}, e.g. '
                    '{"sources": [{"integration": "open-meteo"}]}.'
                )
            ),
        ],
    ) -> str:
        """Record a system this agent's SOP should pull data from before acting.

        Use whenever the user, while describing this SOP, names ANY system
        it should check or query first — e.g. "it should check inventory
        via NetSuite", "look up the weather via open-meteo", "pull the
        account tier from our CRM". This is about declaring the SOP's data
        sources, not actually querying that system right now. Do not call
        this twice concurrently for the same agent.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(_path(agent_id, _DATA_SOURCES), {"value": value})
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    # ----- procedure ------------------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_sop_procedure(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Check the step-by-step procedure this agent follows, per its SOP.

        Use when asked about it, e.g. "walk me through what this agent
        does step by step" or "what's the current process this agent
        runs". If the user is instead STATING or dictating the steps
        themselves (not asking), use mspbotsagent_set_sop_procedure.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _PROCEDURE))
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_set_sop_procedure(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        value: Annotated[str, Field(description="Procedure markdown.")],
    ) -> str:
        """Record the ordered steps this agent follows, in its SOP.

        Naming a real-sounding entity ("check the ticket", "pull account
        data", "apply the discount") does NOT mean do it now — there is no
        live ticket/account here, you're writing a spec, not performing
        it. Never respond "no real customer to act on" — call this with
        the steps as given. A STATEMENT of steps, not a question (see
        mspbotsagent_get_sop_procedure). Call as soon as steps are stated,
        without waiting for "save this". Accepts markdown.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(_path(agent_id, _PROCEDURE), {"value": value})
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    # ----- section visibility ---------------------------------------------
    # Unlike the five fields above, this one is not a {"value": ...}
    # envelope — the write body is the flat subset of the five booleans
    # being changed, and both read and write return all five booleans at
    # once (DB default false = hidden).

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_sop_section_visibility(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Check which optional sections show in the agent's SOP document.

        Use for a QUESTION about current state: "is the Teams section
        visible", "why can't I see the org chart section". If the user is
        instead telling you to change it — "show/hide the X section",
        "turn on/off X" — that's an instruction, use
        mspbotsagent_set_sop_section_visibility, even though "show" sounds
        like a query verb. Returns {permissions, teams, twilio, orgChart,
        humanInLoop} booleans — true means shown, false (default) hidden.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _SECTION_VISIBILITY))
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_set_sop_section_visibility(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        permissions: Annotated[
            bool | None, Field(description="Show the Permissions section. Omit to leave unchanged.")
        ] = None,
        teams: Annotated[
            bool | None,
            Field(description="Show the Teams (Microsoft Teams channel) section. Omit to leave unchanged."),
        ] = None,
        twilio: Annotated[
            bool | None,
            Field(description="Show the Twilio (phone channel) section. Omit to leave unchanged."),
        ] = None,
        org_chart: Annotated[
            bool | None, Field(description="Show the Org chart section. Omit to leave unchanged.")
        ] = None,
        human_in_loop: Annotated[
            bool | None,
            Field(description="Show the Human in the loop (approval intents) section. Omit to leave unchanged."),
        ] = None,
    ) -> str:
        """Show or hide sections in the SOP doc, e.g. "turn on the Teams section".

        Partial update: pass only the sections you want to change, the rest
        keep their current value. Calling with no arguments changes
        nothing and just returns the current state. Returns all five
        booleans after the change. Do not call this twice concurrently for
        the same agent.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        body: dict = {}
        if permissions is not None:
            body["permissions"] = permissions
        if teams is not None:
            body["teams"] = teams
        if twilio is not None:
            body["twilio"] = twilio
        if org_chart is not None:
            body["orgChart"] = org_chart
        if human_in_loop is not None:
            body["humanInLoop"] = human_in_loop
        try:
            result = await client.put(_path(agent_id, _SECTION_VISIBILITY), body)
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()
