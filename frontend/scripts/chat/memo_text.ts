// memo_text.ts – チャットの回答をメモ用テキストへ整える
// --------------------------------------------------
// Web 検索の参照表示は、チャット画面専用のマークアップとして回答本文へ差し込まれる。
//   - <details class="web-search-sources …">…</details> : 「回答までのステップ」と参照Webサイト一覧
//   - <a class="web-search-citation" …>…</a>            : 本文中に添える出典チップ
// これらのスタイルは `.chat-page .bot-message` 配下にしか無いため、メモ側では
// 素のリンクや favicon 画像がそのまま並び、表示が崩れる。メモにはタイトルと
// 本文だけを残したいので、保存前と表示前にここで取り除く。
//
// Web search references are chat-only markup injected into the answer body.
// Their styles are scoped to `.chat-page .bot-message`, so a memo renders them
// as bare links and favicons and the layout breaks. Memos keep only the title
// and the answer body, so these blocks are stripped before saving and before
// rendering.

// ネストした details を含まない最も内側のブロックにマッチする。
// Matches the innermost block, i.e. one that contains no nested details.
const WEB_SEARCH_SOURCES_BLOCK_PATTERN =
  /<details\b[^>]*class\s*=\s*(["'])[^"']*web-search-sources[^"']*\1[^>]*>(?:(?!<\/?details\b)[\s\S])*?<\/details>/gi;

// 出典チップは <a> の中に span/img しか持たないため、最短一致で </a> まで取れる。
// 直前の水平方向の空白も一緒に消して「本文です。 」のような余白を残さない。
// A citation chip only wraps spans and images, so a lazy match up to </a> is
// safe. Leading spaces/tabs are consumed as well so no dangling gap is left.
const WEB_SEARCH_CITATION_PATTERN =
  /[ \t]*<a\b[^>]*class\s*=\s*(["'])[^"']*web-search-citation[^"']*\1[^>]*>[\s\S]*?<\/a>/gi;
const SELECTED_REFERENCE_MARKER_PATTERN =
  /[ \t]*【(?:personal_knowledge_result|shared_prompt_result)】/g;

function tidyBlankLines(text: string): string {
  return text
    .replace(/[ \t]+$/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * 「回答までのステップ」「参照したWebサイト」の details ブロックを取り除く。
 * Remove the trace / referenced-website details blocks.
 */
function stripWebSearchSourcesHtml(text: string): string {
  if (!text.includes("web-search-sources")) return text;
  // 最も内側のブロックから順に除去し、変化がなくなるまで繰り返すことで
  // 外側のブロックも安全に取り除く。
  // Remove innermost blocks repeatedly until nothing changes, so the outer
  // block is removed safely as well.
  let current = text;
  let previous: string;
  do {
    previous = current;
    current = current.replace(WEB_SEARCH_SOURCES_BLOCK_PATTERN, "");
  } while (current !== previous);
  return tidyBlankLines(current);
}

/**
 * 本文中に埋め込まれた出典チップ（参照Webサイトへのリンク）を取り除く。
 * Remove the inline citation chips that link to referenced websites.
 */
function stripWebSearchCitationsHtml(text: string): string {
  if (!text.includes("web-search-citation")) return text;
  return tidyBlankLines(text.replace(WEB_SEARCH_CITATION_PATTERN, ""));
}

function stripSelectedReferenceMarkers(text: string): string {
  if (!text.includes("personal_knowledge_result") && !text.includes("shared_prompt_result")) {
    return text;
  }
  return tidyBlankLines(text.replace(SELECTED_REFERENCE_MARKER_PATTERN, ""));
}

/**
 * メモへ持ち込む前に、Web 検索の参照表示をすべて取り除く。
 * Strip every web search reference before the text reaches a memo.
 */
function stripWebSearchArtifacts(text: string): string {
  return stripSelectedReferenceMarkers(
    stripWebSearchCitationsHtml(stripWebSearchSourcesHtml(text)),
  );
}

export { stripWebSearchArtifacts, stripWebSearchCitationsHtml, stripWebSearchSourcesHtml };
