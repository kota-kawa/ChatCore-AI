// ---------------------------------------------------------------------------
// Memo detail: click-to-edit guards
// ---------------------------------------------------------------------------

// プレビュー面のクリックのうち「編集に入る」意図と見なせるものだけを通す。
// リンクや操作部品のクリックはそのまま通常の動作に任せ、テキストをドラッグ選択した直後の
// クリック（コピー目的）も編集には切り替えない。
// Lets through only the preview-pane clicks that read as "start editing". Clicks on links or
// controls keep their normal behaviour, and a click that ends a drag selection (copying) does
// not switch modes either.
const INTERACTIVE_SELECTOR = "a, button, input, textarea, select, summary, [contenteditable=''], [contenteditable='true']";

export interface ClickToEditContext {
  target: EventTarget | null;
  defaultPrevented: boolean;
  selectionCollapsed: boolean;
}

export function shouldBeginEditingFromClick({ target, defaultPrevented, selectionCollapsed }: ClickToEditContext): boolean {
  if (defaultPrevented) return false;
  if (!selectionCollapsed) return false;
  const element = target as { closest?: (selector: string) => Element | null } | null;
  if (element && typeof element.closest === "function" && element.closest(INTERACTIVE_SELECTOR)) return false;
  return true;
}

// 現在の選択範囲が「点」かどうか。選択APIが無い環境では点として扱う。
// Whether the current selection is collapsed; environments without the API count as collapsed.
export function isSelectionCollapsed(doc: Document = document): boolean {
  const selection = doc.getSelection?.();
  if (!selection) return true;
  return selection.isCollapsed || selection.toString().length === 0;
}

// ---------------------------------------------------------------------------
// Click position → source offset → caret pixel position
// ---------------------------------------------------------------------------

export interface CaretPoint {
  node: Node;
  offset: number;
}

// クリック座標の直下にある文字位置を返す。標準の caretPositionFromPoint と WebKit 系の
// caretRangeFromPoint のどちらかを使い、どちらも無い環境では null。
// Resolves the character under a point via caretPositionFromPoint or WebKit's
// caretRangeFromPoint; null where neither exists.
export function resolveCaretFromPoint(doc: Document, x: number, y: number): CaretPoint | null {
  const withPosition = doc as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };
  if (typeof withPosition.caretPositionFromPoint === "function") {
    const position = withPosition.caretPositionFromPoint(x, y);
    return position ? { node: position.offsetNode, offset: position.offset } : null;
  }
  if (typeof withPosition.caretRangeFromPoint === "function") {
    const range = withPosition.caretRangeFromPoint(x, y);
    return range ? { node: range.startContainer, offset: range.startOffset } : null;
  }
  return null;
}

function textNodesOf(root: Node): Text[] {
  const nodes: Text[] = [];
  const walker = root.ownerDocument?.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */);
  if (!walker) return nodes;
  let current = walker.nextNode();
  while (current) {
    nodes.push(current as Text);
    current = walker.nextNode();
  }
  return nodes;
}

// 描画された Markdown 上のクリック位置を、元の Markdown 文字列の位置へ写す。
// クリックされたテキストノードの文面は（太字や見出し記号を除けば）原文にそのまま現れるので、
// 同じ文面のノードが何番目かを数えて原文中の同じ回目の出現を採る。見つからなければ null。
// Maps a click on the rendered Markdown back to an offset in the source string. The clicked
// text node's content appears verbatim in the source (markers like ** live outside text nodes),
// so the nth identical node is matched to the nth occurrence in the source. Null when no match.
export function locateSourceOffset(root: HTMLElement, source: string, caret: CaretPoint | null): number | null {
  if (!caret) return null;
  let node: Node | null = caret.node;
  let offsetInNode = caret.offset;
  if (node.nodeType !== 3 /* TEXT_NODE */) {
    // 要素が返ったときは、その中の最初のテキストの先頭とみなす
    // An element hit counts as the start of its first text run
    node = textNodesOf(node)[0] ?? null;
    offsetInNode = 0;
  }
  if (!node || !root.contains(node)) return null;

  const run = node.textContent ?? "";
  const needle = run.trim();
  if (!needle) return null;
  const leading = run.length - run.trimStart().length;

  const siblings = textNodesOf(root);
  const ordinal = siblings.filter((candidate) => candidate !== node && (candidate.textContent ?? "").trim() === needle)
    .filter((candidate) => candidate.compareDocumentPosition(node as Node) & 4 /* DOCUMENT_POSITION_FOLLOWING */).length;

  let index = -1;
  let from = 0;
  for (let i = 0; i <= ordinal; i += 1) {
    index = source.indexOf(needle, from);
    if (index < 0) break;
    from = index + needle.length;
  }
  if (index < 0) index = source.indexOf(needle);
  if (index < 0) return null;

  const within = Math.min(Math.max(offsetInNode - leading, 0), needle.length);
  return index + within;
}

// 見出しの無い箇所や写せなかった場合の代替: 面の中でのクリック位置の割合から行を推定する
// Fallback when the click cannot be mapped: estimate the line from the click's share of the pane
export function estimateSourceOffsetByRatio(source: string, ratio: number): number {
  const lines = source.split("\n");
  const lineIndex = Math.min(lines.length - 1, Math.max(0, Math.floor(ratio * lines.length)));
  let offset = 0;
  for (let i = 0; i < lineIndex; i += 1) offset += lines[i].length + 1;
  return offset;
}

const MIRRORED_STYLES = [
  "boxSizing", "width", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
  "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
  "fontFamily", "fontSize", "fontWeight", "fontStyle", "fontVariant", "letterSpacing", "lineHeight",
  "tabSize", "textIndent", "textTransform", "wordSpacing", "wordBreak", "overflowWrap",
] as const;

// textarea の指定位置にあるキャレットの、内容座標での上端（px）を測る。textarea は直接測れない
// ので、同じ字体・幅・折り返し規則の鏡を作り、そこまでの文章を流し込んで印の位置を読む。
// Measures the caret's top edge (px, content coordinates) at an offset. A textarea cannot be
// queried directly, so a mirror with the same font, width and wrapping is filled up to the
// offset and a marker's position is read back.
export function measureCaretTop(textarea: HTMLTextAreaElement, offset: number): number {
  const doc = textarea.ownerDocument;
  const view = doc.defaultView;
  if (!view) return 0;
  const computed = view.getComputedStyle(textarea);
  const mirror = doc.createElement("div");
  for (const property of MIRRORED_STYLES) {
    mirror.style[property] = computed[property];
  }
  mirror.style.position = "absolute";
  mirror.style.top = "0";
  mirror.style.left = "-9999px";
  mirror.style.visibility = "hidden";
  mirror.style.overflow = "hidden";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.width = `${textarea.clientWidth}px`;
  mirror.style.height = "auto";
  mirror.textContent = textarea.value.slice(0, offset);
  const marker = doc.createElement("span");
  marker.textContent = "​";
  mirror.appendChild(marker);
  doc.body.appendChild(mirror);
  const top = marker.offsetTop;
  mirror.remove();
  return top;
}
