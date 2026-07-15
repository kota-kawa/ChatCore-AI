import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SecuritySettingsSection } from "../components/settings/settings_sections";

describe("SecuritySettingsSection MCP connections", () => {
  it("lists an authorized AI service and delegates revocation", async () => {
    const onDeleteMcpOAuthConnection = vi.fn();
    const onIssueMcpOAuthClient = vi.fn();
    const onDeleteMcpOAuthClient = vi.fn();
    const onMcpOAuthClientLabelChange = vi.fn();
    const onMcpOAuthClientRedirectUriChange = vi.fn();
    const onMcpOAuthClientSecretRequiredChange = vi.fn();
    const onUpdateMcpOAuthConnectionDisplayName = vi.fn().mockResolvedValue(undefined);
    const onUpdateMcpOAuthClientLabel = vi.fn().mockResolvedValue(undefined);
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
          display_name: "仕事用アシスタント",
          created_at: "2026-07-13T10:00:00Z",
          last_used_at: null
        }]}
        mcpOAuthConnectionsLoading={false}
        deletingMcpOAuthConnectionId={null}
        mcpOAuthClients={[{
          client_id: "mcp-example-client",
          label: "My connector",
          redirect_uri: "https://client.example.test/oauth/callback",
          token_endpoint_auth_method: "none",
          created_at: "2026-07-14T10:00:00Z"
        }]}
        mcpOAuthClientsLoading={false}
        mcpOAuthClientIssuing={false}
        mcpOAuthClientLabel="Manual connector"
        mcpOAuthClientRedirectUri="https://client.example.test/callback"
        mcpOAuthClientSecretRequired={false}
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
        onUpdateMcpOAuthConnectionDisplayName={onUpdateMcpOAuthConnectionDisplayName}
        onRefreshMcpOAuthClients={vi.fn()}
        onMcpOAuthClientLabelChange={onMcpOAuthClientLabelChange}
        onMcpOAuthClientRedirectUriChange={onMcpOAuthClientRedirectUriChange}
        onMcpOAuthClientSecretRequiredChange={onMcpOAuthClientSecretRequiredChange}
        onIssueMcpOAuthClient={onIssueMcpOAuthClient}
        onDeleteMcpOAuthClient={onDeleteMcpOAuthClient}
        onUpdateMcpOAuthClientLabel={onUpdateMcpOAuthClientLabel}
        onAccountDeleteConfirmationChange={vi.fn()}
        onDeleteAccount={vi.fn()}
      />
    );

    expect(screen.getByRole("heading", { name: "アカウントを安全に保つ" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "セキュリティ設定内のメニュー" })).toBeInTheDocument();
    const overview = screen.getByRole("list", { name: "セキュリティ設定の概要" });
    expect(within(overview).getByText("設定済み")).toBeInTheDocument();
    expect(within(overview).getByText("未登録")).toBeInTheDocument();
    expect(within(overview).getByText("1件接続")).toBeInTheDocument();
    const emailSteps = screen.getByRole("list", { name: "メールアドレス変更の手順" });
    expect(within(emailSteps).getByText("新しいアドレス")).toBeInTheDocument();
    expect(within(emailSteps).getByText("本人確認")).toBeInTheDocument();
    expect(within(emailSteps).getByText("変更を確定")).toBeInTheDocument();

    expect(screen.getByText("仕事用アシスタント")).toBeInTheDocument();
    expect(screen.getByText("Example AI")).toBeInTheDocument();
    expect(screen.getByText("不明")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Example AIの表示名を編集" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Example AIの表示名" }), {
      target: { value: "個人用アシスタント" }
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(onUpdateMcpOAuthConnectionDisplayName).toHaveBeenCalledWith(
        expect.objectContaining({ id: "grant-1" }),
        "個人用アシスタント"
      );
    });
    fireEvent.click(screen.getByRole("button", { name: "解除" }));
    expect(onDeleteMcpOAuthConnection).toHaveBeenCalledWith(expect.objectContaining({ id: "grant-1" }));

    expect(screen.getByText("My connector")).toBeInTheDocument();
    expect(screen.getByText("対応するMCPクライアントは自動的に認証を設定します。OAuthクライアントIDやシークレットをここで発行する必要はありません。")).toBeInTheDocument();
    fireEvent.click(screen.getByText("手動設定が必要なサービス向けに認証情報を発行"));
    fireEvent.click(screen.getByRole("button", { name: "My connectorの名前を編集" }));
    fireEvent.change(screen.getByRole("textbox", { name: "My connectorの名前" }), {
      target: { value: "開発用コネクター" }
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(onUpdateMcpOAuthClientLabel).toHaveBeenCalledWith(
        expect.objectContaining({ client_id: "mcp-example-client" }),
        "開発用コネクター"
      );
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: /コールバックURL（リダイレクトURI）/ }),
      { target: { value: "https://client.example.test/changed-callback" } }
    );
    expect(onMcpOAuthClientRedirectUriChange).toHaveBeenCalledWith(
      "https://client.example.test/changed-callback"
    );
    fireEvent.change(screen.getByRole("textbox", { name: "認証情報の名前 必須" }), {
      target: { value: "開発用コネクター" }
    });
    expect(onMcpOAuthClientLabelChange).toHaveBeenCalledWith("開発用コネクター");
    fireEvent.click(screen.getByRole("checkbox", { name: "OAuthクライアントシークレットを発行する" }));
    expect(onMcpOAuthClientSecretRequiredChange).toHaveBeenCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "手動用の認証情報を発行" }));
    expect(onIssueMcpOAuthClient).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "削除" }));
    expect(onDeleteMcpOAuthClient).toHaveBeenCalledWith(expect.objectContaining({ client_id: "mcp-example-client" }));
  });
});
