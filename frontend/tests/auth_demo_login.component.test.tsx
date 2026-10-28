import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/font/local", () => ({ default: () => ({ style: { fontFamily: "mock" } }) }));
vi.mock("next/router", () => ({
  useRouter: () => ({ asPath: "/login", pathname: "/login", isReady: true, query: {}, push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() }),
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
import { resilientFetch } from "../scripts/core/resilient_fetch";

const fetchMock = vi.mocked(resilientFetch);

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    redirected: false,
    url: "",
    headers: { get: () => "application/json" },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  } as unknown as Response;
}

async function renderLoginPage(demoLoginResponse: Response) {
  fetchMock.mockImplementation(async (url: unknown) => {
    const requestedUrl = String(url);
    if (requestedUrl.includes("current_user")) return jsonResponse({ logged_in: false });
    if (requestedUrl.includes("demo-login")) return demoLoginResponse;
    return jsonResponse({});
  });
  render(<AuthGatewayPage />);
  // マウント時の「既にログイン済みか」確認が解決するのを待つ / Wait for the mount-time "already logged in?" check
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const demoLoginCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).includes("demo-login"));

describe("demo code sign-in on the login page", () => {
  afterEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("keeps the submit button disabled while the code is empty", async () => {
    await renderLoginPage(jsonResponse({}));
    const submit = screen.getByRole("button", { name: "デモを始める" });
    expect(submit).toBeDisabled();

    await userEvent.setup().type(screen.getByLabelText("デモコード"), "   ");
    expect(submit).toBeDisabled();
    expect(demoLoginCalls()).toHaveLength(0);
  });

  it("posts the trimmed code and, on success, clears the previous user's data before heading home", async () => {
    localStorage.setItem("chatcore.chat.userScope", "user:1");
    await renderLoginPage(jsonResponse({ status: "success", expires_at: "2026-11-27T00:00:00+09:00" }));

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("デモコード"), "  demo-ab3k-x9qa-7mpz ");
    await user.click(screen.getByRole("button", { name: "デモを始める" }));

    await waitFor(() => expect(localStorage.getItem("chatcore.chat.userScope")).toBeNull());
    const [[url, init]] = demoLoginCalls();
    expect(url).toBe("/api/auth/demo-login");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ code: "demo-ab3k-x9qa-7mpz" });
    expect(await screen.findByText("ログインしています")).toBeInTheDocument();
  });

  it("shows the server's message inline for a rejected code and lets the user retry", async () => {
    await renderLoginPage(jsonResponse({ error: "このデモコードは終了しています。" }, 401));

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("デモコード"), "demo-old");
    await user.click(screen.getByRole("button", { name: "デモを始める" }));

    expect(await screen.findByText("このデモコードは終了しています。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "デモを始める" })).toBeEnabled();
  });
});
