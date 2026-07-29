import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  it("shows its placeholder copy and quick prompts in English", () => {
    renderSupportAgent("en");

    expect(screen.getByText("Navigation assistant")).toBeInTheDocument();
    expect(screen.getByText("Ask for help using this page, choosing your next action, or organizing what to enter.")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask for help with this page")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "What can this service do?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "How do I use this page?" })).toBeInTheDocument();
  });

  it("keeps the Japanese copy when the display language is Japanese", () => {
    renderSupportAgent("ja");

    expect(screen.getByText("操作支援エージェント")).toBeInTheDocument();
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
});
