// 生成中の本文を毎回描き直させるためのテスト用ヘルパー。
// Test helper that makes a streaming answer body re-render on every update.

import { afterEach, beforeEach, vi } from "vitest";

// 描き直しが重いと次の描き直しは実時間で先送りされる。毎フレームの描き直しで DOM が保たれることを見る
// テストは、時計を止めてすべての更新を描かせる（先送りそのものは bot_message_html_render_pace のテストで見る）。
// describe の中で呼ぶ。
// A heavy render defers the next one by real time. Tests that check the DOM survives a re-render on every
// frame freeze the clock so each update is drawn (deferral itself is covered by the
// bot_message_html_render_pace tests). Call it inside a describe block.
export function renderEveryStreamingUpdate() {
  let clock: { mockRestore: () => void } | null = null;

  beforeEach(() => {
    clock = vi.spyOn(performance, "now").mockReturnValue(0);
  });

  afterEach(() => {
    clock?.mockRestore();
    clock = null;
  });
}
