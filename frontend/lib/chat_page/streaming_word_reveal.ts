// ストリーミング表示の「単語」単位ヘルパー。ChatGPT / Claude の出力と同じく、
// ラテン語は単語単位、日本語などのCJKは1文字単位で現れるのが自然に見えるため、
// 表示位置のクランプとアニメーション対象の切り出しを同じ語境界の定義で扱う。
// Word-level helpers for streamed text. Like ChatGPT / Claude, Latin script
// reads best when it appears one whole word at a time while CJK reads best one
// character at a time, so both the reveal clamp and the animation segmentation
// share a single definition of a word boundary.

// 1文字単位で現れて欲しいCJK系の文字範囲（かな・漢字・全角記号など）。
// CJK ranges (kana, ideographs, fullwidth forms) revealed one char at a time.
const CJK_PATTERN =
  /[\u3000-\u303f\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]/;

// ラテン語の単語を構成する文字。ここに該当する文字が連続する間は語の途中とみなす。
// Characters that make up a Latin word; a run of them is treated as mid-word.
const WORD_CHAR_PATTERN = /[\p{L}\p{N}'’_]/u;

// 長いトークン（URL やハッシュ等）で表示が止まらないよう、語頭探索の上限を設ける。
// Cap the backward scan so a long token (URL, hash, …) cannot stall the reveal.
const MAX_WORD_BOUNDARY_LOOKBACK = 40;

// 単語のフェードイン時間。CSS 側の再生時間もこの値を用いる。
// Fade-in duration for one word; the CSS animation is driven by this value too.
export const WORD_REVEAL_DURATION_MS = 280;

// 1文字で1語として扱うCJK文字かどうか。
// Whether the character is CJK and therefore a word on its own.
export function isCjkChar(char: string) {
  return CJK_PATTERN.test(char);
}

// ラテン語の語中文字かどうか（CJKは常に語境界なのでfalse）。
// Whether the character continues a Latin word (CJK is always a boundary).
function isLatinWordChar(char: string) {
  return !isCjkChar(char) && WORD_CHAR_PATTERN.test(char);
}

// 表示範囲。start は含み、end は含まない。
// A revealed span of text; start is inclusive and end is exclusive.
export type RevealWord = {
  start: number;
  end: number;
};

// テキストをアニメーション単位へ分割する。空白は語に含めず、CJKは1文字ずつ、
// それ以外は空白で区切られた連続文字をひとかたまりの語として扱う。
// Split text into animation units: whitespace is excluded, CJK becomes one word
// per character, and every other run between whitespace becomes a single word.
export function segmentRevealWords(text: string): RevealWord[] {
  const words: RevealWord[] = [];
  let wordStart = -1;

  const flush = (end: number) => {
    if (wordStart < 0) return;
    words.push({ start: wordStart, end });
    wordStart = -1;
  };

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (/\s/.test(char)) {
      flush(index);
      continue;
    }
    if (isCjkChar(char)) {
      flush(index);
      words.push({ start: index, end: index + 1 });
      continue;
    }
    if (wordStart < 0) wordStart = index;
  }
  flush(text.length);

  return words;
}

// 表示文字数を語境界まで巻き戻し、ラテン語が途中で切れて見えないようにする。
// 語頭が見つからない、または探索上限に達した場合は元の長さをそのまま返す。
// Pull the visible length back to a word boundary so a Latin word never shows
// half-typed. Falls back to the given length when no boundary is found in range.
export function clampToWordBoundary(text: string, length: number): number {
  if (length >= text.length) return text.length;
  if (length <= 0) return 0;

  let index = length;
  let steps = 0;
  while (index > 0 && isLatinWordChar(text[index - 1]) && isLatinWordChar(text[index])) {
    if (steps >= MAX_WORD_BOUNDARY_LOOKBACK) return length;
    index -= 1;
    steps += 1;
  }

  return index <= 0 ? length : index;
}

// 語ごとの初出時刻を覚え、再描画のたびにアニメーションが先頭へ巻き戻るのを防ぐ。
// ボットメッセージは毎フレームHTMLごと差し替わるため、経過時間を負の
// animation-delay として与えて再生位置を復元する必要がある。
// Remembers when each word first appeared so a re-render does not restart its
// animation. The bot message is re-rendered from HTML every frame, so the
// elapsed time is replayed as a negative animation-delay.
export class WordRevealTimeline {
  private readonly firstSeenAt = new Map<number, number>();

  private lastTextLength = 0;

  // テキストが縮んだ場合はオフセットの意味が変わるため記録を破棄する。
  // Drop the timestamps when the text shrinks: offsets no longer line up.
  sync(textLength: number) {
    if (textLength < this.lastTextLength) this.firstSeenAt.clear();
    this.lastTextLength = textLength;
  }

  // 語の初出からの経過時間（ms）。再生済みの語は null を返す。
  // Elapsed ms since the word first appeared, or null once it finished playing.
  elapsedFor(wordStart: number, now: number): number | null {
    const seenAt = this.firstSeenAt.get(wordStart);
    if (seenAt === undefined) {
      this.firstSeenAt.set(wordStart, now);
      return 0;
    }
    const elapsed = now - seenAt;
    return elapsed >= WORD_REVEAL_DURATION_MS ? null : Math.max(0, elapsed);
  }

  // アニメーション対象範囲から外れた記録を捨てる。時間ではなく位置で捨てるのは、
  // 生成が遅い場合に再登録されて同じ語がもう一度光るのを防ぐため。
  // Drop records that fell out of the animated tail. Pruning by position rather
  // than by age keeps a slow stream from re-registering — and re-animating — a
  // word that is still on screen.
  prune(minWordStart: number) {
    this.firstSeenAt.forEach((_seenAt, wordStart) => {
      if (wordStart < minWordStart) this.firstSeenAt.delete(wordStart);
    });
  }
}
