import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SecuritySettingsSection } from "../components/settings/settings_sections";

describe("SecuritySettingsSection MCP connections", () => {
  it("lists an authorized AI service and delegates revocation", () => {
    const onDeleteMcpOAuthConnection = vi.fn();
    const onIssueClaudeOAuthClient = vi.fn();
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
          client_host: "ai.example.com",
          created_at: "2026-07-13T10:00:00Z",
          last_used_at: null
        }]}
        mcpOAuthConnectionsLoading={false}
        deletingMcpOAuthConnectionId={null}
        claudeOAuthClient={null}
        claudeOAuthClientLoading={false}
        claudeOAuthClientIssuing={false}
        claudeOAuthClientCredentials={null}
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
        onIssueClaudeOAuthClient={onIssueClaudeOAuthClient}
        onAccountDeleteConfirmationChange={vi.fn()}
        onDeleteAccount={vi.fn()}
      />
    );

    expect(screen.getByText("Example AI")).toBeInTheDocument();
    expect(screen.getByText(/ai\.example\.com/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "連携を解除" }));
    expect(onDeleteMcpOAuthConnection).toHaveBeenCalledWith(expect.objectContaining({ id: "grant-1" }));
    fireEvent.click(screen.getByRole("button", { name: "Claude用認証情報を発行" }));
    expect(onIssueClaudeOAuthClient).toHaveBeenCalledOnce();
  });
});
