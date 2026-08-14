import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatLpScope } from "../components/chat_lp/chat_lp_scope";
import { ChatLpValue } from "../components/chat_lp/chat_lp_value";
import { LocaleProvider } from "../contexts/locale_context";
import { MODEL_OPTIONS } from "../lib/chat_page/constants";
import { buildChatLpStructuredData } from "../pages/chat/lp";
import type { Locale } from "../lib/i18n/config";

type BreadcrumbEntry = { "@type": string; itemListElement?: Array<{ name: string }> };

function breadcrumbNames(locale: Locale) {
  const entries = buildChatLpStructuredData(locale, "title", "description") as BreadcrumbEntry[];
  const breadcrumb = entries.find((entry) => entry["@type"] === "BreadcrumbList");
  return breadcrumb?.itemListElement?.map((item) => item.name);
}

function renderWithLocale(locale: Locale, node: React.ReactNode) {
  return render(<LocaleProvider initialLocale={locale}>{node}</LocaleProvider>);
}

// 紹介ページのモデル一覧は、チャット画面と同じ定数から描く
// The model list on the landing page must come from the same constant as the chat screen
describe("Chat LP scope section", () => {
  it("lists every selectable model", () => {
    const { container } = renderWithLocale("ja", <ChatLpScope />);
    const chips = container.querySelectorAll(".cslp-chips li");
    expect(chips.length).toBe(MODEL_OPTIONS.length);
    expect(Array.from(chips).map((chip) => chip.textContent)).toContain("GPT-OSS 120B（高速応答）");
  });

  it("localizes the model hints for English", () => {
    const { container } = renderWithLocale("en", <ChatLpScope />);
    const chips = Array.from(container.querySelectorAll(".cslp-chips li")).map((chip) => chip.textContent);
    expect(chips).toContain("GPT-OSS 120B (fast responses)");
  });

  // サンドボックスの制約は宣伝より先に出す約束なので、制限リストから消えていないことを確認する
  // The sandbox limits are promised up front, so make sure the limits list still states them
  it("states the sandbox limits up front", () => {
    const { container } = renderWithLocale("ja", <ChatLpScope />);
    const limits = Array.from(container.querySelectorAll(".cslp-limits li")).map((item) => item.textContent ?? "");
    expect(limits.some((limit) => limit.includes("サンドボックス"))).toBe(true);
    expect(limits.some((limit) => limit.includes("Three.js"))).toBe(true);
  });
});

// 見出しは狭い画面用の改行 (.lp-br-sp) を挟むため、英語では単語が連結しないことを確認する
// The headings insert a narrow-screen break (.lp-br-sp), so verify English words never run together
describe("Chat LP headings", () => {
  it("keeps the English heading as one readable sentence", () => {
    const { container } = renderWithLocale("en", <ChatLpValue />);
    expect(container.querySelector(".lp-heading")?.textContent).toBe("Launch it, render it, keep it.");
  });

  it("keeps the narrow-screen break for the Japanese heading", () => {
    const { container } = renderWithLocale("ja", <ChatLpValue />);
    const heading = container.querySelector(".lp-heading");
    expect(heading?.querySelector("br.lp-br-sp")).not.toBeNull();
    expect(heading?.textContent).toBe("押して呼び出し、描かせて、残す。");
  });
});

// パンくずとFAQのJSON-LDは /prompt_share/lp と同じくロケールに追従させる
// The breadcrumb and FAQ JSON-LD must follow the locale, matching /prompt_share/lp
describe("Chat LP structured data", () => {
  it("localizes the breadcrumb names for English", () => {
    expect(breadcrumbNames("en")).toEqual(["Home", "About AI chat"]);
  });

  it("keeps Japanese breadcrumb names for Japanese", () => {
    expect(breadcrumbNames("ja")).toEqual(["ホーム", "AIチャットとは"]);
  });

  it("localizes the FAQ entries", () => {
    const [faq] = buildChatLpStructuredData("en", "title", "description").filter(
      (entry) => entry["@type"] === "FAQPage"
    ) as Array<{ mainEntity: Array<{ name: string }> }>;
    expect(faq.mainEntity[0].name).toBe("Can I use it without an account?");
    expect(faq.mainEntity.length).toBe(5);
  });
});
