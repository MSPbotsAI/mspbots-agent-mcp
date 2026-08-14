from typing import Any

import httpx

# The Agent Platform capabilities API is reachable at this path prefix:
# "https://<host>/apps/mb-platform-agent/api/capabilities/<endpoint>".
# X-MSP-Host only carries the bare host; do not hardcode the prefix elsewhere.
_API_PREFIX = "/apps/mb-platform-agent/api/capabilities"


class AgentError(Exception):
    def __init__(self, status_code: int, code: str | None, message: str):
        self.status_code = status_code
        self.code = code
        super().__init__(f"Agent API error {status_code} ({code}): {message}")


class AgentClient:
    """Async httpx client wrapping the MSPbots Agent Platform capabilities API.

    The tenant is embedded in the JWT bearer token. We additionally forward the
    tenant id as an `X_Tenant_ID` header to stay consistent with the platform
    convention (the sibling ticketqa-mcp service relies on it for routing).
    """

    def __init__(self, access_token: str, host: str, tenant_id: str):
        self._token = access_token
        self._tenant_id = tenant_id
        self._base_url = host.rstrip("/") + _API_PREFIX

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "X_Tenant_ID": self._tenant_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _clean_params(self, params: dict | None) -> dict:
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    async def get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.get(
                    f"{self._base_url}{path}",
                    headers=self._headers(),
                    params=self._clean_params(params),
                )
            except httpx.RequestError as e:
                raise AgentError(0, None, f"{e or type(e).__name__} (url={self._base_url}{path})") from e
            return self._handle(resp)

    async def post(self, path: str, json_body: Any) -> Any:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(
                    f"{self._base_url}{path}",
                    headers=self._headers(),
                    json=json_body,
                )
            except httpx.RequestError as e:
                raise AgentError(0, None, f"{e or type(e).__name__} (url={self._base_url}{path})") from e
            return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> Any:
        try:
            body = resp.json()
        except ValueError:
            body = {"raw_response": resp.text}
        if resp.status_code >= 400:
            code = body.get("code") if isinstance(body, dict) else None
            message = body.get("message") if isinstance(body, dict) else str(body)
            errors = body.get("errors") if isinstance(body, dict) else None
            if errors:
                message = f"{message} | errors={errors}"
            raise AgentError(resp.status_code, code, message or "unknown error")
        return body
