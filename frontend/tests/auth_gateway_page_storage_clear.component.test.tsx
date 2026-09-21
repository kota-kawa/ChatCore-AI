import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/font/local", () => ({ default: () => ({ style: { fontFamily: "mock" } }) }));
vi.mock("next/router", () => ({
  useRouter: () => ({
    asPath: "/login",
    pathname: "/login",
    isReady: true,
    query: {},
    push: vi.fn(),
    prefetch: vi.fn(),
    replace: vi.fn(),
  }),
}));
vi.mock("../scripts/core/csrf", () => ({ ensureCsrfProtection: vi.fn() }));
vi.mock("../scripts/core/passkeys", () => ({
  authenticateWithPasskey: vi.fn(),
  browserSupportsPasskeys: vi.fn(() => false),
  registerPasskey: vi.fn(),
  PasskeyCancelledError: class PasskeyCancelledError extends Error {},
}));
vi.mock("../scripts/core/resilient_fetch", () => ({ resilientFetch: vi.fn() }));

import AuthGatewayPage from "../components/auth/auth_gateway_page";
import { authenticateWithPasskey, browserSupportsPasskeys } from "../scripts/core/passkeys";
import { resilientFetch } from "../scripts/core/resilient_fetch";

const fetchMock = vi.mocked(resilientFetch);
const authenticateWithPasskeyMock = vi.mocked(authenticateWithPasskey);
const browserSupportsPasskeysMock = vi.mocked(browserSupportsPasskeys);

function jsonResponse(payload: unknown, redirected = false) {
  return {
    ok: true,
    status: 200,
    redirected,
    url: "",
    headers: { get: () => "application/json" },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  } as unknown as Response;
}

const PRIVATE_ROOM_KEY = "chatHistory_room-of-user-1";

function seedPreviousUserStorage() {
  localStorage.setItem("chatcore.chat.userScope", "user:1");
  localStorage.setItem("chatcore.auth.loggedIn", "1");
  localStorage.setItem("chatcore.chat.activeRoomId", "room-of-user-1");
  localStorage.setItem(PRIVATE_ROOM_KEY, JSON.stringify([{ text: "USER 1 PRIVATE MESSAGE", sender: "user" }]));
}

function expectPreviousUserStorageCleared() {
  expect(localStorage.getItem(PRIVATE_ROOM_KEY)).toBeNull();
  expect(localStorage.getItem("chatcore.chat.activeRoomId")).toBeNull();
  expect(localStorage.getItem("chatcore.chat.userScope")).toBeNull();
}

// 認証に成功する経路は必ずこのページ（/login, /register 双方が使う
// AuthGatewayPage）を経由してホームへリダイレクトされる。ユーザー切替は
// ログアウトを経由しない場合でも必ずログインを経由するため、この3つの
// リダイレクト地点（メールコード認証・パスキーログイン・既ログイン検知）の
// 直前で前の利用者の永続状態を消せば、ホーム画面がそれを誤って復元することは
// なくなる。
// Every successful authentication path redirects home through this page
// (used by both /login and /register). A user switch always goes through
// login even when it skips logout, so clearing the previous user's persisted
// state right before each of these three redirect points (email code
// verification, passkey login, and detecting an existing session) means the
// home page can never restore it by mistake.
describe("auth gateway clears previous-user storage before redirecting home", () => {
  it("clears storage when the email verification code succeeds", async () => {
    seedPreviousUserStorage();
    browserSupportsPasskeysMock.mockReturnValue(false);

    fetchMock.mockImplementation(async (url: unknown) => {
      const requestedUrl = String(url);
      if (requestedUrl.includes("current_user")) return jsonResponse({ logged_in: false });
      if (requestedUrl.includes("send_email_code")) return jsonResponse({ status: "success" });
      if (requestedUrl.includes("verify_email_code")) {
        return jsonResponse({ status: "success", flow: "login", offer_passkey_setup: false });
      }
      return jsonResponse({});
    });

    const user = userEvent.setup();
    render(<AuthGatewayPage />);

    // マウント時の「既にログイン済みか」確認（未ログイン）が解決するのを待つ。
    // Wait for the mount-time "already logged in?" check (not logged in) to resolve.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const emailInput = document.querySelector<HTMLInputElement>("#email")!;
    await user.type(emailInput, "user2@example.com");
    await user.click(screen.getByRole("button", { name: "認証コードを送信" }));

    await waitFor(() => expect(document.querySelector("#authCode")).not.toBeNull());

    const codeInput = document.querySelector<HTMLInputElement>("#authCode")!;
    await user.type(codeInput, "123456");

    // まだ本文は消えていない（認証コードを検証するまでは何もしない）。
    // Not cleared yet (nothing happens until the code is actually verified).
    expect(localStorage.getItem(PRIVATE_ROOM_KEY)).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "認証して続ける" }));

    await waitFor(() => expectPreviousUserStorageCleared());
  });

  it("clears storage when passkey login succeeds", async () => {
    seedPreviousUserStorage();
    browserSupportsPasskeysMock.mockReturnValue(true);
    authenticateWithPasskeyMock.mockResolvedValue({});

    fetchMock.mockImplementation(async (url: unknown) => {
      const requestedUrl = String(url);
      if (requestedUrl.includes("current_user")) return jsonResponse({ logged_in: false });
      return jsonResponse({});
    });

    const user = userEvent.setup();
    render(<AuthGatewayPage />);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    await user.click(screen.getByRole("button", { name: "Passkeyでログイン" }));

    await waitFor(() => expectPreviousUserStorageCleared());
  });

  it("clears storage when the mount check finds an already-authenticated session", async () => {
    seedPreviousUserStorage();
    browserSupportsPasskeysMock.mockReturnValue(false);

    fetchMock.mockImplementation(async (url: unknown) => {
      const requestedUrl = String(url);
      if (requestedUrl.includes("current_user")) return jsonResponse({ logged_in: true, user: { id: 2 } });
      return jsonResponse({});
    });

    render(<AuthGatewayPage />);

    await waitFor(() => expectPreviousUserStorageCleared());
  });
});
