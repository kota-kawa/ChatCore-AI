import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PromptCard, type PromptRecord } from "../components/prompt_share/prompt_card";

const noop = () => {};

const basePrompt: PromptRecord = {
  id: 7,
  clientId: "prompt-7",
  title: "設計レビューの観点を洗い出す",
  content: "設計ドキュメントを受け取り、レビュー観点を列挙してください。",
  category: "coding",
  author: "Kota",
  author_user_id: 42,
  author_avatar_url: "",
  content_format: "prompt",
  media_type: "text",
  prompt_type: "text",
  liked: false,
  used_in_chat: false,
  comment_count: 0,
  created_at: "2026-06-01T00:00:00Z"
};

function renderCard(overrides: Partial<PromptRecord> = {}) {
  const view = render(
    <PromptCard
      prompt={{ ...basePrompt, ...overrides }}
      isDropdownOpen={false}
      isLikePending={false}
      isLikeEffectActive={false}
      isAddAsTaskPending={false}
      isUseInChatEffectActive={false}
      onOpenDetail={noop}
      onOpenComments={noop}
      onOpenShare={noop}
      onToggleDropdown={noop}
      onCloseDropdown={noop}
      onAddAsTask={noop}
      onToggleLike={noop}
      onOpenAuthorProfile={noop}
    />
  );
  return view.container;
}

// 狭い画面でカテゴリ名が潰れないよう、既定値のバッジは出さない仕様を固定する
// Locks in the rule that default badges are omitted so the category name survives on narrow screens
describe("prompt_share card badges", () => {
  it("既定のプロンプト×テキスト投稿ではカテゴリバッジだけを表示する", () => {
    const container = renderCard();

    expect(container.querySelector(".prompt-card__category-pill span")).toHaveTextContent("開発・プログラミング");
    expect(container.querySelectorAll(".prompt-card__type-pill")).toHaveLength(0);
  });

  it("SKILL投稿ではフォーマットバッジのみを追加する", () => {
    const container = renderCard({ content_format: "skill", skill_markdown: "# SKILL" });

    expect(container.querySelector(".prompt-card__type-pill--skill")).toBeInTheDocument();
    expect(container.querySelector(".prompt-card__type-pill--media")).not.toBeInTheDocument();
  });

  it("画像投稿ではメディアバッジのみを追加する", () => {
    const container = renderCard({ media_type: "image", prompt_type: "image" });

    expect(container.querySelector(".prompt-card__type-pill--image")).toBeInTheDocument();
    expect(container.querySelector(".prompt-card__type-pill--format")).not.toBeInTheDocument();
  });
});
