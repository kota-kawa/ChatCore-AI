import { waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const resilientFetchMock = vi.hoisted(() => vi.fn());
vi.mock("../scripts/core/resilient_fetch", () => ({ resilientFetch: resilientFetchMock }));

import { setLoggedInState } from "../scripts/core/app_state";

const KNOWN_ACCOUNTS_KEY = "chatcore.accountSwitcher.knownAccounts";
const PRIVATE_ROOM_KEY = "chatHistory_room-of-user-1";

const CURRENT = { user_id: 1, username: "Alice", email: "alice@example.com", avatar_url: "/a.png", current: true };
const PARKED = { user_id: 2, username: "Bob", email: "bob@example.com", avatar_url: "", current: false };
const SIGNED_OUT = { userId: 3, username: "", email: "carol@example.com", avatarUrl: "" };

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function mockApi({ switchStatus = 200 } = {}) {
  resilientFetchMock.mockImplementation(async (url: unknown) => {
    const requestedUrl = String(url);
    if (requestedUrl === "/api/user/profile") return jsonResponse(CURRENT);
    if (requestedUrl === "/api/auth/accounts") return jsonResponse({ accounts: [CURRENT, PARKED] });
    if (requestedUrl === "/api/auth/accounts/switch") return jsonResponse({}, switchStatus);
    return jsonResponse({});
  });
}

async function openMenu() {
  await import("../scripts/components/user_icon");
  const element = document.createElement("user-icon");
  document.body.append(element);
  setLoggedInState(true);
  const shadow = element.shadowRoot as ShadowRoot;
  (shadow.querySelector(".btn") as HTMLButtonElement).click();
  await waitFor(() => expect(shadow.querySelectorAll(".account-row").length).toBeGreaterThan(0));
  return shadow;
}

// 右上メニューから、このブラウザでログインしたことのあるアカウントへ切り替えられることを確認する。
// The top-right menu lets the user switch to accounts that have signed in on this browser.
describe("user menu account switcher", () => {
  beforeEach(() => {
    localStorage.clear();
    resilientFetchMock.mockReset();
    document.documentElement.lang = "ja";
  });

  afterEach(() => {
    setLoggedInState(false);
    document.body.innerHTML = "";
  });

  it("lists signed-in accounts as switch buttons and remembered ones as sign-in links", async () => {
    localStorage.setItem(KNOWN_ACCOUNTS_KEY, JSON.stringify([SIGNED_OUT]));
    mockApi();

    const shadow = await openMenu();

    expect(shadow.querySelector(".current")).toHaveTextContent("Alice");
    expect(shadow.querySelector(".current")).toHaveTextContent("alice@example.com");
    const rows = shadow.querySelectorAll(".account-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelector("button.account")).toHaveAttribute("aria-label", "Bobに切り替える");
    const signedOutLink = rows[1].querySelector("a.account");
    expect(signedOutLink).toHaveAttribute("href", "/login?add_account=1&email=carol%40example.com");
    expect(signedOutLink).toHaveTextContent("ログアウト済み");
    expect(shadow.querySelector(".item-add-account")).toHaveAttribute("href", "/login?add_account=1");
    // ログイン中と確認できたアカウントは、ログアウト後も一覧に出せるよう控えに残す
    // Accounts confirmed as signed in are recorded so they still show after sign-out
    const known = JSON.parse(localStorage.getItem(KNOWN_ACCOUNTS_KEY) || "[]") as Array<{ userId: number }>;
    expect(known.map((account) => account.userId)).toEqual([1, 2, 3]);
  });

  it("switches to a signed-in account and wipes the outgoing user's local data", async () => {
    localStorage.setItem(PRIVATE_ROOM_KEY, JSON.stringify([{ text: "ALICE PRIVATE", sender: "user" }]));
    localStorage.setItem("chatcore.chat.userScope", "user:1");
    mockApi();

    const shadow = await openMenu();
    (shadow.querySelector("button.account") as HTMLButtonElement).click();

    await waitFor(() => expect(localStorage.getItem(PRIVATE_ROOM_KEY)).toBeNull());
    expect(resilientFetchMock).toHaveBeenCalledWith(
      "/api/auth/accounts/switch",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ user_id: 2 }) })
    );
    expect(localStorage.getItem("chatcore.chat.userScope")).toBeNull();
    expect(localStorage.getItem("chatcore.userIcon.avatarUrl")).toBeNull();
    expect(localStorage.getItem(KNOWN_ACCOUNTS_KEY)).not.toBeNull();
  });

  it("keeps the current user's local data and shows an error when the switch fails", async () => {
    localStorage.setItem(PRIVATE_ROOM_KEY, JSON.stringify([{ text: "ALICE PRIVATE", sender: "user" }]));
    mockApi({ switchStatus: 503 });

    const shadow = await openMenu();
    const error = shadow.querySelector(".switch-error") as HTMLElement;
    expect(error.hidden).toBe(true);
    (shadow.querySelector("button.account") as HTMLButtonElement).click();

    await waitFor(() => expect(error.hidden).toBe(false));
    expect(error).toHaveTextContent("切り替えられませんでした");
    expect(shadow.querySelector("button.account")).not.toHaveAttribute("aria-busy");
    expect(localStorage.getItem(PRIVATE_ROOM_KEY)).not.toBeNull();
  });

  it("keeps the current user's local data when the target account is signed out on the server", async () => {
    localStorage.setItem(PRIVATE_ROOM_KEY, JSON.stringify([{ text: "ALICE PRIVATE", sender: "user" }]));
    mockApi({ switchStatus: 404 });

    const shadow = await openMenu();
    const button = shadow.querySelector("button.account") as HTMLButtonElement;
    button.click();

    await waitFor(() =>
      expect(resilientFetchMock).toHaveBeenCalledWith("/api/auth/accounts/switch", expect.anything())
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect((shadow.querySelector(".switch-error") as HTMLElement).hidden).toBe(true);
    expect(localStorage.getItem(PRIVATE_ROOM_KEY)).not.toBeNull();
  });

  it("removes a signed-out account from the list on request", async () => {
    localStorage.setItem(KNOWN_ACCOUNTS_KEY, JSON.stringify([SIGNED_OUT]));
    mockApi();

    const shadow = await openMenu();
    const remove = shadow.querySelector(".account-remove") as HTMLButtonElement;
    expect(remove).toHaveAttribute("aria-label", "carol@example.comを一覧から削除");
    remove.click();

    expect(shadow.querySelectorAll(".account-row")).toHaveLength(1);
    expect(localStorage.getItem(KNOWN_ACCOUNTS_KEY)).not.toContain("carol@example.com");
    expect((shadow.querySelector(".dropdown") as HTMLElement).style.display).toBe("flex");
  });
});
