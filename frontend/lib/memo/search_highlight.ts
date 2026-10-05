// ---------------------------------------------------------------------------
// 検索語の強調表示。バックエンドのキーワード検索（services/search_terms.py）と同じ規則で
// 語を分け、大文字小文字とひらがな／カタカナの違いを無視して当てる。規則が食い違うと、
// 検索には出たのに強調が無い、強調があるのに検索結果に出ない、という差が見えてしまう。
// Search-term highlighting. Terms are split by the same rules as the backend keyword search
// (services/search_terms.py), ignoring case and the hiragana/katakana difference. If the rules
// drifted apart, a memo could be found without anything highlighted, or highlighted without
// having been found.
// ---------------------------------------------------------------------------

// 空白（全角含む）と一般的な句読点で区切る。助詞では切らず、`/` と `\` は語の中に残す
// Split on whitespace (full-width included) and common punctuation; particles are not split on
// and `/` and `\` stay inside a term
const TERM_SEPARATOR = /[\s、。，．,.;:!?！？「」『』（）()[\]【】〈〉<>"'|]+/;

// バックエンドと同じ語数の上限
// The same cap on the number of terms as the backend
const MAX_SEARCH_TERMS = 8;

// ひらがな U+3041-3096 とカタカナ U+30A1-30F6 は 0x60 ずれで 1 対 1 に対応する（ゝゞ・ヽヾ も同様）。
// ヷヸヹヺ（U+30F7-30FA）と長音 ー には対応するひらがながないので変換しない
// Hiragana U+3041-3096 and katakana U+30A1-30F6 pair up at a 0x60 offset (as do the iteration
// marks); ヷヸヹヺ and the prolonged-sound mark ー have no hiragana form and are left alone
const KANA_OFFSET = 0x60;

function convertKana(term: string, toKatakana: boolean): string {
  return Array.from(term, (char) => {
    const code = char.codePointAt(0) ?? 0;
    const isHiragana = (code >= 0x3041 && code <= 0x3096) || code === 0x309d || code === 0x309e;
    const isKatakana = (code >= 0x30a1 && code <= 0x30f6) || code === 0x30fd || code === 0x30fe;
    if (toKatakana && isHiragana) return String.fromCodePoint(code + KANA_OFFSET);
    if (!toKatakana && isKatakana) return String.fromCodePoint(code - KANA_OFFSET);
    return char;
  }).join("");
}

// 検索語を重複なく、渡された順に分ける
// Split a query into distinct terms in the order given
export function splitSearchTerms(query: string): string[] {
  const terms: string[] = [];
  for (const raw of query.split(TERM_SEPARATOR)) {
    const term = raw.trim();
    if (!term || terms.includes(term)) continue;
    terms.push(term);
    if (terms.length >= MAX_SEARCH_TERMS) break;
  }
  return terms;
}

// 語そのものと、全部ひらがな・全部カタカナにした綴り（重複なし）
// The term plus its all-hiragana and all-katakana spellings, without duplicates
export function kanaVariants(term: string): string[] {
  const variants = [term];
  for (const converted of [convertKana(term, false), convertKana(term, true)]) {
    if (!variants.includes(converted)) variants.push(converted);
  }
  return variants;
}

// 検索語から、一致箇所を拾う正規表現を作る。当てる語が無ければ null。
// 長い綴りを先に並べ、「パスポート」と「パス」が両方あるとき長いほうが取られるようにする。
// 文字列の長さが変わる小文字化は使わず、i フラグで大文字小文字を無視する（位置がずれない）
// Builds the regex that finds matches, or null when there is nothing to match. Longer spellings come
// first so "パスポート" wins over "パス" when both are terms. Case is ignored with the i flag rather
// than by lowercasing, which can change the string length and shift positions
export function buildHighlightPattern(query: string): RegExp | null {
  const spellings = splitSearchTerms(query).flatMap(kanaVariants);
  if (spellings.length === 0) return null;
  const sorted = Array.from(new Set(spellings)).sort((a, b) => b.length - a.length);
  const source = sorted.map((spelling) => spelling.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  return new RegExp(source, "giu");
}

export type HighlightPart = { text: string; match: boolean };

// 文字列を、一致した部分としない部分に分ける
// Splits a string into matching and non-matching parts
export function splitByPattern(text: string, pattern: RegExp | null): HighlightPart[] {
  if (!pattern || !text) return [{ text, match: false }];
  const parts: HighlightPart[] = [];
  let cursor = 0;
  for (const found of text.matchAll(pattern)) {
    const start = found.index ?? 0;
    if (start > cursor) parts.push({ text: text.slice(cursor, start), match: false });
    parts.push({ text: found[0], match: true });
    cursor = start + found[0].length;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), match: false });
  return parts;
}

// 一致を包む要素のクラス。見た目は CSS が決める
// Class of the element wrapping a match; the look is up to CSS
export const HIGHLIGHT_CLASS = "memo-search-hit";

// 描画済みの DOM のうち、テキストノードの一致だけを <mark> で包む。要素の構造や属性
// （リンクの href、チェック欄など）には触れないので、本文のまま操作できる状態が保たれる。
// 要素をまたぐ一致（強調の途中にリンクの境目がある語など）は拾わない
// Wraps matches in <mark>, touching text nodes only. Elements and their attributes (link hrefs,
// checkboxes) are left as they are, so the body stays operable. A match that straddles an element
// boundary is not picked up
export function highlightTextNodes(root: HTMLElement, pattern: RegExp | null): void {
  if (!pattern) return;
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const targets: Text[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if ((node as Text).data.trim()) targets.push(node as Text);
  }
  for (const node of targets) {
    const parts = splitByPattern(node.data, pattern);
    if (!parts.some((part) => part.match)) continue;
    const fragment = root.ownerDocument.createDocumentFragment();
    for (const part of parts) {
      if (!part.match) {
        fragment.append(part.text);
        continue;
      }
      const mark = root.ownerDocument.createElement("mark");
      mark.className = HIGHLIGHT_CLASS;
      mark.textContent = part.text;
      fragment.append(mark);
    }
    node.replaceWith(fragment);
  }
}
