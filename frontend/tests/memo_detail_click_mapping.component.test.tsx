import { describe, expect, it } from "vitest";

import { estimateSourceOffsetByRatio, locateSourceOffset } from "../lib/memo/detail_click_to_edit";

// 描画済み Markdown のクリック位置を原文の位置へ写す処理を、jsdom の実 DOM で確認する
// Checks the rendered-Markdown → source mapping against a real jsdom DOM
function renderPreview(html: string) {
  const root = document.createElement("div");
  root.innerHTML = html;
  document.body.appendChild(root);
  return root;
}

function textNode(root: HTMLElement, index: number) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  for (let i = 0; i < index; i += 1) node = walker.nextNode();
  return node as Text;
}

describe("locateSourceOffset", () => {
  const source = "牛乳を買う **今日**\n\n牛乳を買う 明日\n\n- 図書館";
  const html = "<p>牛乳を買う <strong>今日</strong></p><p>牛乳を買う 明日</p><ul><li>図書館</li></ul>";

  it("maps a click inside a text run to the same character in the source", () => {
    const root = renderPreview(html);
    // 1つ目の段落の先頭テキスト "牛乳を買う " の 2 文字目
    // second character of the first paragraph's leading run
    expect(locateSourceOffset(root, source, { node: textNode(root, 0), offset: 2 })).toBe(2);
    // <strong> の中身は原文では ** の後ろにある
    // the <strong> text sits after ** in the source
    expect(locateSourceOffset(root, source, { node: textNode(root, 1), offset: 1 })).toBe(source.indexOf("今日") + 1);
  });

  it("picks the nth occurrence when the same text appears more than once", () => {
    const root = renderPreview(html);
    const second = textNode(root, 2); // "牛乳を買う 明日"
    expect(locateSourceOffset(root, source, { node: second, offset: 0 })).toBe(source.indexOf("牛乳を買う 明日"));
  });

  it("uses the child offset of an element hit instead of always its first text run", () => {
    const root = renderPreview(html);
    const firstParagraph = root.querySelector("p") as HTMLElement; // "牛乳を買う " + <strong>今日</strong>
    // 子 1 番目（<strong>）の手前をクリック → その最初のテキストの先頭
    // before child 1 (<strong>) → start of its first run
    expect(locateSourceOffset(root, source, { node: firstParagraph, offset: 1 })).toBe(source.indexOf("今日"));
    // 子の数を超える位置（段落の末尾の余白）→ 最後のテキストの終わり
    // past the last child (trailing gap of the paragraph) → end of the last run
    expect(locateSourceOffset(root, source, { node: firstParagraph, offset: 2 })).toBe(source.indexOf("今日") + 2);
    // ルート要素の末尾ヒット → 文書全体の最後のテキストの終わり
    // a hit past the root's last child → end of the document's last run
    expect(locateSourceOffset(root, source, { node: root, offset: root.childNodes.length })).toBe(source.length);
  });

  it("falls back to a short fragment around the click when display normalisation changed the run", () => {
    // 表示側で「見出しに昇格」された行: 描画は "予定" だが原文は "予定:" のような差
    // a run altered for display: rendered "買い物リスト 今日" but the source line carries extra markup
    const altered = renderPreview("<h2>買い物リスト 今日</h2>");
    const alteredSource = "買い物リスト: 今日\n\n牛乳";
    const node = textNode(altered, 0);
    expect(locateSourceOffset(altered, alteredSource, { node, offset: 8 })).toBe(alteredSource.indexOf("今日") + 1);
  });

  it("treats an element hit as the start of its first text run and rejects nodes outside the root", () => {
    const root = renderPreview(html);
    const li = root.querySelector("li") as HTMLElement;
    expect(locateSourceOffset(root, source, { node: li, offset: 0 })).toBe(source.indexOf("図書館"));
    const outside = document.createTextNode("牛乳を買う");
    document.body.appendChild(outside);
    expect(locateSourceOffset(root, source, { node: outside, offset: 0 })).toBeNull();
    expect(locateSourceOffset(root, source, null)).toBeNull();
  });
});

describe("estimateSourceOffsetByRatio", () => {
  it("snaps to the start of the line at the given share of the text", () => {
    const source = "a\nbb\nccc\ndddd";
    expect(estimateSourceOffsetByRatio(source, 0)).toBe(0);
    expect(estimateSourceOffsetByRatio(source, 0.5)).toBe(5); // "ccc" starts after "a\nbb\n"
    expect(estimateSourceOffsetByRatio(source, 1)).toBe(9); // clamped to the last line
  });

  it("uses a character share when the text has no line breaks (legacy JSON-wrapped memos)", () => {
    const wrapped = JSON.stringify("一行目\n二行目\n三行目");
    expect(estimateSourceOffsetByRatio(wrapped, 0)).toBe(0);
    expect(estimateSourceOffsetByRatio(wrapped, 0.5)).toBe(Math.floor(wrapped.length / 2));
    expect(estimateSourceOffsetByRatio(wrapped, 2)).toBe(wrapped.length);
  });
});
