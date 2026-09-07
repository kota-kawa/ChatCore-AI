import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LocaleProvider } from "../contexts/locale_context";
import {
  PromptCategoryPage,
  type PromptCategoryPageViewProps
} from "../components/prompt_share/prompt_category_page";
import { getPromptCategorySeoCopy } from "../components/prompt_share/prompt_category_seo";
import { PROMPT_CATEGORY_KEYS } from "../scripts/prompt_share/prompt_category_registry";

function renderPage(locale: "ja" | "en", overrides: Partial<PromptCategoryPageViewProps> = {}) {
  const copy = getPromptCategorySeoCopy("coding", locale);
  if (!copy) throw new Error("coding copy is missing");
  const props: PromptCategoryPageViewProps = {
    category: "coding",
    initialPrompts: [{ id: 42, title: "Code review", content: "Review **this** code", category: "coding" }],
    initialLoadFailed: false,
    copy,
    ...overrides
  };
  return render(
    <LocaleProvider initialLocale={locale}>
      <PromptCategoryPage {...props} />
    </LocaleProvider>
  );
}

describe("Prompt category guide page", () => {
  it("renders crawlable Japanese guide and prompt links", () => {
    const { container } = renderPage("ja");
    expect(container.querySelector("h1")?.textContent).toContain("開発・プログラミング");
    expect(container.querySelectorAll(".prompt-category-examples li")).toHaveLength(3);
    expect(container.querySelector('a[href="/prompt_share?category=coding"]')).not.toBeNull();
    expect(container.querySelector('a[href="/shared/prompt/42/code-review"]')).not.toBeNull();
    expect(container.querySelectorAll(".prompt-category-links a")).toHaveLength(PROMPT_CATEGORY_KEYS.length - 1);
  });

  it("localizes page copy and every public URL for English", () => {
    const { container } = renderPage("en");
    expect(container.querySelector("h1")?.textContent).toBe("AI prompts for coding and development");
    expect(container.querySelector('a[href="/en/prompt_share?category=coding"]')).not.toBeNull();
    expect(container.querySelector('a[href="/en/shared/prompt/42/code-review"]')).not.toBeNull();
    expect(container.querySelector('a[href="/en/prompt_share/category/writing"]')).not.toBeNull();
  });

  it("keeps the guide indexable when a category has no public prompts", () => {
    const { container } = renderPage("ja", { initialPrompts: [] });
    expect(container.querySelector(".prompt-category-message")?.textContent).toContain("公開プロンプトがまだありません");
    expect(container.querySelector("h1")).not.toBeNull();
  });

  it("keeps the guide copy visible when the public feed is unavailable", () => {
    const { container } = renderPage("ja", { initialPrompts: [], initialLoadFailed: true });
    expect(container.querySelector(".prompt-category-message--error")?.textContent).toContain("読み込めませんでした");
    expect(container.querySelector(".prompt-category-hero__description")?.textContent).toContain("実装したい機能");
  });
});
