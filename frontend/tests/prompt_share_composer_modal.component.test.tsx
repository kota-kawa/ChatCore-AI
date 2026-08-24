import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef, useRef, useState, type FormEvent } from "react";
import { describe, expect, it, vi } from "vitest";

import { PromptShareComposerModal } from "../components/prompt_share/prompt_share_composer_modal";
import type { ContentFormat, MediaType, PromptResource } from "../scripts/prompt_share/types";

type ComposerType = "text" | "image" | "skill";

function ComposerHarness({
  initialType = "text",
  isGuest = false,
  isPostSubmitting = false,
  statusMessage = "",
  onClose = vi.fn()
}: {
  initialType?: ComposerType;
  isGuest?: boolean;
  isPostSubmitting?: boolean;
  statusMessage?: string;
  onClose?: () => void;
}) {
  const [contentFormat, setContentFormat] = useState<ContentFormat>(initialType === "skill" ? "skill" : "prompt");
  const [mediaType, setMediaType] = useState<MediaType>(initialType === "image" ? "image" : "text");
  const [postTitle, setPostTitle] = useState("");
  const [postCategory, setPostCategory] = useState("");
  const [postContent, setPostContent] = useState("");
  const [postAiModel, setPostAiModel] = useState("");
  const [guardrailEnabled, setGuardrailEnabled] = useState(false);
  const [postInputExample, setPostInputExample] = useState("");
  const [postOutputExample, setPostOutputExample] = useState("");
  const [postResources, setPostResources] = useState<PromptResource[]>([]);
  const [skillMarkdown, setSkillMarkdown] = useState("");
  const skillMarkdownRef = useRef<HTMLTextAreaElement | null>(null);

  return (
    <PromptShareComposerModal
      isOpen
      isGuest={isGuest}
      isPostSubmitting={isPostSubmitting}
      postModalRef={createRef<HTMLDivElement>()}
      onClose={onClose}
      onSubmit={(event: FormEvent<HTMLFormElement>) => event.preventDefault()}
      contentFormat={contentFormat}
      setContentFormat={setContentFormat}
      mediaType={mediaType}
      setMediaType={setMediaType}
      postTitle={postTitle}
      setPostTitle={setPostTitle}
      postCategory={postCategory}
      setPostCategory={setPostCategory}
      postContent={postContent}
      setPostContent={setPostContent}
      postAiModel={postAiModel}
      setPostAiModel={setPostAiModel}
      guardrailEnabled={guardrailEnabled}
      setGuardrailEnabled={setGuardrailEnabled}
      postInputExample={postInputExample}
      setPostInputExample={setPostInputExample}
      postOutputExample={postOutputExample}
      setPostOutputExample={setPostOutputExample}
      postResources={postResources}
      setPostResources={setPostResources}
      attributeBindings={{
        skill_markdown: {
          value: skillMarkdown,
          setValue: setSkillMarkdown,
          ref: skillMarkdownRef
        }
      }}
      updatePromptFeedbackErrorIfNeeded={vi.fn()}
      categoryOptions={[
        { value: "", label: "未選択" },
        { value: "business", label: "仕事・ビジネス" }
      ]}
      promptPostStatus={{
        message: statusMessage,
        variant: statusMessage ? "error" : "info"
      }}
      promptPostTitleInputRef={createRef<HTMLInputElement>()}
      promptPostCategorySelectRef={createRef<HTMLSelectElement>()}
      promptPostContentTextareaRef={createRef<HTMLTextAreaElement>()}
      promptPostAiModelSelectRef={createRef<HTMLInputElement>()}
      promptPostInputExamplesRef={createRef<HTMLTextAreaElement>()}
      promptPostOutputExamplesRef={createRef<HTMLTextAreaElement>()}
      promptImageInputRef={createRef<HTMLInputElement>()}
      promptAssistRootRef={createRef<HTMLDivElement>()}
      promptImagePreviewUrl=""
      promptImagePreviewName=""
      onReferenceImageChange={vi.fn()}
      onClearReferenceImage={vi.fn()}
    />
  );
}

function getExamplesSection() {
  const section = document.getElementById("composerExamplesTitle")?.closest("section");
  if (!section) {
    throw new Error("利用例セクションが見つかりません。");
  }
  return section;
}

describe("新しいプロンプトを投稿モーダル", () => {
  it("投稿タイプをテキスト・画像・SKILLの理解しやすい3択で表示する", () => {
    render(<ComposerHarness />);

    const typeSelector = screen.getByRole("radiogroup", { name: "投稿タイプを選択" });
    expect(within(typeSelector).getAllByRole("radio")).toHaveLength(3);
    expect(within(typeSelector).getByRole("radio", { name: /テキストプロンプト/ })).toBeChecked();
    expect(within(typeSelector).getByRole("radio", { name: /画像生成プロンプト/ })).not.toBeChecked();
    expect(within(typeSelector).getByRole("radio", { name: /SKILL/ })).not.toBeChecked();
  });

  it("テキストプロンプトでは本文と任意の入出力例を表示し、画像添付を表示しない", () => {
    render(<ComposerHarness initialType="text" />);

    expect(document.getElementById("prompt-content")).toBeVisible();
    expect(getExamplesSection()).not.toHaveAttribute("hidden");
    expect(document.getElementById("prompt-reference-image")).not.toBeVisible();
  });

  it("画像生成プロンプトでは作例画像を表示し、テキスト用の入出力例を非表示にする", async () => {
    const user = userEvent.setup();
    render(<ComposerHarness />);

    await user.click(screen.getByRole("radio", { name: /画像生成プロンプト/ }));

    expect(document.getElementById("prompt-content")).toBeVisible();
    expect(document.getElementById("prompt-reference-image")).toBeVisible();
    expect(getExamplesSection()).toHaveAttribute("hidden");
  });

  it("SKILLでは定義と追加リソースを表示し、本文・画像・入出力例を非表示にする", async () => {
    const user = userEvent.setup();
    render(<ComposerHarness initialType="image" />);

    await user.click(screen.getByRole("radio", { name: /SKILL/ }));

    expect(screen.getByLabelText("SKILL定義（Markdown）")).toBeVisible();
    expect(screen.getByText("追加リソース（任意）")).toBeVisible();
    expect(document.getElementById("prompt-content")).not.toBeVisible();
    expect(document.getElementById("prompt-reference-image")).not.toBeVisible();
    expect(getExamplesSection()).toHaveAttribute("hidden");
  });

  it("ゲスト投稿ではテキストだけを表示し、制限と引継ぎを案内する", () => {
    render(<ComposerHarness initialType="image" isGuest />);

    expect(screen.getByText("ゲストとして投稿")).toBeVisible();
    expect(screen.getByText("投稿はIPアドレスとCookieごとに24時間で1件までです。")).toBeVisible();
    expect(screen.getByText("登録後、このゲスト投稿はあなたのアカウントへ自動で引き継がれます。")).toBeVisible();
    expect(screen.getByText("テキストプロンプト")).toBeVisible();
    expect(screen.queryByRole("radiogroup", { name: "投稿タイプを選択" })).toBeNull();
    expect(document.getElementById("prompt-content")).toBeVisible();
    expect(document.getElementById("prompt-reference-image")).toBeNull();
    expect(screen.queryByLabelText("SKILL定義（Markdown）")).toBeNull();
    expect(screen.queryByText("AIで下書きを作る")).toBeNull();
    expect(document.getElementById("prompt-ai-model")).toBeNull();
  });

  it("カテゴリが必須ではないことをラベルとフォーム制約の両方で伝える", () => {
    render(<ComposerHarness />);

    expect(document.querySelector('label[for="prompt-category-trigger"]')).toHaveTextContent("カテゴリ 任意");
    expect(document.getElementById("prompt-category")).not.toBeRequired();
  });

  it("使用AIモデルは自由入力欄で、右端のアイコンから投稿タイプに合う候補を選べる", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<ComposerHarness />);
    const aiModelInput = document.getElementById("prompt-ai-model");
    expect(aiModelInput).toBeInstanceOf(HTMLInputElement);
    expect(aiModelInput).not.toHaveAttribute("list");

    const modelMenuTrigger = screen.getByRole("button", { name: "候補のAIモデルを選択" });
    expect(modelMenuTrigger).toHaveAttribute("aria-expanded", "false");
    await user.click(modelMenuTrigger);
    expect(modelMenuTrigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitemradio", { name: "ChatGPT (GPT-5.6 Sol)" })).toBeVisible();
    expect(screen.queryByRole("menuitemradio", { name: "Midjourney" })).toBeNull();

    await user.click(screen.getByRole("menuitemradio", { name: "ChatGPT (GPT-5.6 Sol)" }));
    expect(aiModelInput).toHaveValue("ChatGPT (GPT-5.6 Sol)");
    expect(modelMenuTrigger).toHaveAttribute("aria-expanded", "false");

    unmount();
    render(<ComposerHarness initialType="image" />);
    await user.click(screen.getByRole("button", { name: "候補のAIモデルを選択" }));
    expect(screen.getByRole("menuitemradio", { name: "Midjourney V8.2" })).toBeVisible();
    expect(screen.queryByRole("menuitemradio", { name: "ChatGPT (GPT-5.6 Sol)" })).toBeNull();
  });

  it("リストにないモデル名も自由入力できる", async () => {
    const user = userEvent.setup();
    render(<ComposerHarness />);

    const aiModelInput = document.getElementById("prompt-ai-model") as HTMLInputElement;
    await user.type(aiModelInput, "自作のローカルLLM");

    expect(aiModelInput).toHaveValue("自作のローカルLLM");
  });

  it("送信中は閉じる操作とフォーム内の編集を無効にする", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<ComposerHarness isPostSubmitting onClose={onClose} />);

    const closeButton = screen.getByRole("button", { name: "投稿モーダルを閉じる" });
    expect(closeButton).toBeDisabled();
    await user.click(closeButton);
    expect(onClose).not.toHaveBeenCalled();

    const form = document.getElementById("postForm");
    const fieldset = form?.querySelector("fieldset");
    expect(fieldset).not.toBeNull();
    expect(fieldset).toBeDisabled();
    expect(screen.getByRole("button", { name: "投稿を準備中…" })).toBeDisabled();
  });

  it("投稿結果のステータスを支援技術へ通知する", () => {
    render(<ComposerHarness statusMessage="タイトルを入力してください。" />);

    const status = screen.getByText("タイトルを入力してください。");
    expect(status).toHaveAttribute("role", "alert");
    expect(status).toHaveAttribute("aria-live", "assertive");
    expect(status).toHaveAttribute("aria-atomic", "true");
  });

  it("下部固定のバーを持たず、投稿ボタンを入力欄の一番下に置く", () => {
    render(<ComposerHarness />);

    const form = document.getElementById("postForm");
    expect(form).not.toBeNull();
    expect(form?.querySelector(".composer-footer")).toBeNull();
    expect(screen.queryByRole("button", { name: "閉じる" })).toBeNull();

    const actions = form?.lastElementChild;
    expect(actions).toHaveClass("composer-actions");
    expect(actions?.querySelector("button[type='submit']")).toBe(
      screen.getByRole("button", { name: "投稿する" })
    );
  });

  it("画像アップロードをキーボードから到達できるファイル入力として提供する", async () => {
    const user = userEvent.setup();
    render(<ComposerHarness initialType="image" />);

    const fileInput = document.getElementById("prompt-reference-image");
    expect(fileInput).toBeInstanceOf(HTMLInputElement);
    expect(fileInput).toHaveAttribute("type", "file");
    expect(fileInput).not.toHaveAttribute("hidden");
    expect(fileInput).not.toHaveAttribute("tabindex", "-1");

    (fileInput as HTMLInputElement).focus();
    expect(fileInput).toHaveFocus();
    await user.upload(fileInput as HTMLInputElement, new File(["image"], "example.png", { type: "image/png" }));
  });
});
