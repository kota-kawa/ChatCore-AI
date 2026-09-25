import { resilientFetch } from "../../core/resilient_fetch";
import { extractApiErrorMessage, fetchJsonOrThrow } from "../../core/runtime_validation";
import {
  parseMcpOAuthClientCredentials,
  parseMcpOAuthClientList,
  parseMcpOAuthConnections,
  parseMcpOAuthConsent,
  parseMcpOAuthConsentDecision,
  parseUsageLimits,
  type McpOAuthClientCredentials,
  type McpOAuthClientList,
  type McpOAuthConnection,
  type McpOAuthConsent,
  type UsageLimits
} from "./types";
import { normalizeLocale, type Locale } from "../../../lib/i18n/config";
import {
  ToolAutoApprovalRevokeResponseSchema,
  ToolAutoApprovalsResponseSchema,
  type ToolAutoApprovalApi,
} from "../../../types/generated/api_schemas";

export function settingsFetchJsonOrThrow<TPayload>(
  input: RequestInfo | URL,
  init?: RequestInit,
  options?: Parameters<typeof fetchJsonOrThrow<TPayload>>[2],
) {
  return fetchJsonOrThrow<TPayload>(input, init, {
    ...options,
    fetchImpl: resilientFetch,
  });
}

export async function loadLocalePreference(): Promise<Locale> {
  const { payload } = await settingsFetchJsonOrThrow<Record<string, unknown>>(
    "/api/user/preferences",
    { credentials: "same-origin" },
    { defaultMessage: "表示言語の取得に失敗しました。" }
  );
  const locale = normalizeLocale(payload.locale);
  if (!locale) throw new Error("Unsupported locale returned by preferences API");
  return locale;
}

export async function loadUsageLimits(): Promise<UsageLimits> {
  const { payload } = await settingsFetchJsonOrThrow<Record<string, unknown>>(
    "/api/user/usage-limits",
    { credentials: "same-origin" },
    { defaultMessage: "利用状況の取得に失敗しました。" }
  );
  return parseUsageLimits(payload);
}

export async function updateLocalePreference(locale: Locale): Promise<Locale> {
  const { payload } = await settingsFetchJsonOrThrow<Record<string, unknown>>(
    "/api/user/preferences",
    {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locale })
    },
    { defaultMessage: "表示言語の保存に失敗しました。" }
  );
  const savedLocale = normalizeLocale(payload.locale);
  if (!savedLocale) throw new Error("Unsupported locale returned by preferences API");
  return savedLocale;
}

// チャットで「常に承認」にしたツールの一覧。/ Tools the user set to "always approve" in chat.
export async function loadToolAutoApprovals(defaultMessage: string): Promise<ToolAutoApprovalApi[]> {
  const { payload } = await settingsFetchJsonOrThrow<unknown>(
    "/api/chat/tool-auto-approvals",
    { credentials: "same-origin" },
    { defaultMessage }
  );
  const parsed = ToolAutoApprovalsResponseSchema.safeParse(payload);
  if (!parsed.success) throw new Error(defaultMessage);
  return parsed.data.grants ?? [];
}

// 「常に承認」を取り消す。付与が無くても成功する（冪等）。/ Revoke "always approve"; succeeds even without a grant (idempotent).
export async function revokeToolAutoApproval(toolName: string, defaultMessage: string): Promise<boolean> {
  const { payload } = await settingsFetchJsonOrThrow<unknown>(
    `/api/chat/tool-auto-approvals/${encodeURIComponent(toolName)}`,
    { method: "DELETE", credentials: "same-origin" },
    { defaultMessage }
  );
  const parsed = ToolAutoApprovalRevokeResponseSchema.safeParse(payload);
  if (!parsed.success) throw new Error(defaultMessage);
  return parsed.data.revoked;
}

export class McpOAuthApiError extends Error {
  public readonly status: number;

  public constructor(message: string, status: number) {
    super(message);
    this.name = "McpOAuthApiError";
    this.status = status;
  }
}

async function fetchMcpOauthJson(input: RequestInfo | URL, init?: RequestInit): Promise<unknown> {
  const response = await resilientFetch(input, init);
  const payload: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new McpOAuthApiError(
      extractApiErrorMessage(payload, "AIサービス連携の操作に失敗しました。", response.status),
      response.status
    );
  }
  return payload;
}

export async function loadMcpOAuthConsent(request: string): Promise<McpOAuthConsent> {
  const payload = await fetchMcpOauthJson(
    `/api/mcp/oauth/consent?${new URLSearchParams({ request }).toString()}`,
    { credentials: "same-origin" }
  );
  return parseMcpOAuthConsent(payload);
}

export async function decideMcpOAuthConsent(
  request: string,
  decision: "approve" | "deny"
): Promise<string> {
  const payload = await fetchMcpOauthJson("/api/mcp/oauth/consent", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request, decision })
  });
  return parseMcpOAuthConsentDecision(payload);
}

export async function loadMcpOAuthConnections(): Promise<McpOAuthConnection[]> {
  const payload = await fetchMcpOauthJson("/api/mcp/oauth/connections", {
    credentials: "same-origin"
  });
  return parseMcpOAuthConnections(payload);
}

export async function revokeMcpOAuthConnection(connectionId: string): Promise<void> {
  await fetchMcpOauthJson(`/api/mcp/oauth/connections/${encodeURIComponent(connectionId)}`, {
    method: "DELETE",
    credentials: "same-origin"
  });
}

export async function updateMcpOAuthConnectionDisplayName(
  connectionId: string,
  displayName: string
): Promise<void> {
  await fetchMcpOauthJson(`/api/mcp/oauth/connections/${encodeURIComponent(connectionId)}`, {
    method: "PATCH",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName })
  });
}

export async function loadMcpOAuthClients(): Promise<McpOAuthClientList> {
  const payload = await fetchMcpOauthJson("/api/mcp/oauth/clients", {
    credentials: "same-origin"
  });
  return parseMcpOAuthClientList(payload);
}

export async function issueMcpOAuthClient(
  label: string,
  redirectUri: string | undefined
): Promise<McpOAuthClientCredentials> {
  const body = {
    label,
    ...(redirectUri ? { redirect_uri: redirectUri } : {})
  };
  const payload = await fetchMcpOauthJson("/api/mcp/oauth/clients", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  return parseMcpOAuthClientCredentials(payload);
}

export async function revokeMcpOAuthClient(clientId: string): Promise<void> {
  await fetchMcpOauthJson(`/api/mcp/oauth/clients/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
    credentials: "same-origin"
  });
}

export async function updateMcpOAuthClientLabel(clientId: string, label: string): Promise<void> {
  await fetchMcpOauthJson(`/api/mcp/oauth/clients/${encodeURIComponent(clientId)}`, {
    method: "PATCH",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label })
  });
}
