import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PromptShareLpScope } from "../components/prompt_share_lp/prompt_share_lp_scope";
import { PromptShareLpValue } from "../components/prompt_share_lp/prompt_share_lp_value";
import { LocaleProvider } from "../contexts/locale_context";
import { PROMPT_CATEGORY_KEYS } from "../scripts/prompt_share/prompt_category_registry";
import { buildPromptShareLpStructuredData } from "../pages/prompt_share/lp";
import type { Locale } from "../lib/i18n/config";

type BreadcrumbEntry = { "@type": string; itemListElement?: Array<{ name: string }> };

function breadcrumbNames(locale: Locale) {
  const entries = buildPromptShareLpStructuredData(locale, "title", "description") as BreadcrumbEntry[];
  const breadcrumb = entries.find((entry) => entry["@type"] === "BreadcrumbList");
  return breadcrumb?.itemListElement?.map((item) => item.name);
}

function renderWithLocale(locale: Locale, node: React.ReactNode) {
  return render(<LocaleProvider initialLocale={locale}>{node}</LocaleProvider>);
}

// 紹介ページのカテゴリ一覧は、実際の絞り込みUIと同じレジストリから描く
// The category list on the landing page must come from the same registry as the real filter UI
describe("Prompt share LP scope section", () => {
  it("lists every registered category", () => {
    const { container } = renderWithLocale("ja", <PromptShareLpScope />);
    const chips = container.querySelectorAll(".pslp-chips li");
    expect(chips.length).toBe(PROMPT_CATEGORY_KEYS.length);
    expect(Array.from(chips).map((chip) => chip.textContent)).toContain("文章作成");
  });

  it("localizes the category labels for English", () => {
    const { container } = renderWithLocale("en", <PromptShareLpScope />);
    const chips = Array.from(container.querySelectorAll(".pslp-chips li")).map((chip) => chip.textContent);
    expect(chips).toContain("Writing");
  });

  it("explains that reusable SKILLs and generated images can be shared", () => {
    const { container } = renderWithLocale(
      "ja",
      <>
        <PromptShareLpValue />
        <PromptShareLpScope />
      </>
    );
    const copy = container.textContent ?? "";
    expect(copy).toContain("SKILL");
    expect(copy).toContain("画像生成で作成した画像");
    expect(copy).toContain("共有できます");
  });
});

// 見出しは狭い画面用の改行 (.lp-br-sp) を挟むため、英語では単語が連結しないことを確認する
// The headings insert a narrow-screen break (.lp-br-sp), so verify English words never run together
describe("Prompt share LP headings", () => {
  it("keeps the English heading as one readable sentence", () => {
    const { container } = renderWithLocale("en", <PromptShareLpValue />);
    expect(container.querySelector(".lp-heading")?.textContent).toBe("Find it, use it, publish it.");
  });

  it("keeps the narrow-screen break for the Japanese heading", () => {
    const { container } = renderWithLocale("ja", <PromptShareLpValue />);
    const heading = container.querySelector(".lp-heading");
    expect(heading?.querySelector("br.lp-br-sp")).not.toBeNull();
    expect(heading?.textContent).toBe("探して、使って、出す。それだけです。");
  });
});

// パンくずのJSON-LDは /lp と同じくロケールに追従させる
// The breadcrumb JSON-LD must follow the locale, matching /lp
describe("Prompt share LP structured data", () => {
  it("localizes the breadcrumb names for English", () => {
    expect(breadcrumbNames("en")).toEqual(["Home", "Prompt library", "About the prompt library"]);
  });

  it("keeps Japanese breadcrumb names for Japanese", () => {
    expect(breadcrumbNames("ja")).toEqual(["ホーム", "プロンプト共有", "プロンプト共有とは"]);
  });

  it("localizes the FAQ entries", () => {
    const [faq] = buildPromptShareLpStructuredData("en", "title", "description").filter(
      (entry) => entry["@type"] === "FAQPage"
    ) as Array<{ mainEntity: Array<{ name: string }> }>;
    expect(faq.mainEntity[0].name).toBe("Can I use it without an account?");
  });
});
