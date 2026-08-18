import json
from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN

# The "SOP author" resource holds an agent's standard-operating-procedure draft.
# It has five independent fields, each with its own read/write endpoint under
# /api/agents/:id/sop-author/<field>. Every write sends {"value": ...}.
#
# Although each field has its own endpoint (unlike the permissions/evaluation/
# approval trio in agents.py, which share one literal PUT /api/agents/:id), all
# five fields still live on the same underlying agent record (the "sopAuthor"
# sub-document keyed by agentId). Treat concurrent writes to this agent's SOP
# fields the same way: do not update them from two calls at once.
#
# This is a documentation/planning artifact (the agent's written SOP), distinct
# from the tool-permission/evaluation/approval settings in agents.py, which
# govern the agent's actual runtime behavior.

_NAME = "/name"
_SOURCE = "/source"
_PURPOSE = "/purpose"
_DATA_SOURCES = "/data-sources-list"
_PROCEDURE = "/procedure"

_MAX_NAME_LEN = 60


def _path(agent_id: str, field: str) -> str:
    return f"/api/agents/{agent_id}/sop-author{field}"


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    # ----- name -----------------------------------------------------------

    @mcp.tool()
    async def mspbotsagent_get_sop_name(
        agent_id: Annotated[str, Field(description="The agent to read. Required.")],
    ) -> str:
        """Read the agent's SOP name.

        Returns the current name as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _NAME))
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_set_sop_name(
        agent_id: Annotated[str, Field(description="The agent to update. Required.")],
        value: Annotated[
            str, Field(description="New name (non-empty, <= 60 chars). Required.")
        ],
    ) -> str:
        """Set the agent's SOP name.

        The name must be a non-empty string of at most 60 characters and must be
        unique within the tenant (uniqueness is enforced by the server). It
        cannot be cleared — always provide a real name.

        Do not update this agent's SOP fields from two calls at once — they
        share the same underlying record and concurrent writes can race.

        Returns the updated record as JSON.
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
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    # ----- source ---------------------------------------------------------

    @mcp.tool()
    async def mspbotsagent_get_sop_source(
        agent_id: Annotated[str, Field(description="The agent to read. Required.")],
    ) -> str:
        """Read the agent's SOP source (the raw task description it was authored from).

        Returns the current source as JSON (may be null).
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _SOURCE))
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_set_sop_source(
        agent_id: Annotated[str, Field(description="The agent to update. Required.")],
        value: Annotated[
            str | None, Field(description="New source text, or null to clear. Required.")
        ],
    ) -> str:
        """Set (or clear) the agent's SOP source.

        Pass a string to set the source, or pass null to clear it. `value` is
        required so clearing is always explicit.

        Do not update this agent's SOP fields from two calls at once — they
        share the same underlying record and concurrent writes can race.

        Returns the updated record as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(_path(agent_id, _SOURCE), {"value": value})
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    # ----- purpose --------------------------------------------------------

    @mcp.tool()
    async def mspbotsagent_get_sop_purpose(
        agent_id: Annotated[str, Field(description="The agent to read. Required.")],
    ) -> str:
        """Read the agent's SOP purpose (markdown).

        Returns the current purpose markdown as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _PURPOSE))
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_set_sop_purpose(
        agent_id: Annotated[str, Field(description="The agent to update. Required.")],
        value: Annotated[
            str,
            Field(
                description=(
                    'Purpose markdown, e.g. "**Produces:** ...\\n**Boundary:** ...". '
                    "Required."
                )
            ),
        ],
    ) -> str:
        """Set the agent's SOP purpose.

        Describes what the SOP produces and its boundaries. Accepts markdown.

        Do not update this agent's SOP fields from two calls at once — they
        share the same underlying record and concurrent writes can race.

        Returns the updated record as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(_path(agent_id, _PURPOSE), {"value": value})
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    # ----- data sources ---------------------------------------------------

    @mcp.tool()
    async def mspbotsagent_get_sop_data_sources(
        agent_id: Annotated[str, Field(description="The agent to read. Required.")],
    ) -> str:
        """Read the agent's SOP data-sources list (structured).

        Returns the structured data-sources object as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _DATA_SOURCES))
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_set_sop_data_sources(
        agent_id: Annotated[str, Field(description="The agent to update. Required.")],
        value: Annotated[
            dict,
            Field(
                description=(
                    'Object with a "sources" array; each item is '
                    '{ "integration": "<key>" }.'
                )
            ),
        ],
    ) -> str:
        """Set the agent's SOP data-sources list (structured object).

        Each source stores only its integration key. Shape:
          { "sources": [ { "integration": "open-meteo" }, { "integration": "ms-graph" } ] }

        Do not update this agent's SOP fields from two calls at once — they
        share the same underlying record and concurrent writes can race.

        Returns the updated record as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(_path(agent_id, _DATA_SOURCES), {"value": value})
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    # ----- procedure ------------------------------------------------------

    @mcp.tool()
    async def mspbotsagent_get_sop_procedure(
        agent_id: Annotated[str, Field(description="The agent to read. Required.")],
    ) -> str:
        """Read the agent's SOP procedure (markdown).

        Returns the current procedure markdown as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(_path(agent_id, _PROCEDURE))
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_set_sop_procedure(
        agent_id: Annotated[str, Field(description="The agent to update. Required.")],
        value: Annotated[str, Field(description="Procedure markdown. Required.")],
    ) -> str:
        """Set the agent's SOP procedure.

        The ordered steps the agent follows. Accepts markdown (headings, numbered
        steps, per-step executor/output/done-when/idempotency notes, etc.).

        Do not update this agent's SOP fields from two calls at once — they
        share the same underlying record and concurrent writes can race.

        Returns the updated record as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(_path(agent_id, _PROCEDURE), {"value": value})
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)
