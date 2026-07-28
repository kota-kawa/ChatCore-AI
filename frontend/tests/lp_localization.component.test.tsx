import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LpFeatures } from "../components/lp/lp_features";
import { LpFinalCta } from "../components/lp/lp_footer";
import { LocaleProvider } from "../contexts/locale_context";
import { buildLpStructuredData } from "../pages/lp";
import type { Locale } from "../lib/i18n/config";

type BreadcrumbEntry = { "@type": string; itemListElement?: Array<{ name: string }> };

function breadcrumbNames(locale: Locale) {
  const entries = buildLpStructuredData(locale, "title", "description") as BreadcrumbEntry[];
  const breadcrumb = entries.find((entry) => entry["@type"] === "BreadcrumbList");
  return breadcrumb?.itemListElement?.map((item) => item.name);
}

function renderWithLocale(locale: Locale, node: React.ReactNode) {
  return render(<LocaleProvider initialLocale={locale}>{node}</LocaleProvider>);
}

// 見出しは狭い画面用の改行 (.lp-br-sp) を挟むため、英語では単語が連結しないことを確認する
// The headings insert a narrow-screen break (.lp-br-sp), so verify English words never run together
describe("LP headings", () => {
  it("keeps English feature heading words separated", () => {
    const { container } = renderWithLocale("en", <LpFeatures />);
    expect(container.querySelector(".lp-heading")?.textContent).toBe("Three essential tools in one workspace.");
  });

  it("keeps English final CTA heading words separated", () => {
    const { container } = renderWithLocale("en", <LpFinalCta />);
    expect(container.querySelector(".lp-final-cta__title")?.textContent).toBe(
      "Turn today’s questions into useful knowledge."
    );
  });

  it("keeps the narrow-screen break for Japanese headings", () => {
    const { container } = renderWithLocale("ja", <LpFeatures />);
    const heading = container.querySelector(".lp-heading");
    expect(heading?.querySelector("br.lp-br-sp")).not.toBeNull();
    expect(heading?.textContent).toBe("ひとつのワークスペースに、3つの道具。");
  });
});

// パンくずのJSON-LDは /help・/privacy・/terms と同じくロケールに追従させる
// The breadcrumb JSON-LD must follow the locale, matching /help, /privacy, and /terms
describe("LP structured data", () => {
  it("localizes the breadcrumb names for English", () => {
    expect(breadcrumbNames("en")).toEqual(["Home", "About ChatCore-AI"]);
  });

  it("keeps Japanese breadcrumb names for Japanese", () => {
    expect(breadcrumbNames("ja")).toEqual(["ホーム", "ChatCore-AIとは"]);
  });

  it("localizes the FAQ entries", () => {
    const [faq] = buildLpStructuredData("en", "title", "description").filter(
      (entry) => entry["@type"] === "FAQPage"
    ) as Array<{ mainEntity: Array<{ name: string }> }>;
    expect(faq.mainEntity[0].name).toBe("Is ChatCore-AI free?");
  });
});
