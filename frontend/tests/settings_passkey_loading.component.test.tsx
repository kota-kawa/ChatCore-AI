import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UserSettingsPage from "../pages/settings";
import { LocaleProvider } from "../contexts/locale_context";

const mocks = vi.hoisted(() => ({
  router: {
    isReady: true,
    query: {} as Record<string, string>,
    pathname: "/settings",
    asPath: "/settings",
    replace: vi.fn().mockResolvedValue(true)
  },
  settingsFetchJsonOrThrow: vi.fn(),
  loadLocalePreference: vi.fn(),
  updateLocalePreference: vi.fn(),
  loadMcpOAuthClients: vi.fn(),
  loadMcpOAuthConnections: vi.fn(),
  browserSupportsPasskeys: vi.fn(),
  registerPasskey: vi.fn(),
  showConfirmModal: vi.fn(),
  showToast: vi.fn(),
  forgetKnownAccount: vi.fn()
}));

vi.mock("next/router", () => ({ useRouter: () => mocks.router }));
vi.mock("../components/SeoHead", () => ({ SeoHead: () => null }));
vi.mock("../scripts/user/settings/api", () => ({
  issueMcpOAuthClient: vi.fn(),
  loadLocalePreference: mocks.loadLocalePreference,
  loadMcpOAuthClients: mocks.loadMcpOAuthClients,
  loadMcpOAuthConnections: mocks.loadMcpOAuthConnections,
  revokeMcpOAuthClient: vi.fn(),
  revokeMcpOAuthConnection: vi.fn(),
  settingsFetchJsonOrThrow: mocks.settingsFetchJsonOrThrow,
  updateMcpOAuthClientLabel: vi.fn(),
  updateMcpOAuthConnectionDisplayName: vi.fn(),
  updateLocalePreference: mocks.updateLocalePreference
}));
vi.mock("../scripts/core/passkeys", () => ({
  PasskeyCancelledError: class PasskeyCancelledError extends Error {},
  browserSupportsPasskeys: mocks.browserSupportsPasskeys,
  registerPasskey: mocks.registerPasskey
}));
vi.mock("../scripts/core/alert_modal", () => ({ showConfirmModal: mocks.showConfirmModal }));
vi.mock("../scripts/core/toast", () => ({ showToast: mocks.showToast }));
vi.mock("../scripts/core/theme", () => ({
  getStoredThemePreference: () => "light",
  setThemePreference: vi.fn()
}));
vi.mock("../lib/auth/account_switcher", () => ({ forgetKnownAccount: mocks.forgetKnownAccount }));

function renderSettings(query: Record<string, string> = {}) {
  mocks.router.query = query;
  mocks.router.asPath = query.section ? `/settings?section=${query.section}` : "/settings";
  return render(<LocaleProvider initialLocale="ja"><UserSettingsPage /></LocaleProvider>);
}

describe("settings passkey loading", () => {
  beforeEach(() => {
    mocks.router.query = {};
    mocks.router.asPath = "/settings";
    mocks.router.replace.mockClear();
    mocks.settingsFetchJsonOrThrow.mockReset();
    mocks.settingsFetchJsonOrThrow.mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/passkeys") {
        return { payload: { passkeys: [{ id: 1, credential_device_type: "singleDevice" }] } };
      }
      if (path === "/api/user/profile") {
        return { payload: { username: "Kota", email: "kota@example.com", bio: "", llm_profile_context: "" } };
      }
      throw new Error(`Unexpected settings request: ${path}`);
    });
    mocks.loadLocalePreference.mockReset().mockResolvedValue("ja");
    mocks.updateLocalePreference.mockReset().mockImplementation(async (locale: string) => locale);
    mocks.loadMcpOAuthClients.mockReset().mockResolvedValue({
      clients: [],
      mcp_server_url: "https://example.test/mcp",
      default_redirect_uri: "https://example.test/callback"
    });
    mocks.loadMcpOAuthConnections.mockReset().mockResolvedValue([]);
    mocks.browserSupportsPasskeys.mockReset().mockReturnValue(true);
    mocks.registerPasskey.mockReset();
    mocks.showConfirmModal.mockReset().mockResolvedValue(false);
    mocks.showToast.mockReset();
    mocks.forgetKnownAccount.mockReset();
  });

  it("loads passkeys once on a direct security URL and refreshes them in the selected locale on revisit", async () => {
    renderSettings({ section: "security" });

    expect(await screen.findByText("保存済みPasskey")).toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.settingsFetchJsonOrThrow.mock.calls.filter(([input]) => String(input) === "/api/passkeys"))
        .toHaveLength(1);
    });

    fireEvent.click(screen.getByRole("button", { name: "言語 / Language" }));
    fireEvent.click(screen.getByRole("radio", { name: /English/ }));
    expect(await screen.findByRole("heading", { name: "Display language" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Security" }));

    expect(await screen.findByText("Saved passkey")).toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.settingsFetchJsonOrThrow.mock.calls.filter(([input]) => String(input) === "/api/passkeys"))
        .toHaveLength(2);
    });
  });

  it("waits for a saved locale that differs from the URL locale and loads passkeys once in that locale", async () => {
    let resolveLocalePreference!: (locale: "ja" | "en") => void;
    mocks.loadLocalePreference.mockReturnValueOnce(new Promise((resolve) => {
      resolveLocalePreference = resolve;
    }));
    renderSettings({ section: "security" });

    expect(screen.getByText("登録済みの端末を確認しています。")).toBeInTheDocument();
    expect(mocks.settingsFetchJsonOrThrow.mock.calls.some(([input]) => String(input) === "/api/passkeys")).toBe(false);

    await act(async () => {
      resolveLocalePreference("en");
    });

    expect(await screen.findByText("Saved passkey")).toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.settingsFetchJsonOrThrow.mock.calls.filter(([input]) => String(input) === "/api/passkeys"))
        .toHaveLength(1);
    });
  });

  it("falls back to the URL locale if loading the saved locale fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.loadLocalePreference.mockRejectedValueOnce(new Error("offline"));
    renderSettings({ section: "security" });

    expect(await screen.findByText("保存済みPasskey")).toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.settingsFetchJsonOrThrow.mock.calls.filter(([input]) => String(input) === "/api/passkeys"))
        .toHaveLength(1);
    });
  });

  it("does not fetch passkeys on the profile section and refreshes them each time security is reopened", async () => {
    renderSettings();

    await waitFor(() => expect(mocks.settingsFetchJsonOrThrow).toHaveBeenCalledWith(
      "/api/user/profile",
      { credentials: "same-origin" },
      expect.any(Object)
    ));
    expect(mocks.settingsFetchJsonOrThrow.mock.calls.some(([input]) => String(input) === "/api/passkeys")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "セキュリティ" }));
    expect(await screen.findByText("保存済みPasskey")).toBeInTheDocument();
    expect(mocks.settingsFetchJsonOrThrow.mock.calls.filter(([input]) => String(input) === "/api/passkeys"))
      .toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "プロフィール設定" }));
    fireEvent.click(screen.getByRole("button", { name: "セキュリティ" }));

    await waitFor(() => {
      expect(mocks.settingsFetchJsonOrThrow.mock.calls.filter(([input]) => String(input) === "/api/passkeys"))
        .toHaveLength(2);
    });
  });
});
