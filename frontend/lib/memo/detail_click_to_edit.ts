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

// 要素がヒットしたとき（段落の間の余白など）は、offset 番目の子の位置にあるテキストへ寄せる。
// 子の数を超えていれば末尾のテキストの終わり、それ以外はその子の最初のテキストの先頭。
// For an element hit (e.g. the gap between paragraphs), settle on the text at the offset-th child:
// past the last child means the end of the last text run, otherwise the start of that child's first run.
function textPointInElement(element: Node, childOffset: number): CaretPoint | null {
  const children = element.childNodes;
  if (childOffset >= children.length) {
    const runs = textNodesOf(element);
    const last = runs[runs.length - 1];
    return last ? { node: last, offset: (last.textContent ?? "").length } : null;
  }
  for (let i = childOffset; i < children.length; i += 1) {
    const child = children[i];
    const first = child.nodeType === 3 /* TEXT_NODE */ ? (child as Text) : textNodesOf(child)[0];
    if (first) return { node: first, offset: 0 };
  }
  const runs = textNodesOf(element);
  const last = runs[runs.length - 1];
  return last ? { node: last, offset: (last.textContent ?? "").length } : null;
}

// 同じ文面のテキストノードのうち何番目か（文書順）/ Ordinal of this node among identical runs, in document order
function ordinalAmongIdenticalRuns(root: HTMLElement, node: Text, needle: string): number {
  return textNodesOf(root)
    .filter((candidate) => candidate !== node && (candidate.textContent ?? "").trim() === needle)
    .filter((candidate) => candidate.compareDocumentPosition(node) & 4 /* DOCUMENT_POSITION_FOLLOWING */).length;
}

function nthIndexOf(source: string, needle: string, ordinal: number): number {
  let index = -1;
  let from = 0;
  for (let i = 0; i <= ordinal; i += 1) {
    index = source.indexOf(needle, from);
    if (index < 0) return -1;
    from = index + needle.length;
  }
  return index;
}

const PARTIAL_MATCH_RADIUS = 6;

// 描画された Markdown 上のクリック位置を、textarea が表示している元の文字列の位置へ写す。
// テキストノードの文面は多くの場合そのまま原文に現れる（** などの記号はノードの外にある）ので、
// 同じ文面のノードが何番目かを数え、原文中の同じ回目の出現を採る。表示前の正規化（見出しの
// 昇格、参照表示の除去など）で文面が変わっていて見つからないときは、クリック位置の前後だけを
// 切り出した短い断片で再照合する。それでも見つからなければ null。
// Maps a click on the rendered Markdown back to an offset in the raw string the textarea shows.
// A text node's content usually appears verbatim in the source (markers like ** live outside text
// nodes), so the nth identical node is matched to the nth occurrence. When display normalisation
// (heading promotion, stripped references, …) changed the run and it is not found, a short
// fragment around the click is tried instead. Null when nothing matches.
export function locateSourceOffset(root: HTMLElement, source: string, caret: CaretPoint | null): number | null {
  if (!caret) return null;
  const point = caret.node.nodeType === 3 /* TEXT_NODE */ ? caret : textPointInElement(caret.node, caret.offset);
  if (!point || !root.contains(point.node)) return null;
  const node = point.node as Text;

  const run = node.textContent ?? "";
  const needle = run.trim();
  if (!needle) return null;
  const leading = run.length - run.trimStart().length;
  const within = Math.min(Math.max(point.offset - leading, 0), needle.length);

  const exact = nthIndexOf(source, needle, ordinalAmongIdenticalRuns(root, node, needle));
  if (exact >= 0) return exact + within;
  const first = source.indexOf(needle);
  if (first >= 0) return first + within;

  // 変わった箇所を避けるため、クリック位置を中心に窓を狭めながら照合する（2 文字未満は採らない）
  // Shrink a window around the click so the altered part falls outside it; fragments under 2 chars are skipped
  for (let radius = PARTIAL_MATCH_RADIUS; radius >= 1; radius -= 1) {
    const start = Math.max(0, within - radius);
    const raw = needle.slice(start, within + radius);
    const leadingTrim = raw.length - raw.trimStart().length;
    const fragment = raw.trim();
    if (fragment.length < 2) continue;
    const partial = source.indexOf(fragment);
    if (partial >= 0) return partial + Math.min(Math.max(within - start - leadingTrim, 0), fragment.length);
  }
  return null;
}

// 写せなかった場合の代替: 面の中でのクリック位置の割合から行を推定する。改行が無い文字列
// （JSON 包みの旧データなど）では行が一つしか無いので、文字数の割合に切り替える。
// Fallback when the click cannot be mapped: estimate the line from the click's share of the pane.
// A string without newlines (e.g. legacy JSON-wrapped data) has a single line, so use a character share.
export function estimateSourceOffsetByRatio(source: string, ratio: number): number {
  const clamped = Math.min(1, Math.max(0, ratio));
  const lines = source.split("\n");
  if (lines.length < 2) return Math.floor(clamped * source.length);
  const lineIndex = Math.min(lines.length - 1, Math.floor(clamped * lines.length));
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
