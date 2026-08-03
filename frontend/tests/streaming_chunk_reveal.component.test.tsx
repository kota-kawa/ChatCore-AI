import { describe, expect, it } from "vitest";

import {
  advanceStreamPace,
  clampToCodePointBoundary,
  createStreamPace,
} from "../lib/chat_page/stream_smoothing";
import { applyStreamingWordReveal } from "../lib/chat_page/streaming_word_dom";
import {
  WordRevealTimeline,
  clampToRevealChunkBoundary,
  clampToWordBoundary,
} from "../lib/chat_page/streaming_word_reveal";

// 生成中の1フレーム分。ペーシング → 表示長のクランプ → DOMのフェードインまで、
// use_home_page_generation_actions が毎フレーム行う流れをそのまま再現する。
// One streaming frame: pacing → visible-length clamp → DOM fade-in, mirroring
// what use_home_page_generation_actions does on every animation frame.
const FRAME_MS = 16;
const GENERATION_CHARS_PER_MS = 0.2;
const SOURCE =
  "今日はいい天気ですね、散歩に出かけましょう。近くの公園では桜が咲いていて、" +
  "写真を撮る人でにぎわっています。帰りにコーヒーでも買って、ゆっくり歩きませんか。";

type FrameState = {
  displayLength: number;
  // 文字位置ごとの状態。opaque は表示中、queued は開始待ち（=透明）。
  // Per-character state: opaque is on screen, queued is waiting (transparent).
  queued: Set<number>;
};

function readCharacterStates(container: HTMLElement): Set<number> {
  const queued = new Set<number>();
  let index = 0;
  const paragraph = container.firstElementChild;
  Array.from(paragraph?.childNodes ?? []).forEach((node) => {
    const text = node.textContent ?? "";
    const delay =
      node.nodeType === Node.ELEMENT_NODE
        ? Number.parseInt((node as HTMLElement).style.animationDelay, 10)
        : 0;
    if (delay > 0) {
      for (let offset = 0; offset < text.length; offset += 1) queued.add(index + offset);
    }
    index += text.length;
  });
  return queued;
}

function runStreamingFrames(): FrameState[] {
  const pace = createStreamPace(0, 0);
  const timeline = new WordRevealTimeline();
  const container = document.createElement("div");
  document.body.appendChild(container);
  const frames: FrameState[] = [];

  for (let frame = 0; frame * FRAME_MS < 6000; frame += 1) {
    const now = frame * FRAME_MS;
    const arrived = Math.min(SOURCE.length, Math.floor(now * GENERATION_CHARS_PER_MS));
    const pacedText = SOURCE.slice(0, arrived);
    const smoothed = clampToCodePointBoundary(
      pacedText,
      advanceStreamPace(pace, pacedText.length, now),
    );
    const displayLength = clampToCodePointBoundary(
      pacedText,
      clampToWordBoundary(pacedText, clampToRevealChunkBoundary(pacedText, smoothed)),
    );

    container.innerHTML = `<p>${pacedText.slice(0, displayLength)}</p>`;
    applyStreamingWordReveal(container, timeline, now);
    frames.push({ displayLength, queued: readCharacterStates(container) });
    if (displayLength >= SOURCE.length) break;
  }

  return frames;
}

describe("streamed reveal, end to end", () => {
  it("grows the visible text in chunks instead of one character per frame", () => {
    const steps = runStreamingFrames()
      .map((frame, index, all) => (index === 0 ? 0 : frame.displayLength - all[index - 1].displayLength))
      .filter((step) => step > 0);

    // 1文字ずつ伸びない＝生成中の行が折り返し直しになる回数がその分減る。
    // Not growing one character at a time is exactly what makes the streaming
    // line re-wrap less often.
    expect(Math.min(...steps)).toBeGreaterThanOrEqual(2);
    const average = steps.reduce((total, step) => total + step, 0) / steps.length;
    expect(average).toBeGreaterThanOrEqual(5);
    expect(steps.length).toBeLessThan(SOURCE.length / 4);
  });

  it("never turns text that is already on screen back to transparent", () => {
    const frames = runStreamingFrames();
    const shown = new Set<number>();

    frames.forEach((frame, index) => {
      frame.queued.forEach((position) => {
        expect(shown.has(position), `character ${position} hid again on frame ${index}`).toBe(false);
      });
      for (let position = 0; position < frame.displayLength; position += 1) {
        if (!frame.queued.has(position)) shown.add(position);
      }
    });

    expect(frames.at(-1)?.displayLength).toBe(SOURCE.length);
  });
});
