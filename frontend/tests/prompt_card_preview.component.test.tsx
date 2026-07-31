import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LikedPromptCard, PromptCard } from "../components/settings/prompt_cards";
import { PromptCategorySelect } from "../components/settings/prompt_category_select";
import { PromptPreviewModal } from "../components/settings/prompt_preview_modal";
import { parseMyPromptsResponse, type LikedPrompt, type PromptRecord } from "../scripts/user/settings/types";

const authoredPrompt: PromptRecord = {
  id: "prompt-1",
  title: "会議メモを要約する",
  category: "business",
  content: "会議メモを要点、決定事項、次のアクションに分けて要約してください。",
  contentFormat: "prompt",
  skillMarkdown: "",
  inputExamples: "会議メモの本文",
  outputExamples: "要点: ...",
  createdAt: "2026-07-26T09:00:00Z"
};

const likedPrompt: LikedPrompt = {
  id: "liked-1",
  likeId: "like-1",
  promptId: "prompt-1",
  prompt: authoredPrompt,
  title: authoredPrompt.title,
  category: authoredPrompt.category,
  content: authoredPrompt.content,
  contentFormat: authoredPrompt.contentFormat,
  skillMarkdown: authoredPrompt.skillMarkdown,
  inputExamples: authoredPrompt.inputExamples,
  outputExamples: authoredPrompt.outputExamples,
  createdAt: "2026-07-26T09:00:00Z",
  likedAt: "2026-07-26T10:00:00Z"
};

describe("設定画面のプロンプトカード詳細", () => {
  it("カテゴリ選択メニューで選択肢を読みやすく表示して変更できる", () => {
    const onChange = vi.fn();
    render(
      <PromptCategorySelect
        selectId="category-test"
        value="business"
        disabled={false}
        onChange={onChange}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "カテゴリを選択" }));
    const listbox = screen.getByRole("listbox", { name: "カテゴリを選択" });
    expect(listbox).toBeInTheDocument();
    fireEvent.click(within(listbox).getByRole("option", { name: "文章作成" }));
    expect(onChange).toHaveBeenCalledWith("writing");
  });

  it("Skill形式の本文を一覧レスポンスから保持する", () => {
    const [skillPrompt] = parseMyPromptsResponse({
      prompts: [{
        id: "skill-1",
        title: "議事録整形 SKILL",
        category: "business",
        content: "",
        content_format: "skill",
        skill_markdown: "# 議事録整形\n\n## 手順\n1. 決定事項を抽出する",
        input_examples: "",
        output_examples: "",
        created_at: "2026-07-26T09:00:00Z"
      }]
    });

    expect(skillPrompt).toMatchObject({
      contentFormat: "skill",
      skillMarkdown: "# 議事録整形\n\n## 手順\n1. 決定事項を抽出する"
    });
  });

  it("投稿したプロンプトの本文領域をクリック・キーボード操作で開ける", () => {
    const onPreview = vi.fn();
    const onEdit = vi.fn();
    const onDelete = vi.fn();
    render(
      <PromptCard
        prompt={authoredPrompt}
        onPreview={onPreview}
        onEdit={onEdit}
        onDelete={onDelete}
      />
    );

    const previewButton = screen.getByRole("button", { name: "「会議メモを要約する」の詳細を表示" });
    fireEvent.click(previewButton);
    fireEvent.keyDown(previewButton, { key: " " });
    expect(onPreview).toHaveBeenCalledTimes(2);
    expect(onPreview).toHaveBeenLastCalledWith(authoredPrompt);

    fireEvent.click(screen.getByRole("button", { name: "編集" }));
    fireEvent.click(screen.getByRole("button", { name: "削除" }));
    expect(onEdit).toHaveBeenCalledWith(authoredPrompt);
    expect(onDelete).toHaveBeenCalledWith(authoredPrompt);
  });

  it("プロンプト共有ページと同じバッジ構成でカードを表示する", () => {
    const { container } = render(
      <PromptCard
        prompt={authoredPrompt}
        onPreview={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(container.querySelector(".prompt-card__category-pill")?.textContent).toContain("仕事・ビジネス");
    expect(container.querySelector(".prompt-card__type-pill--format")?.textContent).toContain("プロンプト");
    expect(container.querySelector(".prompt-card__created-at")?.textContent).toBeTruthy();
    // 共有ページのカードと同じく、本文プレビューだけを見せて入出力例はモーダルへ委ねる
    // Like the share page card, only the content preview is shown; examples stay in the modal
    expect(container.querySelector(".prompt-card__content")?.textContent).toContain("会議メモを要点");
    expect(container.querySelector(".prompt-card__preview-sections")).toBeNull();
  });

  it("いいねしたプロンプトのカードには「いいね済み」バッジを表示しない", () => {
    const { container } = render(
      <LikedPromptCard entry={likedPrompt} onPreview={vi.fn()} onDelete={vi.fn()} />
    );

    expect(container.querySelector(".prompt-card__type-pill--saved")).toBeNull();
    expect(screen.queryByText("いいね済み")).not.toBeInTheDocument();
    expect(container.querySelector(".prompt-card__category-pill")?.textContent).toContain("仕事・ビジネス");
  });

  it("いいねしたプロンプトも同じ詳細導線を提供する", () => {
    const onPreview = vi.fn();
    const onDelete = vi.fn();
    render(<LikedPromptCard entry={likedPrompt} onPreview={onPreview} onDelete={onDelete} />);

    fireEvent.keyDown(screen.getByRole("button", { name: "「会議メモを要約する」の詳細を表示" }), { key: "Enter" });
    expect(onPreview).toHaveBeenCalledWith(likedPrompt);

    fireEvent.click(screen.getByRole("button", { name: "いいねを解除" }));
    expect(onDelete).toHaveBeenCalledWith(likedPrompt);
  });

  it("閲覧モーダルに本文・入出力例を表示して閉じられる", () => {
    const onClose = vi.fn();
    render(<PromptPreviewModal prompt={authoredPrompt} source="authored" onClose={onClose} />);

    expect(screen.getByRole("dialog", { name: "会議メモを要約する" })).toBeInTheDocument();
    expect(screen.getByText("会議メモを要点、決定事項、次のアクションに分けて要約してください。")).toBeInTheDocument();
    expect(screen.getByText("会議メモの本文")).toBeInTheDocument();
    expect(screen.getByText("要点: ...")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "詳細を閉じる" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("Skill形式ではSKILL定義を本文として表示する", () => {
    const skillPrompt: PromptRecord = {
      ...authoredPrompt,
      title: "議事録整形 SKILL",
      content: "",
      contentFormat: "skill",
      skillMarkdown: "# 議事録整形\n\n## 手順\n1. 決定事項を抽出する",
      inputExamples: "",
      outputExamples: ""
    };
    render(<PromptPreviewModal prompt={skillPrompt} source="liked" onClose={vi.fn()} />);

    expect(screen.getByText("SKILL定義")).toBeInTheDocument();
    expect(screen.getByText(/決定事項を抽出する/)).toBeInTheDocument();
    expect(screen.queryByText("入出力例")).not.toBeInTheDocument();
  });
});
