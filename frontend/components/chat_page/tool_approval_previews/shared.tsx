// ツール承認カードのプレビュー（memo / prompts / profile_settings）が共有する、本文・項目の表示部品。
// Shared display parts for the tool approval card previews (memo / prompts / profile_settings): bodies and labelled fields.
import { type ReactNode } from "react";

import { useTranslation } from "../../../contexts/locale_context";

// これより長い本文は抜粋だけを見せ、全文は折り畳みに入れる。カードが画面を占有しないため。
// Text longer than this shows an excerpt and keeps the full text in a disclosure, so a card never
// takes over the screen.
const LONG_TEXT_CHARS = 280;
const LONG_TEXT_LINES = 6;

// 本文が長文として抜粋表示にすべきか判定する（文字数または行数が上限超過）。
// Decides whether a body should be shown as an excerpt (over the character or line limit).
function isLongText(text: string) {
  return text.length > LONG_TEXT_CHARS || text.split("\n").length > LONG_TEXT_LINES;
}

// 長文の先頭から行数・文字数の上限までを切り出し、省略記号を付けた抜粋を作る。
// Builds an excerpt from the start of a long text, capped by lines and characters, with an ellipsis.
function excerptOf(text: string) {
  const lines = text.split("\n").slice(0, LONG_TEXT_LINES).join("\n");
  const clipped = lines.length > LONG_TEXT_CHARS ? lines.slice(0, LONG_TEXT_CHARS) : lines;
  return `${clipped.trimEnd()}…`;
}

// 本文は Markdown として描かず、提案されたとおりの文字で見せる（差分の確認が目的のため）。
// Bodies are shown as the exact proposed characters, not rendered Markdown, because the point is to
// check what will be written.
export function PreviewText({ text, excerpt = false }: { text: string; excerpt?: boolean }) {
  return (
    <div className={excerpt ? "tool-approval-preview__text tool-approval-preview__text--excerpt" : "tool-approval-preview__text"}>
      {text}
    </div>
  );
}

// 全文の折り畳み。開くと抜粋は CSS で隠れ、全文だけが残る。
// Full-text disclosure; once opened, CSS hides the excerpt so only the full text remains.
export function FullTextDisclosure({ text }: { text: string }) {
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
export function ExpandableText({ text }: { text: string }) {
  if (!isLongText(text)) return <PreviewText text={text} />;
  return (
    <>
      <PreviewText text={excerptOf(text)} excerpt />
      <FullTextDisclosure text={text} />
    </>
  );
}

// ラベルと値を dt/dd の組で表示する、プレビュー内の1項目。
// One labelled field in a preview, rendered as a dt/dd pair.
export function PreviewField({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={className ? `tool-approval-preview__field ${className}` : "tool-approval-preview__field"}>
      <dt className="tool-approval-preview__label">{label}</dt>
      <dd className="tool-approval-preview__value">{children}</dd>
    </div>
  );
}
