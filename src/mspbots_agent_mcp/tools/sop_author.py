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
        """Read the agent's SOP name."""
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
        """Set the agent's SOP name.

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
        """Read the agent's SOP source — the raw task description it was authored from."""
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
        """Set or clear the agent's SOP source.

        value is required so clearing (null) is always explicit. Do not
        call this twice concurrently for the same agent.
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
        """Read the agent's SOP purpose (markdown)."""
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
        """Set the agent's SOP purpose: what it produces and its boundaries.

        Accepts markdown. Do not call this twice concurrently for the same agent.
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
        """Read the agent's SOP data-sources list (structured)."""
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
        """Set the agent's SOP data-sources list.

        Do not call this twice concurrently for the same agent.
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
        """Read the agent's SOP procedure (markdown)."""
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
        """Set the agent's SOP procedure — the ordered steps it follows.

        Accepts markdown (headings, numbered steps, per-step notes, etc.).
        Do not call this twice concurrently for the same agent.
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
    # envelope — the write body is the flat subset of the four booleans
    # being changed, and both read and write return all four booleans at
    # once (DB default false = hidden).

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_sop_section_visibility(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Read which optional sections show in the agent's SOP document.

        Returns {permissions, teams, twilio, orgChart} booleans — true
        means that section is shown, false (the default) means it's hidden.
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
    ) -> str:
        """Show or hide optional sections in the agent's SOP document.

        Partial update: pass only the sections you want to change, the rest
        keep their current value. Calling with no arguments changes
        nothing and just returns the current state. Returns all four
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
        try:
            result = await client.put(_path(agent_id, _SECTION_VISIBILITY), body)
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()
