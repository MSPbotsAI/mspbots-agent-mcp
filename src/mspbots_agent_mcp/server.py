import contextvars
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import AgentClient
from .config import Settings

# Per-request credential isolation via contextvars.
# GatewayTokenMiddleware sets this before the MCP handler runs.
# Python asyncio copies context per task, so concurrent SSE connections are isolated.
# Value is (access_token, host, tenant_id). tenant_id is forwarded to the
# downstream Agent API as an X_Tenant_ID header.
_gateway_creds_var: contextvars.ContextVar[tuple[str, str, str] | None] = contextvars.ContextVar(
    "mspbots_agent_gateway_creds", default=None
)


def get_client_from_context(settings: Settings) -> AgentClient | None:
    """Resolve the active AgentClient for the current request context."""
    creds = _gateway_creds_var.get()
    if not creds:
        return None
    token, host, tenant_id = creds
    return AgentClient(token, host, tenant_id)


class GatewayTokenMiddleware:
    """ASGI middleware.

    Reads X-MSP-Token, X-MSP-Tenant-Id, and X-MSP-Host (all required) from
    request headers and stores them in the contextvar. Returns 401 if any is
    missing on /mcp requests.
    """

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        token = request.headers.get("x-msp-token")
        tenant_id = request.headers.get("x-msp-tenant-id")
        host = request.headers.get("x-msp-host")
        if not token or not tenant_id or not host:
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": (
                        "This server requires the X-MSP-Token header (Agent Platform "
                        "bearer access credential), the X-MSP-Tenant-Id header, and "
                        "the X-MSP-Host header (Agent API host)"
                    ),
                    "required_headers": ["X-MSP-Token", "X-MSP-Tenant-Id", "X-MSP-Host"],
                    "optional_headers": [],
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        ctx_token = _gateway_creds_var.set((token, host, tenant_id))
        try:
            await self.app(scope, receive, send)
        finally:
            _gateway_creds_var.reset(ctx_token)


def create_mcp_server(settings: Settings) -> FastMCP:
    """Build the FastMCP server instance and register all Agent tools."""
    # DNS-rebinding protection is a browser-oriented safeguard that rejects
    # non-localhost Host headers with 421. Disable it so the server works
    # correctly behind a reverse proxy or docker network.
    mcp = FastMCP(
        name="mspbots-agent-mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    client_factory: Callable[[], AgentClient | None] = lambda: get_client_from_context(settings)

    from .tools import agents, connectors, triggers

    connectors.register(mcp, client_factory)
    triggers.register(mcp, client_factory)
    agents.register(mcp, client_factory)

    return mcp
