import { Fragment, memo, type ReactNode } from "react";

import { useTranslation } from "../../../contexts/locale_context";
import type { ToolApprovalApi } from "../../../types/generated/api_schemas";

type MemoPreview = NonNullable<ToolApprovalApi["preview"]>;

// これより長い本文は抜粋だけを見せ、全文は折り畳みに入れる。カードが画面を占有しないため。
// Text longer than this shows an excerpt and keeps the full text in a disclosure, so a card never
// takes over the screen.
const LONG_TEXT_CHARS = 280;
const LONG_TEXT_LINES = 6;

function isLongText(text: string) {
  return text.length > LONG_TEXT_CHARS || text.split("\n").length > LONG_TEXT_LINES;
}

function excerptOf(text: string) {
  const lines = text.split("\n").slice(0, LONG_TEXT_LINES).join("\n");
  const clipped = lines.length > LONG_TEXT_CHARS ? lines.slice(0, LONG_TEXT_CHARS) : lines;
  return `${clipped.trimEnd()}…`;
}

// 本文は Markdown として描かず、提案されたとおりの文字で見せる（差分の確認が目的のため）。
// Bodies are shown as the exact proposed characters, not rendered Markdown, because the point is to
// check what will be written.
function PreviewText({ text, excerpt = false }: { text: string; excerpt?: boolean }) {
  return (
    <div className={excerpt ? "tool-approval-preview__text tool-approval-preview__text--excerpt" : "tool-approval-preview__text"}>
      {text}
    </div>
  );
}

// 全文の折り畳み。開くと抜粋は CSS で隠れ、全文だけが残る。
// Full-text disclosure; once opened, CSS hides the excerpt so only the full text remains.
function FullTextDisclosure({ text }: { text: string }) {
  const { t } = useTranslation();
  return (
    <details className="tool-approval-preview__details">
      <summary className="tool-approval-preview__summary">
        <i className="bi bi-chevron-right tool-approval-preview__chevron" aria-hidden="true"></i>
        <span>{t("chat.toolApproval.preview.showFull")}</span>
      </summary>
      <PreviewText text={text} />
    </details>
  );
}

// 長文は抜粋と「全文を表示」の折り畳みに分ける。短文はそのまま見せる。
// Long text splits into an excerpt and a "show the full text" disclosure; short text is shown as is.
function ExpandableText({ text }: { text: string }) {
  if (!isLongText(text)) return <PreviewText text={text} />;
  return (
    <>
      <PreviewText text={excerptOf(text)} excerpt />
      <FullTextDisclosure text={text} />
    </>
  );
}

function PreviewField({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={className ? `tool-approval-preview__field ${className}` : "tool-approval-preview__field"}>
      <dt className="tool-approval-preview__label">{label}</dt>
      <dd className="tool-approval-preview__value">{children}</dd>
    </div>
  );
}

// メモの作成・追記・書き換えの提案を、実行前に確かめられる形で見せる。部分置換は編集ごとに
// 変更前／変更後を並べ、複数あるときだけ番号を付ける（メモエージェントの実行確認と同じ規則）。
// Shows a memo create, append or edit proposal so it can be checked before it runs. Partial edits list
// each passage before and after, numbered only when there is more than one (the same rule as the memo
// agent's action review).
function MemoApprovalPreviewComponent({ preview }: { preview: MemoPreview }) {
  const { t } = useTranslation();
  const untitled = t("chat.toolApproval.preview.untitled");

  if (preview.kind === "memo_create") {
    return (
      <dl className="tool-approval-preview">
        <PreviewField label={t("chat.toolApproval.preview.title")}>{preview.title.trim() || untitled}</PreviewField>
        <PreviewField label={t("chat.toolApproval.preview.content")}>
          <ExpandableText text={preview.content} />
        </PreviewField>
      </dl>
    );
  }

  if (preview.kind === "memo_append") {
    return (
      <dl className="tool-approval-preview">
        <PreviewField label={t("chat.toolApproval.preview.targetMemo")}>{preview.memo_title.trim() || untitled}</PreviewField>
        <PreviewField label={t("chat.toolApproval.preview.appendText")}>
          <ExpandableText text={preview.text} />
        </PreviewField>
      </dl>
    );
  }

  const edits = preview.mode === "edits" ? (preview.edits ?? []) : [];
  const numbered = edits.length > 1;
  return (
    <dl className="tool-approval-preview">
      <PreviewField label={t("chat.toolApproval.preview.targetMemo")}>{preview.memo_title.trim() || untitled}</PreviewField>
      {preview.new_title !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.newTitle")}>{preview.new_title.trim() || untitled}</PreviewField>
      ) : null}
      {edits.map((edit, index) => {
        const suffix = numbered ? ` ${index + 1}` : "";
        return (
          <Fragment key={index}>
            <PreviewField
              label={`${t("chat.toolApproval.preview.before")}${suffix}`}
              className="tool-approval-preview__field--before"
            >
              <ExpandableText text={edit.before} />
            </PreviewField>
            <PreviewField label={`${t("chat.toolApproval.preview.after")}${suffix}`}>
              <ExpandableText text={edit.after || t("chat.toolApproval.preview.removed")} />
            </PreviewField>
          </Fragment>
        );
      })}
      {preview.mode === "content" && preview.content !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.editedContent")}>
          <FullTextDisclosure text={preview.content} />
        </PreviewField>
      ) : null}
    </dl>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const MemoApprovalPreview = memo(MemoApprovalPreviewComponent);
MemoApprovalPreview.displayName = "MemoApprovalPreview";
