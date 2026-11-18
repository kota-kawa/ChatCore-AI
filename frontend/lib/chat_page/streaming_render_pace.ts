// 生成中の本文の描き直しを、直前の描き直しにかかった時間に応じて間引く。
// 本文は伸びるたびに全文を Markdown 解析・サニタイズ・DOM 差分へ通すため、1 回の時間は本文の長さに比例し、
// 長い表やコードでは 1 フレームを超える。毎フレーム描き続けるとメインスレッドが空かず、入力やタップが
// 待たされる。重いときだけ次の描き直しを遅らせ、かかった時間と同じだけメインスレッドを空ける。
// Paces the re-render of a streaming answer body by how long the previous re-render took.
// Every growth re-runs Markdown parsing, sanitizing and the DOM patch over the whole text, so the cost
// scales with its length and exceeds a frame for long tables or code. Re-rendering on every frame then
// leaves the main thread no idle time, and typing or taps have to wait. Only heavy renders are spaced
// out, leaving the main thread free for as long as the render took.

// これ以下で終わる描き直しは間引かない。60fps の 1 フレーム（約 16.7ms）の半分で、通常の長さの回答は
// 今までどおり毎フレーム更新される。
// Renders at or under this cost are never spaced out. It is half of a 60fps frame (about 16.7ms), so
// answers of ordinary length keep updating every frame as before.
export const STREAM_RENDER_FREE_COST_MS = 8;

// 次の描き直しまでに空ける時間の上限。描き直しがどれだけ重くても、届いた本文の表示をこれ以上は遅らせない。
// Cap on the gap before the next render: however heavy a render is, received text is not held back longer.
export const MAX_STREAM_RENDER_GAP_MS = 250;

// 直前の描き直しにかかった時間から、次の描き直しまでに空ける時間を返す。
// Returns how long to leave before the next render, given the cost of the previous one.
export function streamRenderGapMs(lastRenderCostMs: number): number {
  if (!(lastRenderCostMs > STREAM_RENDER_FREE_COST_MS)) return 0;
  return Math.min(lastRenderCostMs, MAX_STREAM_RENDER_GAP_MS);
}
