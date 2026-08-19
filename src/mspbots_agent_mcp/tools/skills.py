from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN

# `files` items ("SkillFile") are assumed to be {"path": str, "content": str}
# — a relative file path within the skill package (e.g. "SKILL.md",
# "scripts/helper.py") plus its raw text content. This wasn't included in the
# API spec handed to us (only referenced via a $ref with no definitions
# block attached) — it's inferred from how SKILL.md-based skill packages
# conventionally work elsewhere. Verify against the real API before relying
# on this for anything beyond a first draft.


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_list_agent_skills(
        agent_id: Annotated[str, Field(description="Agent whose skills to list.")],
    ) -> str:
        """List all skills available to an agent and their selected state.

        Covers org-shared, that agent's own private skills, and platform
        (mspbots) skills. selected=true means not opted out.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/api/agents/{agent_id}/skills")
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool()
    async def mspbotsagent_create_agent_skill(
        agent_id: Annotated[str, Field(description="Agent to create the skill for.")],
        name: Annotated[
            str, Field(description="Skill name, used to derive its slug/package name.")
        ],
        files: Annotated[
            list[dict],
            Field(
                description=(
                    'Non-empty list of {"path", "content"} file objects; must '
                    "include a SKILL.md or the API rejects the call."
                )
            ),
        ],
    ) -> str:
        """Create a new private skill for an agent and install it.

        `files` must include exactly one SKILL.md — its frontmatter
        (name/description/trigger/allowed-tools) is parsed server-side.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        if not files:
            return "Error: files must include at least one file (a SKILL.md is required)"
        try:
            result = await client.post(
                f"/api/agents/{agent_id}/skills/create",
                {"name": name, "files": files},
            )
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_update_agent_skill_files(
        agent_id: Annotated[str, Field(description="Owning agent.")],
        capability_id: Annotated[str, Field(description="Skill (capability) to update.")],
        files: Annotated[
            list[dict],
            Field(
                description=(
                    'The new complete file set as {"path", "content"} objects, '
                    "including SKILL.md."
                )
            ),
        ],
        note: Annotated[
            str | None, Field(description='Version note. Defaults to "Edit" if omitted.')
        ] = None,
    ) -> str:
        """Replace a private skill's files and publish a new version.

        Only works on a private skill owned by this agent — the server
        rejects org/mspbots skills.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        if not files:
            return "Error: files must include at least one file (a SKILL.md is required)"
        body: dict = {"files": files}
        if note is not None:
            body["note"] = note
        try:
            result = await client.put(
                f"/api/agents/{agent_id}/skills/{capability_id}/files", body
            )
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def mspbotsagent_delete_agent_skill(
        agent_id: Annotated[str, Field(description="Owning agent.")],
        capability_id: Annotated[str, Field(description="Private skill to delete.")],
    ) -> str:
        """Delete an agent's private skill: soft-deletes it and uninstalls it.

        Only works on a private skill owned by this agent — org/mspbots
        skills cannot be deleted this way.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.delete_with_body(
                f"/api/agents/{agent_id}/skills", {"id": capability_id}
            )
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()
