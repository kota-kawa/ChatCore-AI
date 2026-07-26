import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LikedPromptCard, PromptCard } from "../components/settings/prompt_cards";
import { PromptPreviewModal } from "../components/settings/prompt_preview_modal";
import type { LikedPrompt, PromptRecord } from "../scripts/user/settings/types";

const authoredPrompt: PromptRecord = {
  id: "prompt-1",
  title: "会議メモを要約する",
  category: "business",
  content: "会議メモを要点、決定事項、次のアクションに分けて要約してください。",
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
  inputExamples: authoredPrompt.inputExamples,
  outputExamples: authoredPrompt.outputExamples,
  createdAt: "2026-07-26T09:00:00Z",
  likedAt: "2026-07-26T10:00:00Z"
};

describe("設定画面のプロンプトカード詳細", () => {
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
});
