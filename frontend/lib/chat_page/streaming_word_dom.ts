// 描画済みボットメッセージの末尾に、チャンクごとのフェードインを適用するDOM処理。
// 「新しく現れたひとかたまり」だけがふわりと立ち上がるようにする。1文字ずつでは
// 生成が速いときにタイプライターに見えるため、数語ぶんをまとめて1回で見せる。
// ストリーミング中は毎フレーム、clearStreamingWordRevealでspanを畳んでから差分
// パッチを当て、そのあとここで付け直す。負のanimation-delayで再生位置を引き継ぐ。
// DOM pass that fades in each newly revealed chunk at the tail of a rendered
// bot message, so a few words rise together instead of one character at a time
// (which reads as a typewriter when generation is fast). Every streaming frame
// folds these spans away through clearStreamingWordReveal, patches the DOM and
// applies them again here; they resume mid-animation via a negative
// animation-delay.

import type { RevealWord } from "./streaming_word_reveal";
import {
  WORD_REVEAL_DURATION_MS,
  WordRevealTimeline,
  segmentRevealChunks,
  segmentRevealWords,
} from "./streaming_word_reveal";

// アニメーションを適用しない要素。折り返しや強調表示が崩れやすいものを除外する。
// Elements left untouched: their layout or highlighting breaks when split.
const SKIP_ELEMENT_SELECTOR =
  "pre, code, svg, table, .katex, .web-search-sources, .web-search-citation, .copy-block-container";

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

// チャンクを、実際にアニメーションさせる区間へ切り分ける。ストリーミング中は
// 末尾のチャンクが文字を足しながら伸びるため、チャンク全体を1単位で扱うと
// 「表示済みの部分が巻き戻る」か「追記部分がフェード無しで出る」のどちらかに
// なる。表示済み境界と既存の予約位置で分割し、どちらも起こらないようにする。
// Cut a chunk into the spans that actually animate. While streaming, the last
// chunk keeps growing as characters arrive; treating it as one unit would
// either rewind the part already on screen or pop the appended part in with no
// fade. Splitting at the known boundary and at existing schedules avoids both.
function splitChunkStarts(
  chunk: RevealWord,
  entry: TextNodeEntry,
  wordStarts: Set<number>,
  timeline: WordRevealTimeline,
) {
  const offset = entry.start;
  const starts = new Set<number>([chunk.start]);
  const known = timeline.knownBoundary - offset;
  if (known > chunk.start && known < chunk.end) starts.add(known);
  timeline.scheduledStartsWithin(offset + chunk.start, offset + chunk.end).forEach((start) => {
    // 語頭に一致する予約だけを分割点にする。整形確定でテキストが差し替わると
    // 予約は文字数差でずらして引き継がれるため、語の途中を指す予約が残る。
    // それを再生単位にすると、表示済みのテキストが開始待ち（透明）に戻る。
    // Only schedules that land on a word start may split. A markdown reflow
    // shifts schedules by the length delta, which leaves some of them pointing
    // mid-word; reviving those would put visible text back into the queued
    // (transparent) state.
    if (wordStarts.has(start - offset)) starts.add(start - offset);
  });
  return Array.from(starts).sort((left, right) => left - right);
}

// 1つのテキストノードを、アニメーション対象の区間だけspanで包んだ断片へ置き換える。
// Replace one text node with a fragment whose animating spans are wrapped.
function wrapChunksInTextNode(
  entry: TextNodeEntry,
  tailStart: number,
  timeline: WordRevealTimeline,
  now: number,
) {
  const text = entry.node.data;
  const document_ = entry.node.ownerDocument;
  if (!document_) return;

  const fragment = document_.createDocumentFragment();
  const wordStarts = new Set(segmentRevealWords(text).map((word) => word.start));
  let cursor = 0;
  let hasWrappedChunk = false;

  segmentRevealChunks(text, entry.start).forEach((chunk) => {
    if (entry.start + chunk.start < tailStart) return;
    const starts = splitChunkStarts(chunk, entry, wordStarts, timeline);

    starts.forEach((start, index) => {
      const end = index + 1 < starts.length ? starts[index + 1] : chunk.end;
      const elapsed = timeline.elapsedFor(entry.start + start, now);
      // 再生し終えた区間はspanを付けず、素のテキストとして次の slice に含める。
      // A finished span is left as plain text and folded into the next slice.
      if (elapsed === null) return;

      if (start > cursor) {
        fragment.appendChild(document_.createTextNode(text.slice(cursor, start)));
      }
      const span = document_.createElement("span");
      span.className = REVEAL_WORD_CLASS;
      // 負のdelayは再生途中から再開、正のdelayは開始待ち（fill:bothで透明のまま）。
      // A negative delay resumes mid-play; a positive one waits to start
      // (fill: both keeps the text transparent until then).
      span.style.animationDelay = `${Math.round(-elapsed)}ms`;
      span.textContent = text.slice(start, end);
      fragment.appendChild(span);
      cursor = end;
      hasWrappedChunk = true;
    });
  });

  if (!hasWrappedChunk) return;
  if (cursor < text.length) {
    fragment.appendChild(document_.createTextNode(text.slice(cursor)));
  }
  entry.node.parentNode?.replaceChild(fragment, entry.node);
}

// 付与済みの単語spanを素のテキストへ戻し、隣接テキストノードを結合する。
// 差分パッチはHTMLの形と実DOMの形が一致していることを前提にするため、
// パッチ前にこの装飾を畳んでおく。再生位置はWordRevealTimelineが持っており、
// パッチ後の再適用で負のdelayとして引き継がれる。
// Unwrap the reveal spans back into plain text and merge adjacent text nodes.
// The DOM patch assumes the live tree has the same shape as the incoming HTML,
// so this decoration is folded away first. Playback position lives in the
// WordRevealTimeline and is restored as a negative delay when reveal is applied
// again after the patch.
export function clearStreamingWordReveal(container: HTMLElement) {
  const spans = Array.from(container.querySelectorAll<HTMLElement>(`span.${REVEAL_WORD_CLASS}`));
  if (spans.length === 0) return;

  spans.forEach((span) => {
    const parent = span.parentNode;
    const document_ = span.ownerDocument;
    if (!parent || !document_) return;
    parent.replaceChild(document_.createTextNode(span.textContent ?? ""), span);
  });
  container.normalize();
}

// 描画直後のコンテナへ単語フェードインを適用する。
// Apply the per-word fade-in to a freshly rendered container.
export function applyStreamingWordReveal(
  container: HTMLElement,
  timeline: WordRevealTimeline,
  now = nowMs(),
) {
  const { entries, total } = collectTextNodes(container);
  // 予約の追従（差分リマップ）にはオフセットだけでなく本文が必要。
  // The remap that keeps schedules aligned needs the text, not just lengths.
  timeline.sync(entries.map((entry) => entry.node.data).join(""));
  container.style.setProperty(REVEAL_DURATION_PROPERTY, `${WORD_REVEAL_DURATION_MS}ms`);

  const tailStart = Math.max(0, total - REVEAL_TAIL_CHARS);
  entries.forEach((entry) => {
    if (entry.start + entry.node.data.length <= tailStart) return;
    wrapChunksInTextNode(entry, tailStart, timeline, now);
  });

  timeline.prune(tailStart);
}
