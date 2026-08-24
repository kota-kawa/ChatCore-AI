import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { PromptShareDetailModal } from "../components/prompt_share/prompt_share_detail_modal";
import type { PromptRecord } from "../components/prompt_share/prompt_card";

const noop = () => {};

// activeView/onClose以外はどのテストでも同じ形なので共通のダミーpropsとしてまとめる
// Every test shares the same shape for everything besides the prompt itself, so bundle it as common dummy props
function renderDetailModal(detailPrompt: PromptRecord) {
  return render(
    <PromptShareDetailModal
      isOpen
      isLoggedIn
      activeView="detail"
      promptDetailModalRef={createRef<HTMLDivElement>()}
      commentsSectionRef={createRef<HTMLElement>()}
      commentTextareaRef={createRef<HTMLTextAreaElement>()}
      detailPrompt={detailPrompt}
      detailComments={[]}
      isDetailCommentsLoading={false}
      isCommentSubmitting={false}
      commentDraft=""
      commentActionPendingIds={new Set<string>()}
      promptDetailCloseButtonRef={createRef<HTMLButtonElement>()}
      onActiveViewChange={noop}
      onCommentDraftChange={noop}
      onSubmitComment={noop}
      onDeleteComment={noop}
      onReportComment={noop}
      onReloadComments={noop}
      onClose={noop}
      onOpenAuthorProfile={noop}
    />
  );
}

const basePrompt: PromptRecord = {
  id: 12,
  clientId: "prompt-12",
  title: "要件定義書のたたき台を作るプロンプト",
  content: "",
  category: "business",
  author: "Kota",
  content_format: "prompt",
  media_type: "text",
  prompt_type: "text",
  liked: false,
  used_in_chat: false,
  comment_count: 0,
  created_at: "2026-06-01T00:00:00Z"
};

describe("プロンプト詳細モーダルのMarkdown整形", () => {
  it("Markdown記法を含む本文を見出し・強調として整形する", () => {
    renderDetailModal({
      ...basePrompt,
      content: "# 出力形式\n\n**箇条書き**でまとめてください。"
    });

    expect(screen.getByRole("heading", { level: 1, name: "出力形式" })).toBeInTheDocument();
    expect(screen.getByText("箇条書き").tagName).toBe("STRONG");
  });

  it("Markdown記法を含まない本文はそのまま段落として表示する", () => {
    renderDetailModal({
      ...basePrompt,
      content: "会議メモを要約してください。"
    });

    expect(screen.getByText("会議メモを要約してください。")).toBeInTheDocument();
  });

  it("説明を本文より前にプレーンテキストで表示する", () => {
    const { container } = renderDetailModal({
      ...basePrompt,
      description: "# 説明\n用途を短く紹介",
      content: "本文"
    });

    const description = container.querySelector(".prompt-detail-description");
    const body = screen.getByText("本文");
    expect(description?.tagName).toBe("P");
    expect(description?.textContent).toBe("# 説明\n用途を短く紹介");
    const bodySection = body.closest(".prompt-detail-section--body");
    expect(description?.closest(".prompt-detail-section")?.compareDocumentPosition(bodySection as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  });

  it("Skill形式の本文もMarkdownとして整形する", () => {
    renderDetailModal({
      ...basePrompt,
      content_format: "skill",
      skill_markdown: "## 手順\n1. 決定事項を抽出する"
    });

    expect(screen.getByRole("heading", { level: 2, name: "手順" })).toBeInTheDocument();
    expect(screen.getByText(/決定事項を抽出する/)).toBeInTheDocument();
  });

  it("コピーボタンには元のMarkdown記法を残したテキストを渡す", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    renderDetailModal({
      ...basePrompt,
      content: "# 出力形式\n\n**箇条書き**でまとめてください。"
    });

    screen.getByRole("button", { name: "コピー" }).click();
    await Promise.resolve();

    expect(writeText).toHaveBeenCalledWith("# 出力形式\n\n**箇条書き**でまとめてください。");
  });
});

describe("プロンプト詳細モーダルの作例画像", () => {
  const imageUrl = "https://example.com/sample.png";
  const expandedViewerName = `${basePrompt.title} の作例画像`;

  function renderWithImage() {
    return renderDetailModal({ ...basePrompt, reference_image_url: imageUrl });
  }

  it("作例画像はそのまま拡大表示を開くボタンになる", () => {
    renderWithImage();

    const trigger = screen.getByRole("button", { name: "作例画像を拡大表示する" });
    expect(trigger.querySelector("img")?.getAttribute("src")).toBe(imageUrl);
    // 拡大表示は開くまでDOMに出さない / the viewer is absent until it is opened
    expect(screen.queryByRole("dialog", { name: expandedViewerName })).not.toBeInTheDocument();
  });

  it("クリックで拡大表示を開き、閉じるボタンで元に戻る", () => {
    renderWithImage();

    fireEvent.click(screen.getByRole("button", { name: "作例画像を拡大表示する" }));
    const viewer = screen.getByRole("dialog", { name: expandedViewerName });
    expect(viewer.querySelector("img")?.getAttribute("src")).toBe(imageUrl);

    fireEvent.click(screen.getByRole("button", { name: "拡大表示を閉じる" }));
    expect(screen.queryByRole("dialog", { name: expandedViewerName })).not.toBeInTheDocument();
  });

  it("拡大表示中のEscapeは拡大だけを閉じ、詳細モーダル側へは伝えない", () => {
    renderWithImage();

    fireEvent.click(screen.getByRole("button", { name: "作例画像を拡大表示する" }));
    const viewer = screen.getByRole("dialog", { name: expandedViewerName });

    // fireEventはpreventDefaultされるとfalseを返す。詳細モーダルのEscape処理は
    // defaultPreventedを見て中断するため、モーダルごと閉じてしまうことはない
    // fireEvent returns false when preventDefault ran; the modal's Escape handler bails on
    // defaultPrevented, so the whole modal does not close behind the viewer
    const notPrevented = fireEvent.keyDown(viewer, { key: "Escape" });
    expect(notPrevented).toBe(false);
    expect(screen.queryByRole("dialog", { name: expandedViewerName })).not.toBeInTheDocument();
  });
});

// カードと同じく、既定値のチップと作例画像の見出しは出さない方針を固定する
// Locks in the rule that default chips and the reference-image heading are not rendered, like on the card
describe("プロンプト詳細モーダルのメタ表示", () => {
  it("既定のプロンプト×テキストではフォーマット・メディアのチップを表示しない", () => {
    const { container } = renderDetailModal(basePrompt);

    expect(container.querySelector("#modalPromptFormat")).toBeNull();
    expect(container.querySelector("#modalPromptMediaType")).toBeNull();
    expect(container.querySelector("#modalPromptCategory")?.textContent).toContain("仕事・ビジネス");
  });

  it("SKILL形式・画像メディアのときだけチップを表示する", () => {
    const { container } = renderDetailModal({
      ...basePrompt,
      content_format: "skill",
      skill_markdown: "# SKILL",
      media_type: "image"
    });

    expect(container.querySelector("#modalPromptFormat")?.textContent).toContain("SKILL");
    expect(container.querySelector("#modalPromptMediaType")?.textContent).toContain("画像");
  });

  it("作例画像の見出しと補足文は表示しない", () => {
    renderDetailModal({ ...basePrompt, reference_image_url: "/static/uploads/example.png" });

    expect(screen.queryByText("作例メディア")).not.toBeInTheDocument();
    expect(screen.queryByText("生成結果の作例画像（任意・1点）")).not.toBeInTheDocument();
  });
});
