// 投稿カードのキーボード操作を検証する。
// Tests prompt card keyboard behavior.

import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PromptCard, type PromptRecord } from "../components/prompt_share/prompt_card";

const prompt: PromptRecord = {
  id: 42,
  clientId: "prompt-42",
  title: "キーボード操作の確認",
  content: "キーボードだけでカードを開けるか確認する。",
  content_format: "prompt",
  media_type: "text",
  liked: false,
  used_in_chat: false
};

function renderCard(onOpenDetail = vi.fn(), { isDropdownOpen = false, onCloseDropdown = vi.fn() } = {}) {
  const noop = vi.fn();
  const view = render(
    <PromptCard
      prompt={prompt}
      isDropdownOpen={isDropdownOpen}
      isLikePending={false}
      isLikeEffectActive={false}
      isAddAsTaskPending={false}
      isMemoSavePending={false}
      isUseInChatEffectActive={false}
      onOpenDetail={onOpenDetail}
      onOpenComments={noop}
      onOpenShare={noop}
      onToggleDropdown={noop}
      onCloseDropdown={onCloseDropdown}
      onAddAsTask={noop}
      onSaveAsMemo={noop}
      onToggleLike={noop}
      onOpenAuthorProfile={noop}
    />
  );
  return { container: view.container, onOpenDetail };
}

// キーボードのみの利用者が主要フィードのカードから詳細モーダルを開けることを固定する。
// Lock in that keyboard-only users can open the detail modal from the main feed card.
describe("prompt_share card keyboard access", () => {
  it("role=buttonとtabIndexを持ち、EnterまたはSpaceで詳細を開く", () => {
    const { container, onOpenDetail } = renderCard();
    const card = container.querySelector<HTMLDivElement>(".prompt-card");

    expect(card?.getAttribute("role")).toBe("button");
    expect(card?.getAttribute("tabindex")).toBe("0");

    card?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" }));
    expect(onOpenDetail).toHaveBeenCalledTimes(1);

    card?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: " " }));
    expect(onOpenDetail).toHaveBeenCalledTimes(2);
  });

  it("カード内のボタンからバブリングしたキー操作では詳細を開かない", () => {
    const { container, onOpenDetail } = renderCard();
    const menuButton = container.querySelector<HTMLButtonElement>(".meatball-menu");

    menuButton?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" }));

    expect(onOpenDetail).not.toHaveBeenCalled();
  });

  // 開いたメニューは Escape で閉じ、開く「…」ボタンへフォーカスが戻る。
  // Escape closes the open menu and returns focus to the "…" button that opened it.
  it("Escapeでメニューを閉じ、開くボタンへフォーカスを戻す", () => {
    const onCloseDropdown = vi.fn();
    const { container } = renderCard(vi.fn(), { isDropdownOpen: true, onCloseDropdown });
    const menuButton = container.querySelector<HTMLButtonElement>(".meatball-menu");
    container.querySelector<HTMLElement>(".prompt-actions-dropdown button")?.focus();

    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

    expect(onCloseDropdown).toHaveBeenCalledTimes(1);
    expect(menuButton).toHaveFocus();
  });

  it("メニューが閉じているときのEscapeでは何も起きない", () => {
    const onCloseDropdown = vi.fn();
    renderCard(vi.fn(), { onCloseDropdown });

    fireEvent.keyDown(document.body, { key: "Escape" });

    expect(onCloseDropdown).not.toHaveBeenCalled();
  });
});
