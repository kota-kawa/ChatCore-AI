import { resilientFetch } from "../../core/resilient_fetch";
import { extractApiErrorMessage, fetchJsonOrThrow } from "../../core/runtime_validation";
import {
  parseClaudeOAuthClientCredentials,
  parseClaudeOAuthClientStatus,
  parseMcpOAuthConnections,
  parseMcpOAuthConsent,
  parseMcpOAuthConsentDecision,
  type ClaudeOAuthClientCredentials,
  type ClaudeOAuthClientStatus,
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

export async function loadClaudeOAuthClientStatus(): Promise<ClaudeOAuthClientStatus> {
  const payload = await fetchMcpOauthJson("/api/mcp/oauth/claude-client", {
    credentials: "same-origin"
  });
  return parseClaudeOAuthClientStatus(payload);
}

export async function issueClaudeOAuthClient(): Promise<ClaudeOAuthClientCredentials> {
  const payload = await fetchMcpOauthJson("/api/mcp/oauth/claude-client", {
    method: "POST",
    credentials: "same-origin"
  });
  return parseClaudeOAuthClientCredentials(payload);
}
