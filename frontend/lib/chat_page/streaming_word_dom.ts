// 描画済みボットメッセージの末尾に、単語ごとのフェードインを適用するDOM処理。
// ChatGPT / Claude と同様に「新しく現れた語だけ」がふわりと立ち上がるようにする。
// メッセージはストリーミング中フレーム毎にHTMLごと差し替わるため、ここで付ける
// spanも毎フレーム作り直される。負のanimation-delayで再生位置を引き継ぐ。
// DOM pass that fades in each newly revealed word at the tail of a rendered bot
// message, the way ChatGPT / Claude reveal their output. The message HTML is
// replaced every frame while streaming, so these spans are rebuilt every frame
// and resume mid-animation through a negative animation-delay.

import {
  WORD_REVEAL_DURATION_MS,
  WordRevealTimeline,
  segmentRevealWords,
} from "./streaming_word_reveal";

// アニメーションを適用しない要素。折り返しや強調表示が崩れやすいものを除外する。
// Elements left untouched: their layout or highlighting breaks when split.
const SKIP_ELEMENT_SELECTOR = "pre, code, svg, table, .katex, .web-search-sources";

// 末尾から遡ってアニメーション対象にする文字数。生成中の末尾だけで十分なので、
// 長い応答でも1フレームあたりの処理量が一定に保たれる。
// How many trailing characters are considered. Only the growing tail needs the
// animation, which keeps the per-frame cost flat for long responses.
const REVEAL_TAIL_CHARS = 320;

// 再生時間をCSSへ渡すカスタムプロパティ名。TSとCSSで値がずれないようにする。
// Custom property that hands the duration to CSS so TS and CSS cannot drift.
const REVEAL_DURATION_PROPERTY = "--streaming-word-duration";

// 単語spanに付与するクラス名。CSS側のキーフレーム定義と対応する。
// Class applied to each word span; paired with the CSS keyframes.
const REVEAL_WORD_CLASS = "streaming-word";

type TextNodeEntry = {
  node: Text;
  start: number;
};

function nowMs() {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}

// 対象コンテナ内のテキストノードを出現順に集め、先頭からのオフセットを添える。
// Collect the container's text nodes in document order with their offsets.
function collectTextNodes(container: HTMLElement) {
  const walker = container.ownerDocument.createTreeWalker(
    container,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        if (node.nodeType !== Node.ELEMENT_NODE) return NodeFilter.FILTER_ACCEPT;
        // 除外対象は子孫ごと飛ばし、それ以外の要素は自身だけ飛ばして中身を辿る。
        // Reject skips the whole subtree; other elements are traversed into.
        return (node as Element).matches(SKIP_ELEMENT_SELECTOR)
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_SKIP;
      },
    },
  );

  const entries: TextNodeEntry[] = [];
  let total = 0;
  let current = walker.nextNode();
  while (current) {
    const node = current as Text;
    entries.push({ node, start: total });
    total += node.data.length;
    current = walker.nextNode();
  }

  return { entries, total };
}

// 1つのテキストノードを、アニメーション対象の語だけspanで包んだ断片へ置き換える。
// Replace one text node with a fragment whose animating words are wrapped.
function wrapWordsInTextNode(
  entry: TextNodeEntry,
  tailStart: number,
  timeline: WordRevealTimeline,
  now: number,
) {
  const text = entry.node.data;
  const document_ = entry.node.ownerDocument;
  if (!document_) return;

  const fragment = document_.createDocumentFragment();
  let cursor = 0;
  let hasWrappedWord = false;

  segmentRevealWords(text).forEach((word) => {
    const absoluteStart = entry.start + word.start;
    if (absoluteStart < tailStart) return;
    const elapsed = timeline.elapsedFor(absoluteStart, now);
    if (elapsed === null) return;

    if (word.start > cursor) {
      fragment.appendChild(document_.createTextNode(text.slice(cursor, word.start)));
    }
    const span = document_.createElement("span");
    span.className = REVEAL_WORD_CLASS;
    // 負のdelayは再生途中から再開、正のdelayは開始待ち（fill:bothで透明のまま）。
    // A negative delay resumes mid-play; a positive one waits to start
    // (fill: both keeps the word transparent until then).
    span.style.animationDelay = `${Math.round(-elapsed)}ms`;
    span.textContent = text.slice(word.start, word.end);
    fragment.appendChild(span);
    cursor = word.end;
    hasWrappedWord = true;
  });

  if (!hasWrappedWord) return;
  if (cursor < text.length) {
    fragment.appendChild(document_.createTextNode(text.slice(cursor)));
  }
  entry.node.parentNode?.replaceChild(fragment, entry.node);
}

// 描画直後のコンテナへ単語フェードインを適用する。
// Apply the per-word fade-in to a freshly rendered container.
export function applyStreamingWordReveal(
  container: HTMLElement,
  timeline: WordRevealTimeline,
  now = nowMs(),
) {
  const { entries, total } = collectTextNodes(container);
  timeline.sync(total);
  container.style.setProperty(REVEAL_DURATION_PROPERTY, `${WORD_REVEAL_DURATION_MS}ms`);

  const tailStart = Math.max(0, total - REVEAL_TAIL_CHARS);
  entries.forEach((entry) => {
    if (entry.start + entry.node.data.length <= tailStart) return;
    wrapWordsInTextNode(entry, tailStart, timeline, now);
  });

  timeline.prune(tailStart);
}
