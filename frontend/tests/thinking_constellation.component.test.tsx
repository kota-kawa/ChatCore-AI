// 思考中インジケーターの星座が、どのフェーズ・どの切り替え時点でも舞台に収まる形で描かれることを検証する。
// Tests that the thinking-indicator constellations render inside the stage for every phase and step.

import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThinkingConstellation } from "../components/chat_page/thinking_constellation";
import {
  THINKING_CONSTELLATION_LINK_COUNT,
  THINKING_CONSTELLATION_NODE_COUNT,
  THINKING_CONSTELLATION_STEP_MS,
} from "../lib/chat_page/constants";
import type { ChatGenerationPhase } from "../lib/chat_page/types";

const PHASES: ChatGenerationPhase[] = ["preparing", "web-search", "generating"];
// どのフェーズの切り替え間隔よりも細かく刻み、最長のフェーズ（12 種）が一巡するまで調べる
// Sample more finely than any phase cadence, long enough for the longest phase (12 variants) to cycle through
const ADVANCE_MS = THINKING_CONSTELLATION_STEP_MS / 4;
const STEPS = 12 * 4;

function renderedShapes(phase: ChatGenerationPhase) {
  const shapes: Array<{ name: string; nodes: HTMLElement[]; links: HTMLElement[] }> = [];
  for (let step = 0; step < STEPS; step += 1) {
    vi.setSystemTime(step * ADVANCE_MS);
    const { container, unmount } = render(<ThinkingConstellation phase={phase} />);
    const loader = container.querySelector<HTMLElement>(".constellation-loader");
    shapes.push({
      name: loader?.dataset.constellationName ?? "",
      nodes: Array.from(container.querySelectorAll<HTMLElement>(".constellation-loader__node")),
      links: Array.from(container.querySelectorAll<HTMLElement>(".constellation-loader__link")),
    });
    unmount();
  }
  return shapes;
}

describe("ThinkingConstellation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each(PHASES)("always renders the fixed number of elements in the %s phase", (phase) => {
    for (const shape of renderedShapes(phase)) {
      expect(shape.nodes).toHaveLength(THINKING_CONSTELLATION_NODE_COUNT);
      expect(shape.links).toHaveLength(THINKING_CONSTELLATION_LINK_COUNT);
    }
  });

  it.each(PHASES)("keeps every star and line inside the stage in the %s phase", (phase) => {
    for (const shape of renderedShapes(phase)) {
      const visibleNodes = shape.nodes.filter((node) => node.style.opacity === "1");
      const visibleLinks = shape.links.filter((link) => link.style.opacity === "1");
      expect(visibleNodes.length, shape.name).toBeGreaterThanOrEqual(4);
      expect(visibleLinks.length, shape.name).toBeGreaterThanOrEqual(3);

      for (const element of [...shape.nodes, ...shape.links]) {
        const left = Number.parseFloat(element.style.left);
        const top = Number.parseFloat(element.style.top);
        expect(left, shape.name).toBeGreaterThanOrEqual(8);
        expect(left, shape.name).toBeLessThanOrEqual(92);
        expect(top, shape.name).toBeGreaterThanOrEqual(12);
        expect(top, shape.name).toBeLessThanOrEqual(88);
      }
      for (const link of shape.links) {
        expect(link.style.transform, shape.name).toMatch(/rotate\(-?[\d.]+deg\)/);
      }
      // 使わない線は長さ 0 で星に重ね、舞台の中央から湧いて見えないようにする
      // Unused lines collapse to zero length on a star instead of appearing from the stage center
      for (const link of shape.links.filter((candidate) => candidate.style.opacity === "0")) {
        expect(link.style.width, shape.name).toBe("0%");
      }
    }
  });

  it("shows different constellations per phase", () => {
    const names = PHASES.map((phase) => new Set(renderedShapes(phase).map((shape) => shape.name)));
    expect(names[0].size).toBeGreaterThan(1);
    expect(names[1].size).toBeGreaterThan(1);
    expect(names[2].size).toBe(12);
    for (const name of names[0]) {
      expect(names[1].has(name) || names[2].has(name)).toBe(false);
    }
    for (const name of names[1]) {
      expect(names[2].has(name)).toBe(false);
    }
  });
});
