// ストリーミング表示の等速ペーシング。受信チャンクの粒度（数十〜数百文字の塊）
// と表示の粒度を分離するのは従来どおりだが、残量に比例して毎フレーム加減速する
// 方式はやめ、到着レートへ時定数付きでゆっくり追従する速度で流す。チャンクが
// 大きく届いても表示速度は急変せず、ほぼ一定のスピードで文字が流れる。
// Constant-pace smoothing for streamed chat text. It still decouples network
// chunk granularity from display granularity, but instead of a backlog-
// proportional per-frame drain (which surged and stalled with each chunk), the
// reveal rate tracks the arrival rate through a time constant. Large chunks no
// longer change the visible speed abruptly; text flows at a near-constant pace.

// 残量をこの時間で排出する速度を目標レートとする。実質的な表示遅延の上限で、
// 生成がどれだけ速くてもテキスト到達からこの時間程度で表示が追いつく。
// The target rate drains the backlog over this window. It bounds the display
// latency: however fast generation is, the reveal trails by about this long.
const CATCH_UP_WINDOW_MS = 450;

// レートの平滑化時定数。大きいほど速度変化が緩やかになり、塊の到着が見えなくなる。
// Time constant for rate smoothing. Larger values hide chunk arrivals better.
const RATE_TAU_MS = 450;

// 最低表示速度（文字/ms）。残量がわずかでも止まって見えないようにする下限。
// Minimum reveal rate (chars/ms) so a tiny backlog never looks stalled.
const MIN_RATE_CHARS_PER_MS = 0.05;

// 1回の更新で進めてよい時間の上限。タブ非表示明けなどの巨大なdtで一気に
// 進んでしまわないようにする。
// Cap on the elapsed time per update so a huge dt (e.g. after the tab was
// hidden) cannot flush the whole backlog at once.
const MAX_FRAME_DT_MS = 100;

// 等速ペーシングの内部状態。lengthは小数のまま持ち、描画側で整数へ丸める。
// Mutable pacing state. length stays fractional; rendering floors it.
export type StreamPace = {
  length: number;
  rate: number;
  lastTime: number;
};

// 復元テキストなどの初期表示位置からペーシングを開始する。
// Start pacing from an initial visible length (e.g. restored text).
export function createStreamPace(initialLength: number, now: number): StreamPace {
  return { length: initialLength, rate: 0, lastTime: now };
}

// 表示位置を1フレーム分進め、表示してよい文字数（整数）を返す。
// 目標が縮んだ場合（生成UIフェンスの畳み込み等）は即座に目標へ合わせる。
// Advance the pace by one frame and return the visible length (integer). If
// the target shrank (e.g. a generative UI fence collapsed), snap to it.
export function advanceStreamPace(pace: StreamPace, targetLength: number, now: number): number {
  const dt = Math.min(Math.max(now - pace.lastTime, 0), MAX_FRAME_DT_MS);
  pace.lastTime = now;

  if (targetLength <= pace.length) {
    if (targetLength < pace.length) pace.length = targetLength;
    return Math.floor(pace.length);
  }

  const backlog = targetLength - pace.length;
  const targetRate = backlog / CATCH_UP_WINDOW_MS;
  if (pace.rate <= 0) {
    // 初回は到着レート相当から始め、立ち上がりの加速を見せない。
    // Start at the arrival-matched rate so there is no visible ramp-up.
    pace.rate = targetRate;
  } else {
    const blend = 1 - Math.exp(-dt / RATE_TAU_MS);
    pace.rate += (targetRate - pace.rate) * blend;
  }

  const rate = Math.max(pace.rate, MIN_RATE_CHARS_PER_MS);
  pace.length = Math.min(targetLength, pace.length + rate * dt);
  return Math.floor(pace.length);
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
