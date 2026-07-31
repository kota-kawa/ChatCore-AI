// ストリーミング表示のスムージング（適応型タイプライター）ヘルパー。
// 受信チャンクの粒度（数十〜数百文字の塊）と表示の粒度を分離し、フレーム毎に
// 残量へ比例した文字数だけ表示を進める。残量が多いほど速く追いつき、少ない
// ほどゆっくり流れるため、生成に置いていかれずにチャンクの塊感だけが消える。
// Adaptive typewriter smoothing helpers for streamed chat text. They decouple
// the network chunk granularity from the display granularity: each frame the
// visible length advances proportionally to the undrained backlog, so the
// display keeps up with generation while chunks stop appearing as blocks.

// 1フレームあたりの最低表示文字数。60fpsで約120文字/秒が下限になる。
// Minimum characters revealed per frame (~120 chars/s at 60fps).
const MIN_CHARS_PER_FRAME = 2;

// 残量のうち1フレームで排出する割合。値が大きいほど追従が速く、塊感が戻る。
// Fraction of the backlog drained per frame. Higher values catch up faster
// but reintroduce the chunky look.
const BACKLOG_DRAIN_RATIO = 0.14;

// 表示済み文字数を目標文字数へ1フレーム分だけ近づける。
// 目標が縮んだ場合（生成UIフェンスの畳み込み等）は即座に目標へ合わせる。
// Advance the visible length one frame toward the target length. If the target
// shrank (e.g. a generative UI fence collapsed), snap to it immediately.
export function nextSmoothedLength(currentLength: number, targetLength: number): number {
  if (currentLength >= targetLength) return targetLength;
  const backlog = targetLength - currentLength;
  const step = Math.max(MIN_CHARS_PER_FRAME, Math.ceil(backlog * BACKLOG_DRAIN_RATIO));
  return Math.min(targetLength, currentLength + step);
}

// サロゲートペア（絵文字等）の途中で切らないよう、境界なら1文字分先へ進める。
// Never cut inside a surrogate pair (e.g. emoji); extend past the low
// surrogate when the boundary would split one.
export function clampToCodePointBoundary(text: string, length: number): number {
  if (length <= 0) return 0;
  if (length >= text.length) return text.length;
  const code = text.charCodeAt(length - 1);
  if (code >= 0xd800 && code <= 0xdbff) return length + 1;
  return length;
}
