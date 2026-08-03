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
export const WORD_REVEAL_DURATION_MS = 360;

// 同じフレームで届いた語同士の開始時刻をずらす間隔。生成が速いとチャンク内の
// 全語が同時初出になり「末尾が一瞬ぼやけるだけ」に見えるため、開始をこの間隔で
// カスケードさせて語が順に立ち上がるようにする。
// Start-time offset between words that arrive in the same frame. A fast stream
// makes every word of a chunk first-seen at once, which reads as "the tail
// blurs for an instant"; cascading the starts makes words light up in order.
export const WORD_REVEAL_STAGGER_MS = 14;

// カスケードがテキスト到達より遅れてよい上限。これを超える語は上限位置へ
// まとめて畳むので、出力速度自体は落ちない。
// Cap on how far the cascade may trail the text. Words beyond it collapse onto
// the cap, so the output speed itself never slows down.
export const WORD_REVEAL_MAX_LAG_MS = 240;

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

// 語ごとの再生開始時刻を管理し、再描画のたびにアニメーションが先頭へ巻き戻る
// のを防ぐ。初出の語には直前の語から WORD_REVEAL_STAGGER_MS ずらした開始時刻を
// 予約し（遅れ上限は WORD_REVEAL_MAX_LAG_MS）、同時に届いた語もカスケードして
// 現れるようにする。ボットメッセージは毎フレームHTMLごと差し替わるため、
// 経過時間を animation-delay（負=再生途中、正=開始待ち）として復元する。
// Tracks each word's scheduled start so a re-render does not restart its
// animation. A newly seen word is scheduled WORD_REVEAL_STAGGER_MS after the
// previous one (trailing at most WORD_REVEAL_MAX_LAG_MS), so words that arrive
// together still cascade. The bot message is re-rendered from HTML every
// frame, so elapsed time is replayed via animation-delay (negative = mid-play,
// positive = not started yet).
export class WordRevealTimeline {
  private readonly scheduledAt = new Map<number, number>();

  private lastText = "";

  private lastScheduledAt = Number.NEGATIVE_INFINITY;

  // 表示テキストの変化に予約を追従させる。純粋な追記なら何もしない。Markdownの
  // 整形確定（例: `**強調` が `<strong>` になり `**` が消える）ではテキストが
  // 途中から差し替わるため、共通接頭辞より後ろの予約を長さ差分だけずらして
  // 引き継ぐ。以前はここで全予約を破棄していたため、表示済みの語まで透明に
  // 戻ってもう一度フェードしていた。
  // Keep the schedule aligned with the rendered text. A pure append needs
  // nothing. When markdown finalizes (e.g. `**bold` collapses into <strong>
  // and the `**` disappears) the text changes mid-way, so entries past the
  // common prefix shift by the length delta. Clearing everything here — the
  // old behaviour — made already-visible words go transparent and fade again.
  sync(text: string) {
    const previous = this.lastText;
    this.lastText = text;
    if (previous === text || text.startsWith(previous)) return;

    let divergence = 0;
    const comparable = Math.min(previous.length, text.length);
    while (divergence < comparable && previous.charCodeAt(divergence) === text.charCodeAt(divergence)) {
      divergence += 1;
    }

    const delta = text.length - previous.length;
    const remapped: Array<[number, number]> = [];
    this.scheduledAt.forEach((scheduled, offset) => {
      const nextOffset = offset < divergence ? offset : offset + delta;
      if (nextOffset >= 0 && nextOffset < text.length) remapped.push([nextOffset, scheduled]);
    });
    this.scheduledAt.clear();
    remapped.forEach(([offset, scheduled]) => {
      this.scheduledAt.set(offset, scheduled);
    });
  }

  // 語の開始時刻からの経過時間（ms）。開始前の語は負値を返し、再生済みの語は
  // null を返す。初出の語はここで開始時刻を予約する。
  // Elapsed ms since the word's scheduled start: negative before it starts,
  // null once it finished. A first-seen word gets its slot reserved here.
  elapsedFor(wordStart: number, now: number): number | null {
    let scheduled = this.scheduledAt.get(wordStart);
    if (scheduled === undefined) {
      scheduled = Math.min(
        Math.max(now, this.lastScheduledAt + WORD_REVEAL_STAGGER_MS),
        now + WORD_REVEAL_MAX_LAG_MS,
      );
      this.lastScheduledAt = scheduled;
      this.scheduledAt.set(wordStart, scheduled);
    }
    const elapsed = now - scheduled;
    return elapsed >= WORD_REVEAL_DURATION_MS ? null : elapsed;
  }

  // アニメーション対象範囲から外れた記録を捨てる。時間ではなく位置で捨てるのは、
  // 生成が遅い場合に再登録されて同じ語がもう一度光るのを防ぐため。
  // Drop records that fell out of the animated tail. Pruning by position rather
  // than by age keeps a slow stream from re-registering — and re-animating — a
  // word that is still on screen.
  prune(minWordStart: number) {
    this.scheduledAt.forEach((_scheduledAt, wordStart) => {
      if (wordStart < minWordStart) this.scheduledAt.delete(wordStart);
    });
  }
}
