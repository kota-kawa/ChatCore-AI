"""Remote Streamable HTTP MCP server for publishing shared prompts."""

from __future__ import annotations

from typing import Annotated, Any

from cryptography.fernet import Fernet
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field, ValidationError

from services.async_utils import run_blocking
from services.auth_limits import consume_rate_limit
from services.mcp_config import (
    get_mcp_allowed_hosts,
    get_mcp_allowed_origins,
    get_mcp_encryption_keys,
    get_mcp_public_base_url,
    get_mcp_server_url,
)
from services.mcp_oauth import ChatCoreOAuthProvider, MCP_PROMPTS_WRITE_SCOPE
from services.request_models import (
    MAX_SHARED_PROMPT_AI_MODEL_LENGTH,
    MAX_SHARED_PROMPT_CONTENT_LENGTH,
    MAX_SHARED_PROMPT_TITLE_LENGTH,
    SharedPromptCreateRequest,
)
from services.shared_prompt_service import create_shared_prompt
from services.web_urls import build_frontend_url

_mcp: FastMCP | None = None
_mcp_asgi_app: Any | None = None


def _require_actor_user_id() -> int:
    token = get_access_token()
    if token is None or not token.subject:
        raise ToolError("MCP access token is missing its authenticated user.")
    try:
        return int(token.subject)
    except (TypeError, ValueError) as exc:
        raise ToolError("MCP access token has an invalid authenticated user.") from exc


async def _consume_publish_limit(user_id: int) -> None:
    allowed, _, retry_after = await run_blocking(
        consume_rate_limit,
        "mcp_prompt_publish:hour",
        str(user_id),
        limit=10,
        window_seconds=3600,
    )
    if not allowed:
        raise ToolError(f"投稿上限に達しました。約{retry_after}秒後に再試行してください。")
    allowed, _, retry_after = await run_blocking(
        consume_rate_limit,
        "mcp_prompt_publish:day",
        str(user_id),
        limit=50,
        window_seconds=24 * 3600,
    )
    if not allowed:
        raise ToolError(f"1日の投稿上限に達しました。約{retry_after}秒後に再試行してください。")


async def _publish(user_id: int, payload: SharedPromptCreateRequest) -> dict[str, Any]:
    await _consume_publish_limit(user_id)
    prompt_id = await run_blocking(create_shared_prompt, user_id, payload)
    return {
        "prompt_id": prompt_id,
        "title": payload.title,
        "content_format": payload.content_format,
        "public_url": build_frontend_url(get_mcp_public_base_url(), f"/shared/prompt/{prompt_id}"),
    }


def _create_mcp() -> FastMCP:
    # Validate encryption-key material at startup, before accepting DCR secrets.
    for key in get_mcp_encryption_keys():
        Fernet(key.encode("ascii"))
    public_base_url = get_mcp_public_base_url()
    provider = ChatCoreOAuthProvider()
    mcp = FastMCP(
        "Chat-Core Prompt Sharing",
        instructions=(
            "登録済みChat-Coreユーザーの公開プロンプト共有へ投稿します。"
            "投稿はすぐ公開され、同じ呼び出しの再実行は別投稿になります。"
        ),
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=public_base_url,
            resource_server_url=get_mcp_server_url(),
            required_scopes=[MCP_PROMPTS_WRITE_SCOPE],
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=[MCP_PROMPTS_WRITE_SCOPE],
                default_scopes=[MCP_PROMPTS_WRITE_SCOPE],
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=get_mcp_allowed_hosts(),
            allowed_origins=get_mcp_allowed_origins(),
        ),
    )
    annotations = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )

    @mcp.tool(
        name="publish_prompt",
        title="公開プロンプトを投稿",
        description="Chat-Coreの公開プロンプト共有へテキストプロンプトを即時公開します。再実行は別投稿になります。",
        annotations=annotations,
        structured_output=True,
    )
    async def publish_prompt(
        title: Annotated[str, Field(min_length=1, max_length=MAX_SHARED_PROMPT_TITLE_LENGTH)],
        content: Annotated[str, Field(min_length=1, max_length=MAX_SHARED_PROMPT_CONTENT_LENGTH)],
        category: str = "",
        input_examples: Annotated[str, Field(max_length=MAX_SHARED_PROMPT_CONTENT_LENGTH)] = "",
        output_examples: Annotated[str, Field(max_length=MAX_SHARED_PROMPT_CONTENT_LENGTH)] = "",
        ai_model: Annotated[str, Field(max_length=MAX_SHARED_PROMPT_AI_MODEL_LENGTH)] = "",
    ) -> dict[str, Any]:
        try:
            payload = SharedPromptCreateRequest(
                title=title,
                content=content,
                category=category,
                input_examples=input_examples,
                output_examples=output_examples,
                ai_model=ai_model,
                content_format="prompt",
                media_type="text",
            )
        except ValidationError as exc:
            raise ToolError("投稿内容が不正です。") from exc
        return await _publish(_require_actor_user_id(), payload)

    @mcp.tool(
        name="publish_skill",
        title="公開SKILLを投稿",
        description="Chat-Coreの公開プロンプト共有へSKILLを即時公開します。SKILL内のコードは実行されません。",
        annotations=annotations,
        structured_output=True,
    )
    async def publish_skill(
        title: Annotated[str, Field(min_length=1, max_length=MAX_SHARED_PROMPT_TITLE_LENGTH)],
        skill_markdown: Annotated[str, Field(min_length=1, max_length=MAX_SHARED_PROMPT_CONTENT_LENGTH)],
        category: str = "",
        skill_python_script: Annotated[str, Field(max_length=MAX_SHARED_PROMPT_CONTENT_LENGTH)] = "",
        ai_model: Annotated[str, Field(max_length=MAX_SHARED_PROMPT_AI_MODEL_LENGTH)] = "",
    ) -> dict[str, Any]:
        try:
            payload = SharedPromptCreateRequest(
                title=title,
                category=category,
                content_format="skill",
                media_type="text",
                ai_model=ai_model,
                attributes={
                    "skill_markdown": skill_markdown,
                    "skill_python_script": skill_python_script,
                },
            )
        except ValidationError as exc:
            raise ToolError("SKILLの内容が不正です。") from exc
        return await _publish(_require_actor_user_id(), payload)

    return mcp


def get_mcp_asgi_app():
    global _mcp, _mcp_asgi_app
    if _mcp_asgi_app is None:
        _mcp = _create_mcp()
        _mcp_asgi_app = _mcp.streamable_http_app()
    return _mcp_asgi_app


def get_mcp_lifespan_context():
    app = get_mcp_asgi_app()
    return app.router.lifespan_context(app)


def get_oauth_authorization_metadata() -> dict[str, Any]:
    """Expose CIMD support, which the v1 SDK metadata helper does not advertise."""
    base = get_mcp_public_base_url()
    # RFC 8414 §3.3 requires the issuer to byte-match the value advertised in the
    # protected resource metadata's authorization_servers, which the MCP SDK
    # serializes via AnyHttpUrl (a trailing slash is appended to a bare host).
    # Normalize the same way so strict clients (e.g. ChatGPT) accept discovery.
    issuer = str(AnyHttpUrl(base))
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "revocation_endpoint": f"{base}/revoke",
        "scopes_supported": [MCP_PROMPTS_WRITE_SCOPE],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256"],
        "client_id_metadata_document_supported": True,
    }
