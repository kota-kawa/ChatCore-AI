import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PromptCard, type PromptRecord } from "../components/prompt_share/prompt_card";
import { buildPromptPath } from "../lib/promptSlug";

const PROMPT_ID = 7;

const prompt: PromptRecord = {
  id: PROMPT_ID,
  clientId: "prompt-7",
  title: "設計レビューの観点",
  content: "設計をレビューして、懸念点を列挙してください。",
  content_format: "prompt",
  media_type: "text",
  liked: false,
  used_in_chat: false
};

function renderCard(onOpenDetail = vi.fn()) {
  const noop = vi.fn();
  const view = render(
    <PromptCard
      prompt={prompt}
      isDropdownOpen={false}
      isLikePending={false}
      isLikeEffectActive={false}
      isAddAsTaskPending={false}
      isMemoSavePending={false}
      isUseInChatEffectActive={false}
      onOpenDetail={onOpenDetail}
      onOpenComments={noop}
      onOpenShare={noop}
      onToggleDropdown={noop}
      onCloseDropdown={noop}
      onAddAsTask={noop}
      onSaveAsMemo={noop}
      onToggleLike={noop}
      onOpenAuthorProfile={noop}
    />
  );
  return { container: view.container, onOpenDetail };
}

// フィードから個別ページへの内部リンクが消えるとクローラーの発見経路がsitemapだけになるため、
// タイトルが実リンクであることを固定する。
// Lock in the crawlable title link: without it the feed gives crawlers no internal path to the
// detail pages and discovery depends on the sitemap alone.
describe("prompt_share card detail link", () => {
  it("タイトルを個別ページの正規URLへのリンクとして出力する", () => {
    const { container } = renderCard();

    const link = container.querySelector<HTMLAnchorElement>(".prompt-card > h3 a");
    expect(link).not.toBeNull();
    expect(link?.getAttribute("href")).toBe(buildPromptPath(PROMPT_ID, prompt.title));
    expect(link?.textContent).toBe(prompt.title);
  });

  it("素の左クリックでは遷移せずモーダル表示のままにする", () => {
    const { container, onOpenDetail } = renderCard();

    const link = container.querySelector<HTMLAnchorElement>(".prompt-card > h3 a");
    const clickEvent = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    link?.dispatchEvent(clickEvent);

    expect(clickEvent.defaultPrevented).toBe(true);
    expect(onOpenDetail).toHaveBeenCalledTimes(1);
  });

  it("修飾キー付きクリックはブラウザ既定のリンク遷移に任せる", () => {
    const { container } = renderCard();

    const link = container.querySelector<HTMLAnchorElement>(".prompt-card > h3 a");
    const clickEvent = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      button: 0,
      metaKey: true
    });
    link?.dispatchEvent(clickEvent);

    expect(clickEvent.defaultPrevented).toBe(false);
  });
});
