import { useEffect, useState } from "react";
import {
  THINKING_CONSTELLATION_BASE_HEIGHT,
  THINKING_CONSTELLATION_BASE_WIDTH,
  THINKING_CONSTELLATION_LINK_COUNT,
  THINKING_CONSTELLATION_NODE_COUNT,
  THINKING_CONSTELLATION_STEP_MS,
  THINKING_CONSTELLATION_VARIANTS,
  type ThinkingConstellationVariant,
} from "../../lib/chat_page/constants";
import type { ChatGenerationPhase } from "../../lib/chat_page/types";

type ConstellationPhaseTiming = {
  stepMs: number;
  linkDelayMs: number;
  nodeDelayMs: number;
};

const CONSTELLATION_PHASE_TIMING: Record<ChatGenerationPhase, ConstellationPhaseTiming> = {
  preparing: {
    stepMs: Math.round(THINKING_CONSTELLATION_STEP_MS * 1.12),
    linkDelayMs: 190,
    nodeDelayMs: 150,
  },
  "web-search": {
    stepMs: Math.max(1300, Math.round(THINKING_CONSTELLATION_STEP_MS * 0.72)),
    linkDelayMs: 110,
    nodeDelayMs: 120,
  },
  generating: {
    stepMs: THINKING_CONSTELLATION_STEP_MS,
    linkDelayMs: 160,
    nodeDelayMs: 180,
  },
};

const WEB_SEARCH_CONSTELLATION_VARIANTS: ThinkingConstellationVariant[] = [
  {
    name: "検索レンズ",
    nodes: [
      { x: 34, y: 32, size: 0.84 },
      { x: 48, y: 28, size: 0.92 },
      { x: 60, y: 40, size: 0.86 },
      { x: 55, y: 56, size: 0.98 },
      { x: 40, y: 62, size: 0.9 },
      { x: 28, y: 50, size: 0.82 },
      { x: 66, y: 66, size: 0.88 },
      { x: 80, y: 76, size: 0.8 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 0], [3, 6], [6, 7]],
  },
  {
    name: "検索オービット",
    nodes: [
      { x: 50, y: 50, size: 1.06 },
      { x: 82, y: 50, size: 0.82 },
      { x: 70, y: 28, size: 0.88 },
      { x: 43, y: 23, size: 0.82 },
      { x: 21, y: 38, size: 0.88 },
      { x: 21, y: 62, size: 0.82 },
      { x: 43, y: 77, size: 0.88 },
      { x: 70, y: 72, size: 0.82 },
    ],
    links: [[1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7], [7, 1], [0, 1]],
  },
  {
    name: "検索ハニカム",
    nodes: [
      { x: 84, y: 50, size: 0.84 },
      { x: 67, y: 26, size: 0.9 },
      { x: 33, y: 26, size: 0.9 },
      { x: 16, y: 50, size: 0.84 },
      { x: 33, y: 74, size: 0.9 },
      { x: 67, y: 74, size: 0.9 },
      { x: 42, y: 50, size: 1.0 },
      { x: 58, y: 50, size: 1.04 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 0], [6, 7], [7, 0]],
  },
];

const PREPARING_CONSTELLATION_VARIANTS: ThinkingConstellationVariant[] = [
  {
    name: "準備コア",
    nodes: [
      { x: 50, y: 50, size: 1.08 },
      { x: 50, y: 20, size: 0.82 },
      { x: 74, y: 34, size: 0.9 },
      { x: 74, y: 66, size: 0.82 },
      { x: 50, y: 80, size: 0.9 },
      { x: 26, y: 66, size: 0.82 },
      { x: 26, y: 34, size: 0.9 },
      { x: 88, y: 50, size: 0.76 },
    ],
    links: [[0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6], [2, 7], [3, 7]],
  },
  {
    name: "準備分岐",
    nodes: [
      { x: 18, y: 54, size: 0.88 },
      { x: 34, y: 42, size: 0.96 },
      { x: 50, y: 50, size: 1.08 },
      { x: 66, y: 34, size: 0.88 },
      { x: 82, y: 24, size: 0.78 },
      { x: 66, y: 66, size: 0.88 },
      { x: 82, y: 78, size: 0.78 },
      { x: 46, y: 74, size: 0.82 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [2, 5], [5, 6], [2, 7], [1, 7]],
  },
  {
    name: "準備ヘリックス",
    nodes: [
      { x: 24, y: 28, size: 0.82 },
      { x: 24, y: 72, size: 0.82 },
      { x: 40, y: 40, size: 0.9 },
      { x: 40, y: 60, size: 0.9 },
      { x: 58, y: 28, size: 0.82 },
      { x: 58, y: 72, size: 0.82 },
      { x: 76, y: 42, size: 0.9 },
      { x: 76, y: 58, size: 0.9 },
    ],
    links: [[0, 2], [2, 4], [4, 6], [1, 3], [3, 5], [5, 7], [2, 3], [4, 5]],
  },
];

function resolveConstellationVariants(phase: ChatGenerationPhase) {
  if (phase === "web-search") return WEB_SEARCH_CONSTELLATION_VARIANTS;
  if (phase === "generating") return THINKING_CONSTELLATION_VARIANTS;
  return PREPARING_CONSTELLATION_VARIANTS;
}

function resolveConstellationIndex(timestamp: number, stepMs: number, variantCount: number) {
  if (variantCount <= 0) return 0;
  return Math.floor(timestamp / stepMs) % variantCount;
}

export function ThinkingConstellation({ phase = "preparing" }: { phase?: ChatGenerationPhase }) {
  const [constellationIndex, setConstellationIndex] = useState(0);
  const phaseTiming = CONSTELLATION_PHASE_TIMING[phase] ?? CONSTELLATION_PHASE_TIMING.preparing;
  const constellationVariants = resolveConstellationVariants(phase);

  useEffect(() => {
    if (constellationVariants.length <= 1) return;

    let timerId: ReturnType<typeof setTimeout> | null = null;

    const syncConstellation = () => {
      const now = Date.now();
      setConstellationIndex(resolveConstellationIndex(now, phaseTiming.stepMs, constellationVariants.length));

      const elapsedInStep = now % phaseTiming.stepMs;
      const delay = Math.max(48, phaseTiming.stepMs - elapsedInStep + 18);
      timerId = setTimeout(syncConstellation, delay);
    };

    syncConstellation();

    return () => {
      if (timerId !== null) {
        clearTimeout(timerId);
      }
    };
  }, [phase, constellationVariants.length, phaseTiming.stepMs]);

  const currentConstellation = constellationVariants[constellationIndex] ?? constellationVariants[0];
  if (!currentConstellation) return null;

  const baseNodeSize = Math.max(4, THINKING_CONSTELLATION_BASE_WIDTH * 0.03);

  const links = Array.from({ length: THINKING_CONSTELLATION_LINK_COUNT }).map((_, index) => {
    const link = currentConstellation.links[index];

    if (!link) {
      return (
        <span
          key={`thinking-link-${index}`}
          className="constellation-loader__link"
          style={{
            left: "50%",
            top: "50%",
            width: "0px",
            opacity: 0,
            transform: "translateY(-50%) rotate(0deg)",
            ["--link-delay" as string]: `${(index * -phaseTiming.linkDelayMs) / 1000}s`,
          }}
        ></span>
      );
    }

    const [fromIndex, toIndex] = link;
    const fromNode = currentConstellation.nodes[fromIndex];
    const toNode = currentConstellation.nodes[toIndex];

    if (!fromNode || !toNode) {
      return (
        <span
          key={`thinking-link-${index}`}
          className="constellation-loader__link"
          style={{
            left: "50%",
            top: "50%",
            width: "0px",
            opacity: 0,
            transform: "translateY(-50%) rotate(0deg)",
            ["--link-delay" as string]: `${(index * -phaseTiming.linkDelayMs) / 1000}s`,
          }}
        ></span>
      );
    }

    const dx = ((toNode.x - fromNode.x) / 100) * THINKING_CONSTELLATION_BASE_WIDTH;
    const dy = ((toNode.y - fromNode.y) / 100) * THINKING_CONSTELLATION_BASE_HEIGHT;
    const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
    const length = Math.hypot(dx, dy);

    return (
      <span
        key={`thinking-link-${index}`}
        className="constellation-loader__link"
        style={{
          left: `${fromNode.x}%`,
          top: `${fromNode.y}%`,
          width: `${length}px`,
          opacity: 1,
          transform: `translateY(-50%) rotate(${angle}deg)`,
          ["--link-delay" as string]: `${(index * -phaseTiming.linkDelayMs) / 1000}s`,
        }}
      ></span>
    );
  });

  const nodes = Array.from({ length: THINKING_CONSTELLATION_NODE_COUNT }).map((_, index) => {
    const node = currentConstellation.nodes[index];
    if (!node) {
      return (
        <span
          key={`thinking-node-${index}`}
          className="constellation-loader__node"
          style={{
            left: "50%",
            top: "50%",
            width: "0px",
            height: "0px",
            opacity: 0,
            transform: "translate(-50%, -50%) scale(0.32)",
            ["--node-delay" as string]: `${(index * -phaseTiming.nodeDelayMs) / 1000}s`,
          }}
        ></span>
      );
    }

    return (
      <span
        key={`thinking-node-${index}`}
        className="constellation-loader__node"
        style={{
          left: `${node.x}%`,
          top: `${node.y}%`,
          width: `${baseNodeSize * (node.size ?? 1)}px`,
          height: `${baseNodeSize * (node.size ?? 1)}px`,
          opacity: 1,
          transform: "translate(-50%, -50%) scale(1)",
          ["--node-delay" as string]: `${(index * -phaseTiming.nodeDelayMs) / 1000}s`,
        }}
      ></span>
    );
  });

  return (
    <div
      className="constellation-loader thinking-message__constellation is-ready"
      data-constellation-name={currentConstellation.name}
      data-generation-phase={phase}
      aria-hidden="true"
    >
      {links}
      {nodes}
    </div>
  );
}
