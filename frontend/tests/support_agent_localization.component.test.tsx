import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const resilientFetchMock = vi.hoisted(() => vi.fn());
const showConfirmModalMock = vi.hoisted(() => vi.fn(async () => true));

vi.mock("../scripts/core/resilient_fetch", () => ({ resilientFetch: resilientFetchMock }));
vi.mock("../scripts/core/alert_modal", () => ({ showConfirmModal: showConfirmModalMock }));

vi.mock("next/router", () => ({
  useRouter: () => ({ asPath: "/", pathname: "/", isReady: true, query: {}, push: vi.fn(), prefetch: vi.fn() })
}));

import { MiniChat } from "../components/chat_page/MiniChat";
import { LocaleProvider } from "../contexts/locale_context";
import { LOCALE_CHANGE_EVENT, type Locale } from "../lib/i18n/config";

const JAPANESE = /[぀-ヿ一-龯]/;

function renderSupportAgent(locale: Locale) {
  // 左下のサポートエージェントは props を渡さずに MiniChat を描画するため、
  // 既定の文言がそのまま英語UIに出る。
  // The support agent in the bottom-left corner renders MiniChat without any props, so its
  // default copy is exactly what the English UI shows.
  return render(<LocaleProvider initialLocale={locale}><MiniChat /></LocaleProvider>);
}

describe("support agent localization", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    resilientFetchMock.mockResolvedValue(new Response(
      'event: done\ndata: {"response":"Concise answer","model":"openai/gpt-oss-120b"}\n\n',
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    ));
  });

  it("shows its placeholder copy and quick prompts in English", () => {
    const { container } = renderSupportAgent("en");

    expect(container.querySelector('img[src="/static/Chaco.png"]')).toBeInTheDocument();
    expect(screen.getByText("Chaco")).toBeInTheDocument();
    expect(screen.getByText("Ask for help using this page, choosing your next action, or organizing what to enter.")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask for help with this page").tagName).toBe("TEXTAREA");
    expect(screen.getByRole("button", { name: "What can this service do?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "How do I use this page?" })).toBeInTheDocument();
  });

  it("uses the memo mascot for the welcome state and assistant replies when requested", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <LocaleProvider initialLocale="en">
        <MiniChat agentIconPath="/static/ChacoMemo.png" quickPrompts={["Summarize"]} persistConversation={false} />
      </LocaleProvider>,
    );

    expect(container.querySelector('.mini-chat-placeholder img[src="/static/ChacoMemo.png"]')).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Summarize" }));
    await screen.findByText("Concise answer");
    expect(container.querySelector('.mini-chat-message--assistant img[src="/static/ChacoMemo.png"]')).toBeInTheDocument();
  });

  it("keeps the Japanese copy when the display language is Japanese", () => {
    renderSupportAgent("ja");

    expect(screen.getByText("チャコ")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "このサービスはどんなことができる？" })).toBeInTheDocument();
  });

  // 既定文言との一致で英訳を差し替える方式は、日本語を少し直すだけで英語UIが
  // 日本語に戻る。英語表示に日本語が一切残らないことで担保する。
  // Substituting English by comparing against the Japanese default reverts the English UI
  // the moment that default is edited. Guard it by asserting no Japanese survives.
  it("leaves no Japanese in the English support agent", () => {
    const { container } = renderSupportAgent("en");

    const leaked = Array.from(container.querySelectorAll("button, p, h3, h4, textarea, [aria-label]"))
      .flatMap((element) => [element.textContent ?? "", element.getAttribute("aria-label") ?? "", element.getAttribute("placeholder") ?? ""])
      .filter((text) => JAPANESE.test(text));

    expect(leaked).toEqual([]);
  });

  it("sends a suggested message immediately without showing the response model", async () => {
    const user = userEvent.setup();
    renderSupportAgent("en");

    await user.click(screen.getByRole("button", { name: "What can this service do?" }));

    await screen.findByText("Concise answer");
    expect(screen.queryByText("Model: gpt-oss-120b · Groq")).not.toBeInTheDocument();
    expect(resilientFetchMock).toHaveBeenCalledOnce();
    const requestBody = JSON.parse(String(resilientFetchMock.mock.calls[0][1].body));
    expect(requestBody.messages.at(-1)).toEqual({ role: "user", content: "What can this service do?" });
  });

  it("explains when older messages fall outside the 20-message context window", async () => {
    window.sessionStorage.setItem(
      "globalAiAgent.messages",
      JSON.stringify(Array.from({ length: 20 }, (_, index) => ({
        id: `stored-${index}`,
        sender: index % 2 === 0 ? "user" : "assistant",
        text: `Stored message ${index + 1}`,
      }))),
    );
    window.sessionStorage.setItem("globalAiAgent.messagesTimestamp", String(Date.now()));

    renderSupportAgent("en");

    expect(await screen.findByText(
      "Only the latest 20 messages are sent as context. Older messages remain visible but are no longer included.",
    )).toBeInTheDocument();
  });

  it("uses Enter to send, keeps Shift+Enter for a new line, and confirms clearing", async () => {
    const user = userEvent.setup();
    renderSupportAgent("en");
    const input = screen.getByLabelText("Message to AI support");

    await user.type(input, "First line{shift>}{enter}{/shift}Second line");
    expect(input).toHaveValue("First line\nSecond line");
    await user.type(input, "{enter}");
    await screen.findByText("Concise answer");

    const clearButton = screen.getByRole("button", { name: "Clear conversation" });
    expect(clearButton).toHaveClass("mini-chat-clear-btn--icon-only");
    expect(clearButton.querySelector("span")).toBeNull();

    await user.click(clearButton);
    await waitFor(() => expect(showConfirmModalMock).toHaveBeenCalledWith("Clear this conversation? This cannot be undone."));
    expect(screen.getByText("Chaco")).toBeInTheDocument();
  });
});

describe("user menu localization", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    document.documentElement.lang = "";
  });

  // user-icon は React ツリーの外で動く Web Component のため、カタログを直接引き、
  // 言語切り替えイベントで貼り直す必要がある。
  // user-icon is a Web Component living outside the React tree, so it has to read the
  // catalogue itself and re-apply its copy when the language changes.
  it("renders the settings and logout entries in the active language and follows a switch", async () => {
    document.documentElement.lang = "en";
    await import("../scripts/components/user_icon");

    const element = document.createElement("user-icon");
    document.body.append(element);
    const shadow = element.shadowRoot;

    expect(shadow?.querySelector('a[href="/settings"]')).toHaveTextContent("Settings");
    expect(shadow?.querySelector('a[href="/logout"]')).toHaveTextContent("Log out");
    expect(shadow?.querySelector(".btn")).toHaveAttribute("aria-label", "Open the account menu");

    document.documentElement.lang = "ja";
    window.dispatchEvent(new CustomEvent(LOCALE_CHANGE_EVENT, { detail: { locale: "ja" } }));

    expect(shadow?.querySelector('a[href="/settings"]')).toHaveTextContent("設定");
    expect(shadow?.querySelector('a[href="/logout"]')).toHaveTextContent("ログアウト");
  });

  // ログアウト後も同一端末の次の利用者にチャット全文が残るのが本バグの本体。
  // クリックした結果、会話全文・生成状態・下書き・タスクキャッシュ・アクティブ
  // ルームの指し先・認証キャッシュのすべてが消えることを確認する。
  // The core bug: without this, the next person on this device could still see
  // the previous user's full chat text after logout. Verify the click wipes the
  // chat text, generation state, drafts, task cache, the active-room pointer and
  // the auth cache all at once.
  it("wipes every locally persisted chat state on logout", async () => {
    localStorage.clear();
    localStorage.setItem("chatHistory_room-a", JSON.stringify([{ text: "secret answer", sender: "bot" }]));
    localStorage.setItem("chatGeneration_room-a", JSON.stringify({
      roomId: "room-a",
      roomMode: "normal",
      lastEventId: 1,
      streamedText: "still streaming",
      updatedAt: Date.now(),
    }));
    localStorage.setItem("chatcore.chat.activeRoomId", "room-a");
    localStorage.setItem("chatcore.chat.activeRoomMode", "normal");
    localStorage.setItem("chatcore.home.viewState", "chat");
    localStorage.setItem("chatcore.setup.infoDraft", "unsent draft");
    localStorage.setItem("chatcore.tasks.v3.list", "[]");
    localStorage.setItem("chatcore.auth.loggedIn", "1");
    localStorage.setItem("chatcore.auth.cachedAt", String(Date.now()));

    resilientFetchMock.mockResolvedValue(new Response(null, { status: 200 }));

    document.documentElement.lang = "en";
    await import("../scripts/components/user_icon");
    const element = document.createElement("user-icon");
    document.body.append(element);
    const logoutAnchor = element.shadowRoot?.querySelector('a[href="/logout"]') as HTMLAnchorElement;

    logoutAnchor.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    await waitFor(() => expect(resilientFetchMock).toHaveBeenCalledWith("/logout", expect.objectContaining({ method: "POST" })));

    expect(localStorage.getItem("chatHistory_room-a")).toBeNull();
    expect(localStorage.getItem("chatGeneration_room-a")).toBeNull();
    expect(localStorage.getItem("chatcore.chat.activeRoomId")).toBeNull();
    expect(localStorage.getItem("chatcore.chat.activeRoomMode")).toBeNull();
    expect(localStorage.getItem("chatcore.home.viewState")).toBeNull();
    expect(localStorage.getItem("chatcore.setup.infoDraft")).toBeNull();
    expect(localStorage.getItem("chatcore.tasks.v3.list")).toBeNull();
    expect(localStorage.getItem("chatcore.auth.loggedIn")).toBeNull();
    expect(localStorage.getItem("chatcore.auth.cachedAt")).toBeNull();
  });
});
