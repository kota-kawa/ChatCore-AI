import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import McpOAuthAuthorizePage from "../pages/oauth/authorize";

const mocks = vi.hoisted(() => ({
  decideMcpOAuthConsent: vi.fn(),
  loadMcpOAuthConsent: vi.fn()
}));

vi.mock("next/router", () => ({
  useRouter: () => ({
    asPath: "/oauth/authorize?request=signed-request",
    isReady: true,
    query: { request: "signed-request" }
  })
}));

vi.mock("../scripts/user/settings/api", () => ({
  McpOAuthApiError: class McpOAuthApiError extends Error {},
  decideMcpOAuthConsent: mocks.decideMcpOAuthConsent,
  loadMcpOAuthConsent: mocks.loadMcpOAuthConsent
}));

describe("McpOAuthAuthorizePage", () => {
  beforeEach(() => {
    mocks.decideMcpOAuthConsent.mockReset();
    mocks.loadMcpOAuthConsent.mockReset();
  });

  it("presents the connection, requested permission, and protected details", async () => {
    mocks.loadMcpOAuthConsent.mockResolvedValue({
      client_name: "Example AI",
      client_id: "https://client.example.test/metadata.json",
      client_host: "client.example.test",
      redirect_host: "client.example.test",
      scope: "prompts:read prompts:write memos:read memos:write",
      localhost_warning: false
    });

    const { container } = render(<McpOAuthAuthorizePage />);

    expect(screen.getByText("連携情報を安全に確認しています…")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Example AI と連携しますか？" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "この連携で許可されること" })).toBeInTheDocument();
    expect(screen.getByText("公開プロンプトとSKILLを検索・閲覧する")).toBeInTheDocument();
    expect(screen.getByText("公開プロンプトを投稿する")).toBeInTheDocument();
    expect(screen.getByText("保存したメモを検索・閲覧する")).toBeInTheDocument();
    expect(screen.getByText("保存したメモを編集する")).toBeInTheDocument();
    expect(screen.getByText("あなたの非公開メモのタイトルと内容を変更できます。")).toBeInTheDocument();
    expect(screen.getByText("この許可はいつでも設定画面の「外部サービス連携」から取り消せます。")).toBeInTheDocument();
    expect(screen.getByText("接続の詳細を表示")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "キャンセル" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "許可して接続" })).toBeInTheDocument();
    expect(container.querySelector(".oauth-authorize-client-icon")).not.toBeInTheDocument();
    expect(container.querySelector(".bi-stars")).not.toBeInTheDocument();
  });

  it.each([
    ["キャンセル", "deny"],
    ["許可して接続", "approve"]
  ] as const)("keeps the %s action working", async (buttonName, decision) => {
    mocks.loadMcpOAuthConsent.mockResolvedValue({
      client_name: "Example AI",
      client_id: "example-client",
      client_host: "client.example.test",
      redirect_host: "client.example.test",
      scope: "prompts:write",
      localhost_warning: false
    });
    mocks.decideMcpOAuthConsent.mockReturnValue(new Promise(() => {}));

    render(<McpOAuthAuthorizePage />);
    const button = await screen.findByRole("button", { name: buttonName });
    fireEvent.click(button);

    expect(mocks.decideMcpOAuthConsent).toHaveBeenCalledWith("signed-request", decision);
  });
});
