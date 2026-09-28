import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BotMessageParts } from "../components/chat_page/bot_message_parts";
import { ToolApprovalCard } from "../components/chat_page/tool_approval_card";
import { SharedChatMessageParts } from "../components/shared_chat/shared_chat_message_parts";
import { LocaleProvider } from "../contexts/locale_context";
import { normalizeToolApproval } from "../lib/chat_page/api_contract";
import type { ToolApprovalApi } from "../types/generated/api_schemas";

const FAR_FUTURE = "2999-01-01T00:00:00Z";

function approval(overrides: Record<string, unknown> = {}): ToolApprovalApi {
  const normalized = normalizeToolApproval({
    id: "a1",
    tool: "memo_create",
    family: "memo",
    status: "pending",
    always_allowed: true,
    preview: { kind: "memo_create", title: "買い物リスト", content: "牛乳\n卵" },
    expires_at: FAR_FUTURE,
    ...overrides,
  });
  if (!normalized) throw new Error("fixture must be a valid approval");
  return normalized;
}

function memoEdit(preview: Record<string, unknown>, overrides: Record<string, unknown> = {}) {
  return approval({
    tool: "memo_edit",
    preview: { kind: "memo_edit", memo_id: 7, memo_title: "議事録", base_revision: 3, ...preview },
    ...overrides,
  });
}

function promptApproval(preview: Record<string, unknown>, overrides: Record<string, unknown> = {}): ToolApprovalApi {
  return approval({
    tool: "publish_prompt",
    family: "prompts",
    preview: { kind: "publish_prompt", title: "会議の要約", content: "要点を箇条書きする", ...preview },
    ...overrides,
  });
}

type ProfileSettingsPreview = Extract<NonNullable<ToolApprovalApi["preview"]>, { kind: "profile_settings_update" }>;

function profilePreview(overrides: Partial<ProfileSettingsPreview> = {}): ProfileSettingsPreview {
  return {
    kind: "profile_settings_update" as const,
    display_name: null,
    bio: null,
    llm_profile_context: null,
    preferred_locale: null,
    theme: null,
    ...overrides,
  };
}

function profileApproval(overrides: Partial<ToolApprovalApi> = {}): ToolApprovalApi {
  return {
    id: "profile-a1",
    tool: "profile_settings_update",
    family: "profile",
    status: "pending",
    decision: null,
    always_allowed: false,
    preview: profilePreview(),
    warnings: [],
    expires_at: FAR_FUTURE,
    result: null,
    readonly: false,
    ...overrides,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("ToolApprovalCard", () => {
  it("offers approve once / always approve / deny and sends one decision only", async () => {
    let resolveDecision: () => void = () => {};
    const onDecide = vi.fn(() => new Promise<void>((resolve) => { resolveDecision = resolve; }));
    render(<ToolApprovalCard approval={approval()} onDecide={onDecide} />);

    expect(screen.getByRole("group", { name: "メモを作成します" })).toBeInTheDocument();
    const once = screen.getByRole("button", { name: "1度だけ承認" });
    const always = screen.getByRole("button", { name: "常に承認" });
    const deny = screen.getByRole("button", { name: "拒否" });

    fireEvent.click(always);
    fireEvent.click(once);
    fireEvent.click(deny);

    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith("a1", "approve_always");
    expect(once).toBeDisabled();
    expect(always).toBeDisabled();
    expect(deny).toBeDisabled();
    expect(screen.getByText("処理しています…")).toBeInTheDocument();

    await act(async () => resolveDecision());
    expect(once).toBeEnabled();
  });

  it("shows only approve and deny for a tool that cannot be always approved", () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ToolApprovalCard approval={approval({ always_allowed: false })} onDecide={onDecide} />);

    expect(screen.queryByRole("button", { name: "常に承認" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "1度だけ承認" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "承認" }));
    expect(onDecide).toHaveBeenCalledWith("a1", "approve_once");
    expect(screen.queryByText(/設定の「チャットの権限」/)).not.toBeInTheDocument();
  });

  it("keeps the buttons disabled while generating or once the user wrote after the reply", () => {
    const onDecide = vi.fn();
    render(<ToolApprovalCard approval={approval()} onDecide={onDecide} disabled />);

    const deny = screen.getByRole("button", { name: "拒否" });
    expect(deny).toBeDisabled();
    fireEvent.click(deny);
    expect(onDecide).not.toHaveBeenCalled();
  });

  it("treats a pending card past its deadline as expired without asking the server", () => {
    render(<ToolApprovalCard approval={approval({ expires_at: "2020-01-01T00:00:00Z" })} onDecide={vi.fn()} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("期限が切れたため実行していません");
  });

  it("locks the buttons when the deadline passes on an open screen", () => {
    vi.useFakeTimers({ now: Date.parse("2026-09-24T12:00:00Z") });
    render(<ToolApprovalCard approval={approval({ expires_at: "2026-09-24T12:00:10Z" })} onDecide={vi.fn()} />);
    expect(screen.getByRole("button", { name: "拒否" })).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(11_000);
    });

    expect(screen.queryByRole("button", { name: "拒否" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("期限が切れたため実行していません");
  });

  it("shows a succeeded card with the memo link instead of the buttons", () => {
    render(
      <ToolApprovalCard
        approval={approval({ status: "succeeded", decision: "once", result: { target_id: 12, target_title: "買い物リスト" } })}
        onDecide={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("実行しました");
    const link = screen.getByRole("link", { name: /メモを開く/ });
    expect(link).toHaveAttribute("href", "/memo");
    expect(link).toHaveTextContent("買い物リスト");
  });

  it("names an automatic run as coming from always approve", () => {
    render(<ToolApprovalCard approval={approval({ status: "succeeded", decision: "auto", result: { target_id: 1 } })} />);
    expect(screen.getByRole("status")).toHaveTextContent("「常に承認」の設定で実行しました");
  });

  it("explains a failure from its error code, with a generic sentence for unknown codes", () => {
    const { rerender } = render(
      <ToolApprovalCard
        approval={approval({ status: "failed", decision: "once", result: { error_code: "target_changed" } })}
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("実行できませんでした");
    expect(screen.getByRole("status")).toHaveTextContent("提案の後で対象が更新されたため、上書きしませんでした。");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();

    rerender(
      <ToolApprovalCard
        approval={approval({ status: "failed", decision: "once", result: { error_code: "constructor" } })}
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("時間をおいてもう一度お試しください。");
  });

  it.each([
    ["denied", "拒否しました。何も変更していません。"],
    ["expired", "期限が切れたため実行していません"],
    ["superseded", "新しい発言があったため無効になりました"],
    ["cancelled", "回答を止めたため取り消しました"],
  ])("shows the %s state without buttons", (status, text) => {
    render(<ToolApprovalCard approval={approval({ status })} onDecide={vi.fn()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(text);
  });

  it("lists warnings as notes rather than errors", () => {
    render(
      <ToolApprovalCard
        approval={memoEdit(
          { mode: "edits", edits: [{ before: "a", after: "b" }] },
          { warnings: ["shared_memo", "untrusted_input_in_turn"] },
        )}
        onDecide={vi.fn()}
      />,
    );

    const warnings = screen.getAllByRole("listitem");
    expect(warnings).toHaveLength(2);
    expect(warnings[0]).toHaveTextContent("このメモは共有中です。");
    expect(warnings[1]).toHaveTextContent("外部の内容");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("requires acknowledgment before approving a public prompt that overlaps private content", () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(
      <ToolApprovalCard
        approval={promptApproval(
          { private_overlap_excerpts: ["利用者の非公開メモから一致した文"] },
          { warnings: ["private_text_in_public_post"], always_allowed: true },
        )}
        onDecide={onDecide}
      />,
    );

    expect(screen.getByText("このターンで読んだ非公開の内容（メモ・自分用プロンプト・個人Skill・プロフィールなど）と一致する箇所があります。公開してよい内容か確かめてください。")).toBeInTheDocument();
    expect(screen.getByText("一致した箇所")).toBeInTheDocument();
    expect(screen.getByText("利用者の非公開メモから一致した文")).toBeInTheDocument();
    const approve = screen.getByRole("button", { name: "1度だけ承認" });
    expect(approve).toBeDisabled();
    expect(screen.getByRole("button", { name: "拒否" })).toBeEnabled();
    fireEvent.click(approve);
    expect(onDecide).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("checkbox", { name: "内容を確認しました。公開してよい情報です。" }));
    expect(approve).toBeEnabled();
    fireEvent.click(approve);
    expect(onDecide).toHaveBeenCalledWith("a1", "approve_once", true);
  });

  it.each([
    ["publish_prompt", "プロンプト共有を開く", "/prompt_share", { kind: "publish_prompt", title: "公開案", content: "本文" }, "本文"],
    ["my_prompt_save", "自分用プロンプトを開く", "/#task-selection", { kind: "my_prompt_save", task_id: 3, current_title: "検索", clear_fields: [], title: "検索", prompt_content: "検索する" }, "検索する"],
    ["my_skill_save", "個人Skillを開く", "/#skill-selection-title", { kind: "my_skill_save", skill_id: 4, name: "校正", instructions: "誤字を直す" }, "誤字を直す"],
  ])("shows the %s preview and result link", (tool, label, href, preview, previewText) => {
    const current = approval({
      tool,
      family: "prompts",
      preview,
      status: "succeeded",
      decision: "once",
      result: { target_id: 12, target_title: "保存済み" },
    });
    render(<ToolApprovalCard approval={current} />);

    expect(screen.getByRole("group")).toHaveTextContent(previewText);
    expect(screen.getByRole("link", { name: new RegExp(label) })).toHaveAttribute("href", href);
  });

  it("identifies the existing Skill when only its instructions are edited", () => {
    render(
      <ToolApprovalCard
        approval={approval({
          tool: "my_skill_save",
          family: "prompts",
          always_allowed: false,
          preview: {
            kind: "my_skill_save",
            skill_id: 9,
            current_name: "調査アシスタント",
            name: null,
            instructions: "出典を確認する",
          },
        })}
      />,
    );

    expect(screen.getByRole("group")).toHaveTextContent("調査アシスタント");
    expect(screen.getByRole("group")).toHaveTextContent("出典を確認する");
    expect(screen.getByRole("group")).not.toHaveTextContent("（題名なし）");
  });

  it("shows the existing Task name, id, and optional fields that will be cleared", () => {
    render(
      <ToolApprovalCard
        approval={approval({
          tool: "my_prompt_save",
          family: "prompts",
          always_allowed: false,
          preview: {
            kind: "my_prompt_save",
            task_id: 3,
            current_title: "既存Task",
            clear_fields: ["response_rules"],
            title: "新しいTask名",
            prompt_content: "新しい本文",
            response_rules: "",
            output_skeleton: "",
            input_examples: "",
            output_examples: "",
          },
        })}
      />,
    );

    const card = screen.getByRole("group", { name: "自分用プロンプトを保存します" });
    expect(card).toHaveTextContent("既存Task (#3)");
    expect(card).toHaveTextContent("新しいTask名");
    expect(card).toHaveTextContent("空にする項目");
    expect(card).toHaveTextContent("回答のルール");
  });

  it("renders a readonly card from another view without buttons, with a note while pending", () => {
    render(<ToolApprovalCard approval={approval({ readonly: true })} onDecide={vi.fn()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    const note = screen.getByText("このカードは共有された会話のもので、ここからは操作できません。");
    expect(note).toBeInTheDocument();
    expect(note).toHaveClass("interactive-buttons-readonly-note");
  });
});

describe("MemoApprovalPreview", () => {
  it("shows the new memo's title and body, folding a long body behind a disclosure", () => {
    const longBody = Array.from({ length: 12 }, (_, index) => `${index + 1}行目`).join("\n");
    render(<ToolApprovalCard approval={approval({ preview: { kind: "memo_create", title: "", content: longBody } })} />);

    expect(screen.getByText("（題名なし）")).toBeInTheDocument();
    expect(screen.getByText(/1行目[\s\S]*6行目…/)).toBeInTheDocument();
    const disclosure = screen.getByText("全文を表示").closest("details");
    expect(disclosure).not.toBeNull();
    expect(disclosure).toHaveTextContent("12行目");
  });

  it("shows the target memo and the text to append", () => {
    render(
      <ToolApprovalCard
        approval={approval({
          tool: "memo_append",
          preview: { kind: "memo_append", memo_id: 4, memo_title: "読書メモ", text: "第3章の要点", separator: "\n\n" },
        })}
      />,
    );

    expect(screen.getByRole("group", { name: "メモに追記します" })).toBeInTheDocument();
    expect(screen.getByText("読書メモ")).toBeInTheDocument();
    expect(screen.getByText("第3章の要点")).toBeInTheDocument();
  });

  it("lists partial edits as numbered before/after pairs and marks a removal", () => {
    render(
      <ToolApprovalCard
        approval={memoEdit({
          mode: "edits",
          new_title: "議事録（確定）",
          edits: [
            { before: "来週", after: "9月30日" },
            { before: "仮の案", after: "" },
          ],
        })}
      />,
    );

    const preview = screen.getByRole("group", { name: "メモを書き換えます" });
    expect(within(preview).getByText("議事録（確定）")).toBeInTheDocument();
    const labels = Array.from(preview.querySelectorAll("dt")).map((node) => node.textContent);
    expect(labels).toEqual(["対象のメモ", "新しい題名", "変更前 1", "変更後 1", "変更前 2", "変更後 2"]);
    expect(within(preview).getByText("（削除）")).toBeInTheDocument();
  });

  it("does not number a single edit", () => {
    render(<ToolApprovalCard approval={memoEdit({ mode: "edits", edits: [{ before: "誤字", after: "正字" }] })} />);
    const labels = Array.from(document.querySelectorAll("dt")).map((node) => node.textContent);
    expect(labels).toEqual(["対象のメモ", "変更前", "変更後"]);
  });

  it("keeps a whole-body rewrite behind a disclosure", () => {
    render(<ToolApprovalCard approval={memoEdit({ mode: "content", content: "全部書き直した本文" })} />);
    const disclosure = screen.getByText("全文を表示").closest("details");
    expect(disclosure).not.toBeNull();
    expect(disclosure).not.toHaveAttribute("open");
    expect(disclosure).toHaveTextContent("全部書き直した本文");
  });

  it("shows changed profile settings and makes empty text fields explicit", () => {
    render(
      <ToolApprovalCard
        approval={profileApproval({
          preview: {
            kind: "profile_settings_update",
            display_name: "Mika",
            bio: "",
            llm_profile_context: "",
            preferred_locale: "en",
            theme: "dark",
          },
        })}
        onDecide={vi.fn()}
      />,
    );

    const card = screen.getByRole("group", { name: "プロフィール設定を更新します" });
    expect(card.querySelector(".bi-person-gear")).toBeInTheDocument();
    expect(screen.getByText("表示名").parentElement).toHaveTextContent("Mika");
    expect(screen.getByText("自己紹介").parentElement).toHaveTextContent("空にします");
    expect(screen.getByText("AIに伝えるプロフィール").parentElement).toHaveTextContent("空にします");
    expect(screen.getByText("英語")).toBeInTheDocument();
    expect(screen.getByText("ダーク")).toBeInTheDocument();
    expect(screen.getByText("テーマ設定はこのブラウザーの localStorage に保存され、サーバーからは確認できません。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "常に承認" })).not.toBeInTheDocument();
  });

  it("links a succeeded profile update to the existing settings page", () => {
    render(
      <ToolApprovalCard
        approval={profileApproval({
          status: "succeeded",
          decision: "once",
          result: { target_id: null, target_title: null, error_code: null },
          preview: profilePreview({ preferred_locale: "ja" }),
        })}
      />,
    );

    const link = screen.getByRole("link", { name: "プロフィール設定を開く" });
    expect(link).toHaveAttribute("href", "/settings");
  });

  it("translates profile locale and theme values in the English catalogue", () => {
    render(
      <LocaleProvider initialLocale="en">
        <ToolApprovalCard
          approval={profileApproval({
            preview: profilePreview({ preferred_locale: "ja", theme: "auto" }),
          })}
        />
      </LocaleProvider>,
    );

    expect(screen.getByRole("group", { name: "Update your profile settings" })).toBeInTheDocument();
    expect(screen.getByText("Japanese")).toBeInTheDocument();
    expect(screen.getByText("Auto")).toBeInTheDocument();
    expect(screen.getByText("Theme preference is stored in this browser's localStorage and can't be read by the server.")).toBeInTheDocument();
  });
});

describe("approval cards inside messages", () => {
  it("passes decisions from a bot message and disables them on request", () => {
    const onToolApprovalDecide = vi.fn().mockResolvedValue(undefined);
    const parts = [
      { type: "text" as const, text: "メモを作る案です。" },
      { type: "tool_approval" as const, approval: approval() },
    ];
    const { rerender } = render(
      <BotMessageParts fallbackText="" parts={parts} onToolApprovalDecide={onToolApprovalDecide} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "拒否" }));
    expect(onToolApprovalDecide).toHaveBeenCalledWith("a1", "deny");

    rerender(
      <BotMessageParts fallbackText="" parts={parts} onToolApprovalDecide={onToolApprovalDecide} approvalsDisabled />,
    );
    expect(screen.getByRole("button", { name: "拒否" })).toBeDisabled();
  });

  it("shows only the status of a redacted card in the shared view", () => {
    const redacted = normalizeToolApproval({ id: "a1", tool: "memo_edit", family: "memo", status: "succeeded", decision: "once", readonly: true });
    if (!redacted) throw new Error("redacted card must be valid");
    render(<SharedChatMessageParts fallbackText="" parts={[{ type: "tool_approval", approval: redacted }]} />);

    expect(screen.getByRole("group", { name: "メモを書き換えます" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("実行しました");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  // 共有チャットを自分のルームへ取り込む（fork）と、redact 済みのカードは通常チャットの
  // BotMessageParts に載る。共有画面専用の CSS が当たらないため、ここでも読み取り専用の
  // 注記の文言とクラスが揃っていることを確かめる。
  // Forking a shared chat into the viewer's own room lands the redacted card on the normal
  // chat's BotMessageParts, which the shared view's own CSS never reaches. This confirms the
  // readonly note's wording and class hold there too.
  it("keeps the readonly note on a redacted, still-pending card forked into a normal chat", () => {
    const redacted = normalizeToolApproval({ id: "a1", tool: "memo_create", family: "memo", status: "pending", readonly: true });
    if (!redacted) throw new Error("redacted card must be valid");
    render(<BotMessageParts fallbackText="" parts={[{ type: "tool_approval", approval: redacted }]} onToolApprovalDecide={vi.fn()} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    const note = screen.getByText("このカードは共有された会話のもので、ここからは操作できません。");
    expect(note).toBeInTheDocument();
    expect(note).toHaveClass("interactive-buttons-readonly-note");
  });
});
