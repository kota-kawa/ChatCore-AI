import { render } from "@testing-library/react";
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
});
