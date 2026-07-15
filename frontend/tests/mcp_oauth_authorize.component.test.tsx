import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import McpOAuthAuthorizePage from "../pages/oauth/authorize";

const mocks = vi.hoisted(() => ({
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
  decideMcpOAuthConsent: vi.fn(),
  loadMcpOAuthConsent: mocks.loadMcpOAuthConsent
}));

describe("McpOAuthAuthorizePage", () => {
  it("presents the connection, requested permission, and protected details", async () => {
    mocks.loadMcpOAuthConsent.mockResolvedValue({
      client_name: "Example AI",
      client_id: "https://client.example.test/metadata.json",
      client_host: "client.example.test",
      redirect_host: "client.example.test",
      scope: "prompts:write",
      localhost_warning: false
    });

    render(<McpOAuthAuthorizePage />);

    expect(screen.getByText("連携情報を安全に確認しています…")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Example AI")).toBeInTheDocument();
    });

    expect(screen.getByRole("heading", { name: "AIサービス連携の確認" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "公開プロンプトを投稿する" })).toBeInTheDocument();
    expect(screen.getByText("この許可はいつでも設定画面の「外部サービス連携」から取り消せます。")).toBeInTheDocument();
    expect(screen.getByText("接続の詳細を表示")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接続しない" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "許可して接続" })).toBeInTheDocument();
  });
});
