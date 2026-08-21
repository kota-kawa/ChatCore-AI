import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PromptCard, type PromptRecord } from "../components/prompt_share/prompt_card";

const prompt: PromptRecord = {
  id: 7,
  clientId: "prompt-7",
  title: "設計レビューの観点",
  content: "設計をレビューして、懸念点を列挙してください。",
  content_format: "prompt",
  media_type: "text",
  liked: false,
  used_in_chat: false
};

function renderCard(options?: { isMemoSavePending?: boolean; onSaveAsMemo?: (value: PromptRecord) => void }) {
  const noop = vi.fn();
  render(
    <PromptCard
      prompt={prompt}
      isDropdownOpen
      isLikePending={false}
      isLikeEffectActive={false}
      isAddAsTaskPending={false}
      isMemoSavePending={options?.isMemoSavePending ?? false}
      isUseInChatEffectActive={false}
      onOpenDetail={noop}
      onOpenComments={noop}
      onOpenShare={noop}
      onToggleDropdown={noop}
      onCloseDropdown={noop}
      onAddAsTask={noop}
      onSaveAsMemo={options?.onSaveAsMemo ?? noop}
      onToggleLike={noop}
      onOpenAuthorProfile={noop}
    />
  );
}

describe("prompt share card memo action", () => {
  it("メニューの「メモに保存」から対象プロンプトを保存処理へ渡す", () => {
    const onSaveAsMemo = vi.fn();
    renderCard({ onSaveAsMemo });

    fireEvent.click(screen.getByRole("menuitem", { name: "メモに保存" }));

    expect(onSaveAsMemo).toHaveBeenCalledTimes(1);
    expect(onSaveAsMemo).toHaveBeenCalledWith(prompt);
  });

  it("保存中はメニュー項目を無効化して二重送信を防ぐ", () => {
    renderCard({ isMemoSavePending: true });

    expect(screen.getByRole("menuitem", { name: "メモに保存中…" })).toBeDisabled();
  });
});
