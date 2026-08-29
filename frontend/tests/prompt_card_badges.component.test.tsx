import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

function renderCard(
  overrides: Partial<PromptRecord> = {},
  options: {
    isDropdownOpen?: boolean;
    isPriorityImage?: boolean;
    isOwnPrompt?: boolean;
    isAddAsTaskPending?: boolean;
    onEdit?: (prompt: PromptRecord) => void;
  } = {}
) {
  const view = render(
    <PromptCard
      prompt={{ ...basePrompt, ...overrides }}
      isPriorityImage={options.isPriorityImage}
      isDropdownOpen={Boolean(options.isDropdownOpen)}
      isLikePending={false}
      isLikeEffectActive={false}
      isAddAsTaskPending={Boolean(options.isAddAsTaskPending)}
      isMemoSavePending={false}
      isUseInChatEffectActive={false}
      isOwnPrompt={options.isOwnPrompt}
      onOpenDetail={noop}
      onOpenComments={noop}
      onOpenShare={noop}
      onToggleDropdown={noop}
      onCloseDropdown={noop}
      onAddAsTask={noop}
      onSaveAsMemo={noop}
      onToggleLike={noop}
      onOpenAuthorProfile={noop}
      onEdit={options.onEdit}
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

  it("SKILL投稿の主操作をSkill追加として表示し、追加済みは再送信できない", () => {
    const container = renderCard({ content_format: "skill", skill_markdown: "# SKILL" });
    const addButton = screen.getByRole("button", { name: "Skillに追加" });
    expect(addButton).toBeInTheDocument();
    expect(addButton).not.toBeDisabled();

    container.remove();
    renderCard({ content_format: "skill", skill_markdown: "# SKILL", added_to_skills: true });
    const addedButton = screen.getByRole("button", { name: "Skillに追加済み" });
    expect(addedButton).toBeDisabled();
    expect(addedButton).toHaveAttribute("aria-pressed", "true");
  });

  it("SKILL追加済みは通常の追加済み状態と同じ塗りつぶしアイコンを使う", () => {
    const container = renderCard({ content_format: "skill", skill_markdown: "# SKILL", added_to_skills: true });
    const addedButton = screen.getByRole("button", { name: "Skillに追加済み" });

    expect(addedButton).toHaveClass("add-to-skill-btn", "added-to-skills");
    expect(container.querySelector(".add-to-skill-btn i")).toHaveClass("bi-plus-square-fill");
  });

  it("通常プロンプトの主操作はチャット利用のまま維持する", () => {
    renderCard();

    expect(screen.getByRole("button", { name: "チャットで使う" })).toBeInTheDocument();
  });

  it("SKILL追加中は専用の状態ラベルを表示する", () => {
    renderCard(
      { content_format: "skill", skill_markdown: "# SKILL" },
      { isAddAsTaskPending: true }
    );

    expect(screen.getByRole("button", { name: "Skillに追加中…" })).toBeDisabled();
  });

  it("画像投稿ではメディアバッジのみを追加する", () => {
    const container = renderCard({ media_type: "image", prompt_type: "image" });

    expect(container.querySelector(".prompt-card__type-pill--image")).toBeInTheDocument();
    expect(container.querySelector(".prompt-card__type-pill--format")).not.toBeInTheDocument();
  });

  it("本人の投稿だけに編集操作を表示し、カードの投稿を渡す", () => {
    const onEdit = vi.fn();
    renderCard({}, { isDropdownOpen: true, isOwnPrompt: true, onEdit });

    fireEvent.click(screen.getByRole("menuitem", { name: "プロンプト編集" }));

    expect(onEdit).toHaveBeenCalledWith(basePrompt);
  });

  it("他ユーザーの投稿には編集操作を表示しない", () => {
    renderCard({}, { isOwnPrompt: false, onEdit: vi.fn() });

    expect(screen.queryByRole("menuitem", { name: "プロンプト編集" })).not.toBeInTheDocument();
  });

  it("管理対象の作例画像はNext Imageで遅延・サイズ最適化される", () => {
    const container = renderCard({
      reference_image_url: "/prompt_share/api/media/example.png",
      media_type: "image",
      prompt_type: "image"
    });

    const image = container.querySelector(".prompt-card__image img");
    expect(image).toHaveAttribute("data-nimg", "fill");
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image?.getAttribute("src")).toContain("/_next/image");
  });

  it("先頭の作例画像だけを優先読み込みできる", () => {
    const container = renderCard(
      { reference_image_url: "/prompt_share/api/media/example.png" },
      { isPriorityImage: true }
    );

    const image = container.querySelector(".prompt-card__image img");
    expect(image).toHaveAttribute("fetchpriority", "high");
    expect(image).toHaveAttribute("loading", "eager");
  });
});
