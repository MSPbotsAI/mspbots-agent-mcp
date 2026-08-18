import json
from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN

# `files` items ("SkillFile") are assumed to be {"path": str, "content": str} —
# a relative file path within the skill package (e.g. "SKILL.md",
# "scripts/helper.py") plus its raw text content. This wasn't included in the
# API spec handed to us (only referenced via "$ref": "#/definitions/SkillFile"
# with no definitions block attached) — it's inferred from how SKILL.md-based
# skill packages conventionally work elsewhere. Verify against the real API
# before relying on this for anything beyond a first draft.


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    @mcp.tool()
    async def mspbotsagent_list_agent_skills(
        agent_id: Annotated[
            str, Field(description="The agent whose skills to list. Required.")
        ],
    ) -> str:
        """List all skills available to an agent: org-shared + that agent's own
        private skills + platform (mspbots) skills, with each one's selected
        (opted-in) state.

        Returns JSON with a `skills` array (id, type: mspbots|org|agent, ref,
        scope, name, skillName, description, version, enabled, selected,
        available) and a `selectedIds` array of the currently-selected refs.
        `selected=true` means not opted out.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/api/agents/{agent_id}/skills")
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_create_agent_skill(
        agent_id: Annotated[
            str, Field(description="The agent to create the skill for. Required.")
        ],
        name: Annotated[
            str,
            Field(
                description="Skill name, used to derive its slug/npm package name. Required."
            ),
        ],
        files: Annotated[
            list[dict],
            Field(
                description=(
                    "Non-empty list of file objects; must include a "
                    'SKILL.md or the API rejects with "A SKILL.md file is '
                    'required". Required.'
                )
            ),
        ],
    ) -> str:
        """Create a new private skill (scope=agent) for an agent, publish it as
        an npm version, and install it into that agent's workspace.

        `files` must include exactly one SKILL.md — its frontmatter
        (name/description/trigger/allowed-tools) is parsed automatically by
        the server. Each item in `files` is assumed to be
        {"path": "<relative path, e.g. 'SKILL.md'>", "content": "<raw text>"}
        (see module-level note — this shape wasn't in the spec we were given
        and should be confirmed against the real API).

        Returns the new capability's id as JSON.
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
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_update_agent_skill_files(
        agent_id: Annotated[str, Field(description="The owning agent. Required.")],
        capability_id: Annotated[
            str, Field(description="The skill (capability) to update. Required.")
        ],
        files: Annotated[
            list[dict],
            Field(
                description=(
                    "The new complete file set, including SKILL.md. "
                    "Required. See module-level note on the assumed "
                    '{"path", "content"} shape.'
                )
            ),
        ],
        note: Annotated[
            str | None,
            Field(description='Version note. Defaults to "Edit" server-side if omitted.'),
        ] = None,
    ) -> str:
        """Replace a private skill's files (whole-package replace) and publish a
        new version. Only works on a private skill owned by this agent — the
        server checks ownership and rejects org/mspbots skills.

        Returns the new version's id/version/hash as JSON.
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
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_delete_agent_skill(
        agent_id: Annotated[str, Field(description="The owning agent. Required.")],
        capability_id: Annotated[
            str, Field(description="The private skill to delete. Required.")
        ],
    ) -> str:
        """Delete an agent's private skill: soft-deletes the capability, clears
        its opt-out row, and uninstalls it from the workspace. Only works on a
        private skill (scope=agent) owned by this agent — org/mspbots skills
        cannot be deleted this way.

        Returns the agentId and the removed capability id as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.delete_with_body(
                f"/api/agents/{agent_id}/skills", {"id": capability_id}
            )
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)
