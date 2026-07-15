import { resilientFetch } from "../../core/resilient_fetch";
import { extractApiErrorMessage, fetchJsonOrThrow } from "../../core/runtime_validation";
import {
  parseMcpOAuthClientCredentials,
  parseMcpOAuthClientList,
  parseMcpOAuthConnections,
  parseMcpOAuthConsent,
  parseMcpOAuthConsentDecision,
  type McpOAuthClientCredentials,
  type McpOAuthClientList,
  type McpOAuthConnection,
  type McpOAuthConsent
} from "./types";

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
  redirectUri: string | undefined,
  issueClientSecret: boolean
): Promise<McpOAuthClientCredentials> {
  const body = {
    label,
    issue_client_secret: issueClientSecret,
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
