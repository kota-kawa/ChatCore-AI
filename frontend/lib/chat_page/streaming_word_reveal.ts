// ストリーミング表示の分割ヘルパー。まずテキストを語（ラテン語は単語、CJKは
// 1文字）へ分け、その語を数語ぶんの「チャンク」へまとめる。表示位置のクランプも
// アニメーション対象の切り出しも、このチャンクを単位にする。1文字ずつだと生成が
// 速いときにタイプライターにしか見えず、行の折り返しも毎フレーム変わってしまう。
// Segmentation helpers for streamed text. Text is first split into words (whole
// words for Latin, single characters for CJK), then those words are gathered
// into chunks of a few words. Both the reveal clamp and the animation units
// work in chunks: revealing one character at a time reads as a typewriter when
// generation is fast, and re-wraps the line on every single frame.

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

// 1回のフェードイン時間。CSS 側の再生時間もこの値を用いる。
// Fade-in duration for one reveal unit; the CSS animation uses this value too.
export const WORD_REVEAL_DURATION_MS = 420;

// 同じフレームで届いた表示単位同士の開始時刻をずらす間隔。1フレームに複数の
// かたまりが現れる場合でも、同時に光らず順に立ち上がるようにする。
// Start-time offset between units that arrive in the same frame, so several
// chunks landing together still light up one after another.
export const WORD_REVEAL_STAGGER_MS = 45;

// カスケードがテキスト到達より遅れてよい上限。これを超える単位は上限位置へ
// まとめて畳むので、出力速度自体は落ちない。
// Cap on how far the cascade may trail the text. Units beyond it collapse onto
// the cap, so the output speed itself never slows down.
export const WORD_REVEAL_MAX_LAG_MS = 320;

// 1つの表示単位（チャンク）に入れる最大文字数。1文字ずつのタイプライター表示に
// 見えないよう、語をこの長さまでまとめてから1回のフェードで見せる。
// Maximum characters in one reveal chunk. Words are grouped up to this length
// and faded in together so the output does not read as a typewriter.
export const REVEAL_CHUNK_MAX_CHARS = 16;

// 句読点でチャンクを閉じてよい最小文字数。「はい、」のような短すぎる断片が
// 独立したチャンクになるのを防ぐ。
// Minimum length before a clause break may close a chunk, so a tiny fragment
// like "はい、" does not become a chunk of its own.
const REVEAL_CHUNK_MIN_CHARS = 4;

// 表示文字数を進める刻み幅。これがスマホでの行の揺れを抑える要で、表示長が
// この単位でしか伸びないため、折り返しが変わる回数が1/10程度になる。
// Step size for the visible length. This is what calms the line jitter on
// narrow screens: the text only grows in these steps, so the number of
// re-wraps drops by roughly a factor of ten.
export const REVEAL_CHUNK_STEP_CHARS = 10;

// チャンクを早めに閉じてよい区切り文字。読点・句点や節の切れ目で閉じると、
// かたまりの切れ目が文章の意味と一致して自然に見える。
// Punctuation that may close a chunk early; breaking where the sentence breaks
// keeps the chunk boundaries aligned with the meaning of the text.
const CLAUSE_BREAK_PATTERN = /[、。，．！？!?;；:：…\n]/;

// 句読点を探して遡る上限。刻み幅の2倍までに限り、長文でも走査量を一定に保つ。
// Backward scan limit when looking for a clause break; capping it at twice the
// step keeps the per-frame cost constant for long responses.
const MAX_CLAUSE_BREAK_LOOKBACK = REVEAL_CHUNK_STEP_CHARS * 2;

// 1フレームでアニメーション対象にしてよい追記量の上限。パーツ更新・復元・
// 長い処理落ち明けなどでテキストが一括で飛び込んだ場合は、後からまとめて
// フェードさせず即時表示する。通常のストリーミングでは1フレームの追記が
// この量に達することはない。
// Cap on how much appended text may animate in one frame. When text lands in
// bulk (parts updates, restore, after a long stall) it shows instantly instead
// of fading in afterwards; ordinary streaming never appends this much per frame.
export const MAX_ANIMATED_APPEND_CHARS = 240;

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

// 語をアニメーションの表示単位（チャンク）へまとめる。1語＝1フェードだと、
// 日本語は1文字ずつのタイプライターに見えてしまうため、語をまとめて1回の
// フェードで見せる。区切りは表示側と同じ REVEAL_CHUNK_STEP_CHARS のグリッドに
// 合わせる。合わせないとチャンクと表示の刻みがずれ、1〜2文字だけの半端な
// かたまりが毎回できてしまう。句読点や改行があればそこで早めに閉じる。
// offset は本文先頭からの位置。グリッドを本文全体で共有するために渡す。
// Group words into the units that actually animate. One fade per word makes
// Japanese read as a per-character typewriter, so words are revealed together.
// Chunks close on the same REVEAL_CHUNK_STEP_CHARS grid the visible length
// steps on: without that alignment the two grids drift apart and every step
// leaves a stray one or two character chunk behind. A clause break or a
// newline closes a chunk early. offset is the position of `text` within the
// whole message, so the grid is shared across text nodes.
export function segmentRevealChunks(text: string, offset = 0): RevealWord[] {
  const chunks: RevealWord[] = [];
  let start = -1;
  let end = -1;

  const flush = () => {
    if (start < 0) return;
    chunks.push({ start, end });
    start = -1;
    end = -1;
  };

  segmentRevealWords(text).forEach((word) => {
    if (start >= 0) {
      // 語を足すと上限を超える場合は、超える前に閉じて次のチャンクを始める。
      // Close before the word that would overflow, and start a new chunk.
      const overflows = word.end - start > REVEAL_CHUNK_MAX_CHARS;
      const breaksLine = /\n/.test(text.slice(end, word.start));
      if (breaksLine || (overflows && end - start >= REVEAL_CHUNK_MIN_CHARS)) flush();
    }
    if (start < 0) start = word.start;
    end = word.end;

    const size = end - start;
    const gridLine =
      Math.floor((offset + start) / REVEAL_CHUNK_STEP_CHARS) * REVEAL_CHUNK_STEP_CHARS +
      REVEAL_CHUNK_STEP_CHARS;
    const closesClause = CLAUSE_BREAK_PATTERN.test(text[end - 1]) && size >= REVEAL_CHUNK_MIN_CHARS;
    if (offset + end >= gridLine || size >= REVEAL_CHUNK_MAX_CHARS || closesClause) flush();
  });
  flush();

  return chunks;
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

// 表示文字数をチャンクの刻みへ丸める。1文字ずつ伸ばすと、生成中の行が毎フレーム
// 折り返し直しになって既に読める文字まで動いてしまう（特にスマホ）。刻み幅の
// グリッドまで巻き戻し、直前に句読点があればそこまでは見せることで、表示は
// かたまり単位でしか伸びなくなる。長さに対して単調で、平均速度は変わらない。
// Round the visible length down to the chunk step. Growing one character at a
// time re-wraps the line every frame and shifts characters the reader is
// already reading (worst on narrow screens). Falling back to the step grid —
// or to just after a nearby clause break, whichever is later — makes the text
// grow only in chunks. The result is monotonic in length and does not change
// the average speed.
export function clampToRevealChunkBoundary(text: string, length: number): number {
  if (length >= text.length) return text.length;
  if (length <= 0) return 0;

  const gridBoundary = length - (length % REVEAL_CHUNK_STEP_CHARS);
  const scanStart = Math.max(0, length - MAX_CLAUSE_BREAK_LOOKBACK);
  let clauseBoundary = 0;
  for (let index = length - 1; index >= scanStart; index -= 1) {
    if (CLAUSE_BREAK_PATTERN.test(text[index])) {
      clauseBoundary = index + 1;
      break;
    }
  }

  // 句読点で早めに見せるのは、刻みより十分先へ進める場合だけ。直前のグリッドの
  // すぐ後ろにある区切りを拾うと、1〜2文字だけ伸びる無意味な刻みが生まれる。
  // Only break early on punctuation when it is meaningfully ahead of the grid;
  // a break sitting right after the grid line would add a pointless step that
  // grows the text by one or two characters.
  const usesClause = clauseBoundary - gridBoundary >= REVEAL_CHUNK_MIN_CHARS;
  return usesClause ? clauseBoundary : gridBoundary;
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

  // 既知コンテンツの境界。これより前のオフセットは過去のフレームで描画済みの
  // 内容なので、予約を失っていても（pruneやリマップずれの後でも）決して
  // 透明へ戻さない。コードフェンスの確定でアニメ対象テキストが縮み、
  // アニメーション対象範囲が後退した場合などに、表示済みの語が「新規」として
  // 未来開始で再登録され、点滅してもう一度フェードする不具合を防ぐ。
  // Boundary of known content. Offsets below it were rendered in earlier
  // frames, so they must never turn transparent again even when their
  // schedule was lost (after prune or a remap mismatch). This is what stops
  // already-visible words from blinking and fading again when e.g. a code
  // fence finalizes, the animatable text shrinks and the tail window recedes.
  private knownEnd = 0;

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
    if (previous === text) return;
    if (text.startsWith(previous)) {
      // 純粋な追記: 前フレームまでの内容が既知コンテンツになる。一括追記は
      // アニメーションさせず全文を既知にする（後追いフェードの防止）。
      // Pure append: everything up to the previous frame is now known. A bulk
      // append marks the whole text known so nothing fades in after the fact.
      this.knownEnd =
        text.length - previous.length > MAX_ANIMATED_APPEND_CHARS ? text.length : previous.length;
      return;
    }

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

    // 差し替え後の既知境界は「前フレームの内容が新テキスト内で占める範囲」。
    // 差し替えと同時に追記された分だけが新規扱いになる。一括追記は即時表示。
    // After a reflow the known boundary is the extent the previous content
    // occupies in the new text; only what was appended alongside stays new,
    // and a bulk append still shows instantly.
    this.knownEnd = Math.max(0, Math.min(previous.length + delta, text.length));
    if (text.length - this.knownEnd > MAX_ANIMATED_APPEND_CHARS) this.knownEnd = text.length;
  }

  // 既に描画済みとみなす範囲の終端。伸長中のチャンクを「表示済みの部分」と
  // 「今フレームで現れた部分」へ分けるために描画側が参照する。
  // End of the content already on screen. The DOM pass uses it to split a
  // growing chunk into the part already shown and the part that just arrived.
  get knownBoundary() {
    return this.knownEnd;
  }

  // 指定範囲内で既に開始時刻を持つオフセット（昇順）。チャンクが伸びたとき、
  // 再生中の部分を同じ単位のまま切り出すために使う。ここで分割しないと、
  // 再生途中の語が素のテキストへ戻って不透明へ飛ぶ。
  // Offsets inside the range that already have a schedule, ascending. Used to
  // keep an in-flight part of a growing chunk as its own unit; without the
  // split it would revert to plain text and snap to full opacity mid-fade.
  scheduledStartsWithin(start: number, end: number): number[] {
    const starts: number[] = [];
    this.scheduledAt.forEach((_scheduledAt, offset) => {
      if (offset >= start && offset < end) starts.push(offset);
    });
    return starts.sort((left, right) => left - right);
  }

  // 語の開始時刻からの経過時間（ms）。開始前の語は負値を返し、再生済みの語は
  // null を返す。初出の語はここで開始時刻を予約する。
  // Elapsed ms since the word's scheduled start: negative before it starts,
  // null once it finished. A first-seen word gets its slot reserved here.
  elapsedFor(wordStart: number, now: number): number | null {
    let scheduled = this.scheduledAt.get(wordStart);
    if (scheduled === undefined) {
      // 既知コンテンツ内で予約が見つからない語は表示済み扱いにして素通しする。
      // ここで新規予約すると、表示済みの語が透明へ戻って点滅・再フェードする。
      // A known-content word without a schedule is treated as already shown.
      // Scheduling it afresh would turn visible text transparent again.
      if (wordStart < this.knownEnd) return null;
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
