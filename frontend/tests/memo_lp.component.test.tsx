import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MEMO_LP_FAQ_ITEMS, MEMO_LP_FAQ_ITEMS_EN, MemoLpFaq } from "../components/memo_lp/memo_lp_faq";
import { MemoLpHeader } from "../components/memo_lp/memo_lp_header";
import { MemoLpScope } from "../components/memo_lp/memo_lp_scope";
import { MemoLpValue } from "../components/memo_lp/memo_lp_value";
import { LocaleProvider } from "../contexts/locale_context";
import { buildMemoLpStructuredData } from "../pages/memo/lp";
import type { Locale } from "../lib/i18n/config";

type BreadcrumbEntry = { "@type": string; itemListElement?: Array<{ name: string }> };

function breadcrumbNames(locale: Locale) {
  const entries = buildMemoLpStructuredData(locale, "title", "description") as BreadcrumbEntry[];
  const breadcrumb = entries.find((entry) => entry["@type"] === "BreadcrumbList");
  return breadcrumb?.itemListElement?.map((item) => item.name);
}

function renderWithLocale(locale: Locale, node: React.ReactNode) {
  return render(<LocaleProvider initialLocale={locale}>{node}</LocaleProvider>);
}

// ブランドマークはメモ画面と同じアイコンで、このページ唯一の画像
// The brand mark reuses the memo screen's icon and is the only image on the page
describe("Memo LP header", () => {
  it("uses the memo service icon as the only image", () => {
    const { container } = renderWithLocale("ja", <MemoLpHeader />);
    const images = container.querySelectorAll("img");
    expect(images.length).toBe(1);
    expect(images[0].getAttribute("src")).toBe("/static/chatcore-memo.png");
    // 装飾なので代替テキストは空にする / Decorative, so the alt text stays empty
    expect(images[0].getAttribute("alt")).toBe("");
  });
});

// 共有の公開範囲と制限は、対応範囲セクションで必ず先に見せる
// The sharing scope and the limits must always be stated up front in the scope section
describe("Memo LP scope section", () => {
  it("states the 30 day share link expiry and the missing revoke control", () => {
    const { container } = renderWithLocale("ja", <MemoLpScope />);
    const limits = Array.from(container.querySelectorAll(".mslp-limits li")).map((item) => item.textContent);
    expect(limits.some((limit) => limit?.includes("30日で期限切れ"))).toBe(true);
    expect(limits.some((limit) => limit?.includes("取り消しボタンは、まだメモ画面にありません"))).toBe(true);
  });

  it("lists every sort option and export format offered by the memo screen", () => {
    const { container } = renderWithLocale("ja", <MemoLpScope />);
    const chips = Array.from(container.querySelectorAll(".mslp-chips li")).map((chip) => chip.textContent);
    expect(chips).toEqual([
      "手動順",
      "新しい順",
      "更新順",
      "古い順",
      "タイトル順",
      "AI類似検索",
      "Markdown",
      "JSON",
      "CSV"
    ]);
  });

  it("localizes the scope section for English", () => {
    const { container } = renderWithLocale("en", <MemoLpScope />);
    const chips = Array.from(container.querySelectorAll(".mslp-chips li")).map((chip) => chip.textContent);
    expect(chips).toContain("AI similarity");
    expect(container.querySelector(".lp-heading")?.textContent).toBe(
      "A memo is private until you hand out a link."
    );
  });
});

// 見出しは狭い画面用の改行 (.lp-br-sp) を挟むため、英語では単語が連結しないことを確認する
// The headings insert a narrow-screen break (.lp-br-sp), so verify English words never run together
describe("Memo LP headings", () => {
  it("keeps the English heading as one readable sentence", () => {
    const { container } = renderWithLocale("en", <MemoLpValue />);
    expect(container.querySelector(".lp-heading")?.textContent).toBe("Capture it, organize it, come back to it.");
  });

  it("keeps the narrow-screen break for the Japanese heading", () => {
    const { container } = renderWithLocale("ja", <MemoLpValue />);
    const heading = container.querySelector(".lp-heading");
    expect(heading?.querySelector("br.lp-br-sp")).not.toBeNull();
    expect(heading?.textContent).toBe("残して、整えて、見返す。");
  });
});

// FAQはJSON-LDと表示の両方で同じデータを使うので、件数と本文が一致することを確認する
// The FAQ feeds both JSON-LD and the visible list, so the count and text must match
describe("Memo LP FAQ", () => {
  it("renders every FAQ item that also feeds the structured data", () => {
    const { container } = renderWithLocale("ja", <MemoLpFaq />);
    const questions = Array.from(container.querySelectorAll(".lp-faq__question")).map((item) => item.textContent);
    expect(questions).toEqual(MEMO_LP_FAQ_ITEMS.map((item) => item.question));
  });

  it("keeps the Japanese and English FAQ lists the same length", () => {
    expect(MEMO_LP_FAQ_ITEMS_EN.length).toBe(MEMO_LP_FAQ_ITEMS.length);
  });
});

// パンくずのJSON-LDは /lp と同じくロケールに追従させる
// The breadcrumb JSON-LD must follow the locale, matching /lp
describe("Memo LP structured data", () => {
  it("localizes the breadcrumb names for English", () => {
    expect(breadcrumbNames("en")).toEqual(["Home", "Memos", "About memos"]);
  });

  it("keeps Japanese breadcrumb names for Japanese", () => {
    expect(breadcrumbNames("ja")).toEqual(["ホーム", "メモ", "メモとは"]);
  });

  it("localizes the FAQ entries", () => {
    const [faq] = buildMemoLpStructuredData("en", "title", "description").filter(
      (entry) => entry["@type"] === "FAQPage"
    ) as Array<{ mainEntity: Array<{ name: string }> }>;
    expect(faq.mainEntity[0].name).toBe("Can other people see my memos?");
  });
});
