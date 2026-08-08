// ```chatcore-copy フェンスを「右上にコピーアイコンが付いた枠」へ変換する。
// メールや返信文のように、そのままコピーして外部へ送る完成文のためのブロックで、
// コードブロックとは別物として扱う（等幅・シンタックスハイライトは付けない）。
// 枠の中は素のテキストのまま出すため、画面に見える文字列とコピーされる文字列が一致する。
// Converts a ```chatcore-copy fence into a card with a copy icon at its top right.
// The fence carries finished text the reader pastes verbatim — an email, a message
// reply — so it is deliberately not a code block: no monospace, no highlighting.
// The body stays plain text, which keeps what is shown identical to what is copied.

import { escapeHtml } from "../core/html";

// フェンス名。表記ゆれ（chatcore copy / chatcore_copy）もモデル出力ではよく起きるため、
// 判定側だけ緩めに受ける。生成する HTML は常に同じ。
// The fence name. Models drift into "chatcore copy" or "chatcore_copy", so detection
// accepts those spellings while the produced HTML stays identical.
const COPY_BLOCK_FENCE_RE = /^chatcore[\s_-]*copy$/i;

export type CopyBlockInfo = {
  isCopyBlock: boolean;
  // フェンス名の後ろに書かれた短い見出し（例: ```chatcore-copy メール本文）
  // The short caption written after the fence name (e.g. ```chatcore-copy Email body)
  label: string;
};

// marked が渡すコードトークンの info 文字列を、フェンス種別とラベルに分解する。
// Split the info string marked hands to the code renderer into fence kind and label.
export function parseCopyBlockInfo(lang: string): CopyBlockInfo {
  const info = (lang || "").trim();
  if (!info) return { isCopyBlock: false, label: "" };

  const separatorIndex = info.search(/\s/);
  const name = separatorIndex === -1 ? info : info.slice(0, separatorIndex);
  if (!COPY_BLOCK_FENCE_RE.test(name)) return { isCopyBlock: false, label: "" };

  const label = separatorIndex === -1 ? "" : info.slice(separatorIndex).trim();
  return { isCopyBlock: true, label };
}

const COPY_BLOCK_OPEN_LINE_RE = /^[ \t]*```[ \t]*chatcore[\s_-]*copy\b[^\n]*$/i;
const FENCE_CLOSE_LINE_RE = /^[ \t]*```[ \t]*$/;

// メッセージ全体のコピーやメモ保存に、内部マーカーである ```chatcore-copy の
// 行がそのまま混ざらないようにする。中身の文面は1文字も変えずに残す。
// Keep the internal ```chatcore-copy delimiters out of a whole-message copy or a
// memo save. The wording inside the fence is passed through untouched.
export function stripCopyBlockFences(text: string): string {
  if (!text || !/chatcore[\s_-]*copy/i.test(text)) return text;

  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const kept: string[] = [];
  let insideCopyBlock = false;

  lines.forEach((line) => {
    if (!insideCopyBlock) {
      if (COPY_BLOCK_OPEN_LINE_RE.test(line)) {
        insideCopyBlock = true;
        return;
      }
      kept.push(line);
      return;
    }
    // 閉じフェンスだけを終端として扱うので、他の言語のフェンスは影響を受けない。
    // Only the closing fence ends the block, so fences of other languages are untouched.
    if (FENCE_CLOSE_LINE_RE.test(line)) {
      insideCopyBlock = false;
      return;
    }
    kept.push(line);
  });

  return kept.join("\n");
}

type RenderCopyBlockOptions = {
  // コピーボタンは document 委譲（message_copy_buttons）が動く画面でのみ出す。
  // メモやプレビューではボタンが反応しないので、枠だけを描く。
  // The button is only rendered where the delegated handler runs. Memo previews
  // have no handler, so they get the frame without a dead button.
  withCopyButton: boolean;
};

// ヘッダー（ラベル + コピーボタン）を組み立てる。どちらも無い場合はヘッダーごと省く。
// Build the header holding the label and the copy button, omitted when it would be empty.
function renderHeader(label: string, withCopyButton: boolean): string {
  if (!label && !withCopyButton) return "";

  const labelHtml = `<span class="copy-block-label">${escapeHtml(label)}</span>`;
  const buttonHtml = withCopyButton
    ? '<button class="copy-block-copy-btn" type="button" title="Copy"><i class="bi bi-clipboard"></i></button>'
    : "";

  return `<div class="copy-block-header">${labelHtml}${buttonHtml}</div>`;
}

// コピー枠の HTML を返す。呼び出し側でサニタイズされる前提で、本文はここでエスケープする。
// Return the copy card HTML. The caller sanitizes the result; the body is escaped here.
export function renderCopyBlockHtml(text: string, label: string, options: RenderCopyBlockOptions): string {
  // 末尾の改行はフェンスの閉じ側に由来するもので、コピー結果に余分な空行を作る。
  // The trailing newline comes from the closing fence and would add a blank line on paste.
  const body = escapeHtml((text || "").replace(/\n+$/, ""));
  return [
    '<div class="copy-block-container">',
    renderHeader(label, options.withCopyButton),
    `<pre class="copy-block-text">${body}</pre>`,
    "</div>",
  ].join("");
}
