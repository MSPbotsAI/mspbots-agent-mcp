"""tools/list snapshot + error-envelope mapping tests.

No network calls: tool enumeration goes through FastMCP's in-process
list_tools(), and the error-code mapping is tested directly against
AgentError, independent of any real HTTP request.
"""

import pytest
from mcp.server.fastmcp import FastMCP

from mspbots_agent_mcp.api_client import AgentError
from mspbots_agent_mcp.config import Settings
from mspbots_agent_mcp.server import create_mcp_server
from mspbots_agent_mcp.tools.agents import _invalid_bare_tool_ids

# name -> (required params, expected annotation hint set to True)
EXPECTED_TOOLS = {
    # connectors
    "mspbotsagent_get_connectors": (set(), {"readOnlyHint"}),
    # triggers
    "mspbotsagent_list_triggers": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_upsert_trigger": (set(), set()),
    "mspbotsagent_delete_trigger": ({"task_id"}, {"destructiveHint"}),
    "mspbotsagent_get_trigger_catalog": (set(), {"readOnlyHint"}),
    "mspbotsagent_run_trigger": ({"task_id"}, set()),
    # agent policy: permissions / evaluation / approval
    "mspbotsagent_get_agent_permissions": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_upsert_agent_permissions": ({"agent_id"}, {"idempotentHint"}),
    "mspbotsagent_get_agent_evaluation": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_upsert_agent_evaluation": ({"agent_id", "rules"}, {"idempotentHint"}),
    "mspbotsagent_get_agent_approval": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_upsert_agent_approval": ({"agent_id", "rules"}, {"idempotentHint"}),
    # SOP author
    "mspbotsagent_get_sop_name": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_set_sop_name": ({"agent_id", "value"}, {"idempotentHint"}),
    "mspbotsagent_get_sop_source": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_set_sop_source": ({"agent_id", "value"}, {"idempotentHint"}),
    "mspbotsagent_get_sop_purpose": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_set_sop_purpose": ({"agent_id", "value"}, {"idempotentHint"}),
    "mspbotsagent_get_sop_data_sources": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_set_sop_data_sources": ({"agent_id", "value"}, {"idempotentHint"}),
    "mspbotsagent_get_sop_procedure": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_set_sop_procedure": ({"agent_id", "value"}, {"idempotentHint"}),
    "mspbotsagent_get_sop_section_visibility": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_set_sop_section_visibility": ({"agent_id"}, {"idempotentHint"}),
    "mspbotsagent_clear_sop_section": (
        {"agent_id", "section"},
        {"destructiveHint", "idempotentHint"},
    ),
    # skills
    "mspbotsagent_list_agent_skills": ({"agent_id"}, {"readOnlyHint"}),
    "mspbotsagent_create_agent_skill": ({"agent_id", "name", "files"}, set()),
    "mspbotsagent_update_agent_skill_files": (
        {"agent_id", "capability_id", "files"},
        {"idempotentHint"},
    ),
    "mspbotsagent_delete_agent_skill": (
        {"agent_id", "capability_id"},
        {"destructiveHint"},
    ),
}


@pytest.mark.asyncio
async def test_tools_list_snapshot():
    mcp = create_mcp_server(Settings())
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == set(EXPECTED_TOOLS), f"unexpected tool set: {names}"

    by_name = {t.name: t for t in tools}
    # These two tools are deliberate exceptions to the SOP's 500-char
    # description guideline (§2.2, a "should" not a hard rule): their
    # docstrings document real, load-bearing usage guidance (trigger types
    # including "manual"; the permission/interrupt_on/approval relationship
    # and decision values) added upstream after this repo's SOP refactor
    # started. Trimming them to fit 500 chars would drop guidance an agent
    # needs to call these tools correctly — confirmed by cross-checking
    # origin/main's content during a rebase conflict.
    # mspbotsagent_clear_sop_section joins this list for the same reason:
    # it's a destructive, irreversible, multi-branch tool (5 section
    # values, each with a different real-world effect, plus the excluded-
    # sections note) where an agent picking the wrong one can't be undone —
    # the per-section effect table is load-bearing, not decorative
    # (PRD-17514, scope narrowed to 5 sections per Leo Yang's later comment).
    _LONG_DESCRIPTION_EXCEPTIONS = {
        "mspbotsagent_upsert_trigger",
        "mspbotsagent_upsert_agent_permissions",
        "mspbotsagent_clear_sop_section",
    }
    for name, (expected_required, expected_hints) in EXPECTED_TOOLS.items():
        tool = by_name[name]
        required = set(tool.inputSchema.get("required", []))
        assert required == expected_required, f"{name}: required={required}"

        description = tool.description or ""
        if name not in _LONG_DESCRIPTION_EXCEPTIONS:
            assert len(description) <= 500, f"{name}: description too long ({len(description)})"
        first_line = description.strip().splitlines()[0] if description.strip() else ""
        assert len(first_line) <= 100, f"{name}: first line too long: {first_line!r}"
        assert "API:" not in description, f"{name}: leaked implementation detail"
        assert "GET /" not in description and "POST /" not in description, (
            f"{name}: leaked implementation detail"
        )

        annotations = tool.annotations
        actual_hints = set()
        if annotations is not None:
            for hint in ("readOnlyHint", "destructiveHint", "idempotentHint"):
                if getattr(annotations, hint, None) is True:
                    actual_hints.add(hint)
        assert actual_hints == expected_hints, f"{name}: hints={actual_hints}"


@pytest.mark.asyncio
async def test_service_instructions_present_and_bounded():
    mcp = create_mcp_server(Settings())
    assert mcp.instructions
    assert len(mcp.instructions) <= 1500


@pytest.mark.parametrize(
    "status_code,expected_code,expected_retryable",
    [
        (0, "upstream_error", True),
        (400, "invalid_argument", False),
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (422, "invalid_argument", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (503, "upstream_error", True),
    ],
)
def test_error_envelope_mapping(status_code, expected_code, expected_retryable):
    import json

    err = AgentError(status_code, "boom")
    envelope = json.loads(err.to_envelope())
    assert envelope["error"]["code"] == expected_code
    assert envelope["error"]["retryable"] is expected_retryable
    assert envelope["error"]["message"] == "boom"


@pytest.mark.parametrize(
    "keys,expected_bad",
    [
        ({"execute": "deny"}, []),
        ({"read_file": "ask", "write_file": "allow"}, []),
        ({"qbo.createInvoice": "ask"}, []),
        ({"send_email": "deny"}, ["send_email"]),
        ({"shell.exec": "deny"}, []),  # dotted — assumed to be a real connector id, unverifiable statically
        ({"execute": "deny", "send_message": "ask"}, ["send_message"]),
        (None, []),
        ({}, []),
    ],
)
def test_invalid_bare_tool_ids(keys, expected_bad):
    assert sorted(_invalid_bare_tool_ids(keys)) == sorted(expected_bad)


@pytest.mark.asyncio
async def test_clear_sop_section_has_real_enum_constraint():
    # SOP §3 (02-开发阶段SOP.md): enum-shaped params must carry a real JSON
    # Schema `enum`, not just enum values mentioned in prose. section not
    # only affects tool_use accuracy — it's a destructive action, so a
    # client that skips the enum entirely would only find out it guessed
    # wrong after the (irreversible) API call.
    mcp = create_mcp_server(Settings())
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "mspbotsagent_clear_sop_section")
    section_schema = tool.inputSchema["properties"]["section"]
    assert set(section_schema.get("enum", [])) == {
        "evaluation",
        "humanInLoop",
        "teams",
        "twilio",
        "orgChart",
    }


@pytest.mark.asyncio
async def test_clear_sop_section_rejects_unknown_section_before_calling_api():
    # FastMCP validates `section` against the Literal via pydantic before
    # the tool function ever runs — confirmed here by asserting the stub
    # client's delete() is never reached, and that the rejection names the
    # real enum (not this repo's own {"error": {...}} shape, which only
    # AgentError.to_envelope() produces — pydantic's ToolError is a
    # different, but equally real, structured rejection).
    from mcp.server.fastmcp.exceptions import ToolError

    from mspbots_agent_mcp.tools import sop_author

    captured = {}

    class _StubClient:
        async def delete(self, path):
            captured["called"] = path
            return {"ok": True}

    mcp = FastMCP(name="test")
    sop_author.register(mcp, lambda: _StubClient())
    with pytest.raises(ToolError) as exc_info:
        await mcp.call_tool(
            "mspbotsagent_clear_sop_section", {"agent_id": "a1", "section": "not_a_real_section"}
        )
    assert "evaluation" in str(exc_info.value)
    assert "called" not in captured, "must reject before ever calling the API"
