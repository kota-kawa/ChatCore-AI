import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SecuritySettingsSection } from "../components/settings/settings_sections";

describe("SecuritySettingsSection MCP connections", () => {
  it("lists an authorized AI service and delegates revocation", () => {
    const onDeleteMcpOAuthConnection = vi.fn();
    const onIssueMcpOAuthClient = vi.fn();
    const onDeleteMcpOAuthClient = vi.fn();
    const onMcpOAuthClientRedirectUriChange = vi.fn();
    render(
      <SecuritySettingsSection
        isActive
        profileEmail="user@example.com"
        emailChangeStatus={null}
        emailChangeStage="idle"
        emailChangeNewEmail=""
        emailChangeCode=""
        emailChangeSubmitting={false}
        passkeySupportStatus="対応しています。"
        passkeySupported
        passkeys={[]}
        passkeysLoading={false}
        registeringPasskey={false}
        deletingPasskeyId={null}
        mcpOAuthConnections={[{
          id: "grant-1",
          client_name: "Example AI",
          client_host: "",
          created_at: "2026-07-13T10:00:00Z",
          last_used_at: null
        }]}
        mcpOAuthConnectionsLoading={false}
        deletingMcpOAuthConnectionId={null}
        mcpOAuthClients={[{
          client_id: "mcp-example-client",
          label: "My connector",
          redirect_uri: "https://client.example.test/oauth/callback",
          created_at: "2026-07-14T10:00:00Z"
        }]}
        mcpOAuthClientsLoading={false}
        mcpOAuthClientIssuing={false}
        mcpOAuthClientLabel=""
        mcpOAuthClientRedirectUri="https://claude.ai/api/mcp/auth_callback"
        deletingMcpOAuthClientId={null}
        mcpOAuthClientCredentials={null}
        accountDeleteConfirmation=""
        accountDeleting={false}
        accountDeleteError={null}
        onRequestEmailChange={vi.fn()}
        onConfirmEmailChange={vi.fn()}
        onCancelEmailChange={vi.fn()}
        onEmailChangeNewEmailChange={vi.fn()}
        onEmailChangeCodeChange={vi.fn()}
        onRegisterPasskey={vi.fn()}
        onRefreshPasskeys={vi.fn()}
        onDeletePasskey={vi.fn()}
        onRefreshMcpOAuthConnections={vi.fn()}
        onDeleteMcpOAuthConnection={onDeleteMcpOAuthConnection}
        onRefreshMcpOAuthClients={vi.fn()}
        onMcpOAuthClientLabelChange={vi.fn()}
        onMcpOAuthClientRedirectUriChange={onMcpOAuthClientRedirectUriChange}
        onIssueMcpOAuthClient={onIssueMcpOAuthClient}
        onDeleteMcpOAuthClient={onDeleteMcpOAuthClient}
        onAccountDeleteConfirmationChange={vi.fn()}
        onDeleteAccount={vi.fn()}
      />
    );

    expect(screen.getByText("Example AI")).toBeInTheDocument();
    expect(screen.getByText("不明")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "連携を解除" }));
    expect(onDeleteMcpOAuthConnection).toHaveBeenCalledWith(expect.objectContaining({ id: "grant-1" }));

    expect(screen.getByText("My connector")).toBeInTheDocument();
    fireEvent.change(
      screen.getByRole("textbox", { name: "コールバックURL（リダイレクトURI）" }),
      { target: { value: "https://client.example.test/changed-callback" } }
    );
    expect(onMcpOAuthClientRedirectUriChange).toHaveBeenCalledWith(
      "https://client.example.test/changed-callback"
    );
    fireEvent.click(screen.getByRole("button", { name: "認証情報を発行" }));
    expect(onIssueMcpOAuthClient).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "削除" }));
    expect(onDeleteMcpOAuthClient).toHaveBeenCalledWith(expect.objectContaining({ client_id: "mcp-example-client" }));
  });
});
