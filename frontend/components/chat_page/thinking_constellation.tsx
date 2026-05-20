import { useEffect, useState } from "react";
import {
  THINKING_CONSTELLATION_BASE_HEIGHT,
  THINKING_CONSTELLATION_BASE_WIDTH,
  THINKING_CONSTELLATION_LINK_COUNT,
  THINKING_CONSTELLATION_NODE_COUNT,
  THINKING_CONSTELLATION_STEP_MS,
  THINKING_CONSTELLATION_VARIANTS,
  type ThinkingConstellationNode,
} from "../../lib/chat_page/constants";
import type { ChatGenerationPhase } from "../../lib/chat_page/types";

type ConstellationPhaseTiming = {
  stepMs: number;
  linkDelayMs: number;
  nodeDelayMs: number;
  motionMs: number;
  motionTickMs: number;
};

const TAU = Math.PI * 2;

const CONSTELLATION_PHASE_TIMING: Record<ChatGenerationPhase, ConstellationPhaseTiming> = {
  preparing: {
    stepMs: THINKING_CONSTELLATION_STEP_MS,
    linkDelayMs: 160,
    nodeDelayMs: 180,
    motionMs: 1,
    motionTickMs: THINKING_CONSTELLATION_STEP_MS,
  },
  "web-search": {
    stepMs: Math.max(1200, Math.round(THINKING_CONSTELLATION_STEP_MS * 0.68)),
    linkDelayMs: 92,
    nodeDelayMs: 104,
    motionMs: 1760,
    motionTickMs: 120,
  },
  generating: {
    stepMs: Math.round(THINKING_CONSTELLATION_STEP_MS * 1.18),
    linkDelayMs: 210,
    nodeDelayMs: 132,
    motionMs: 2480,
    motionTickMs: 150,
  },
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function resolveConstellationIndex(timestamp: number, stepMs: number) {
  if (THINKING_CONSTELLATION_VARIANTS.length === 0) return 0;
  return Math.floor(timestamp / stepMs) % THINKING_CONSTELLATION_VARIANTS.length;
}

function resolveMotionProgress(timestamp: number, durationMs: number) {
  if (timestamp <= 0 || durationMs <= 0) return 0;
  return (timestamp % durationMs) / durationMs;
}

function resolveConstellationCenter(nodes: ThinkingConstellationNode[]) {
  if (nodes.length === 0) {
    return { x: 52, y: 50 };
  }

  const sum = nodes.reduce(
    (acc, node) => ({
      x: acc.x + node.x,
      y: acc.y + node.y,
    }),
    { x: 0, y: 0 },
  );

  return {
    x: sum.x / nodes.length,
    y: sum.y / nodes.length,
  };
}

function applyPhaseNodeMotion(
  nodes: ThinkingConstellationNode[],
  phase: ChatGenerationPhase,
  timestamp: number,
  timing: ConstellationPhaseTiming,
) {
  if (phase === "preparing") return nodes;

  const progress = resolveMotionProgress(timestamp, timing.motionMs);
  if (phase === "web-search") {
    const focusX = 18 + 68 * progress;
    const focusY = 50 + Math.sin(progress * TAU * 2) * 6;

    return nodes.map((node, index) => {
      const stagger = index / Math.max(1, nodes.length - 1);
      const localWave = Math.sin((progress - stagger) * TAU);
      const focusStrength = clamp(0.12 + Math.max(0, localWave) * 0.2, 0.1, 0.32);
      const driftX = Math.sin((progress + index * 0.13) * TAU) * 2.8;
      const driftY = Math.cos((progress + index * 0.11) * TAU) * 2.2;

      return {
        ...node,
        x: clamp(node.x + (focusX - node.x) * focusStrength + driftX, 10, 90),
        y: clamp(node.y + (focusY - node.y) * focusStrength + driftY, 15, 85),
      };
    });
  }

  const center = resolveConstellationCenter(nodes);
  const breath = (1 - Math.cos(progress * TAU)) / 2;
  const gatherStrength = 0.08 + breath * 0.18;

  return nodes.map((node, index) => {
    const orbit = progress * TAU + index * 0.78;
    const orbitStrength = 0.55 + breath * 0.45;
    const orbitX = Math.cos(orbit) * 3.1 * orbitStrength;
    const orbitY = Math.sin(orbit) * 2.35 * orbitStrength;

    return {
      ...node,
      x: clamp(center.x + (node.x - center.x) * (1 - gatherStrength) + orbitX, 10, 90),
      y: clamp(center.y + (node.y - center.y) * (1 - gatherStrength) + orbitY, 15, 85),
    };
  });
}

function resolveLinkMotion(
  phase: ChatGenerationPhase,
  index: number,
  fromNode: ThinkingConstellationNode,
  toNode: ThinkingConstellationNode,
  timestamp: number,
  timing: ConstellationPhaseTiming,
) {
  if (phase === "preparing") {
    return { scale: 1, opacity: 1 };
  }

  const progress = resolveMotionProgress(timestamp, timing.motionMs);
  if (phase === "web-search") {
    const midpointX = (fromNode.x + toNode.x) / 2;
    const scannerX = 10 + progress * 80;
    const focus = clamp(1 - Math.abs(midpointX - scannerX) / 22, 0, 1);
    return {
      scale: 0.48 + focus * 0.52,
      opacity: 0.42 + focus * 0.58,
    };
  }

  const pulse = (1 + Math.sin(progress * TAU + index * 0.72)) / 2;
  return {
    scale: 0.78 + pulse * 0.22,
    opacity: 0.68 + pulse * 0.32,
  };
}

export function ThinkingConstellation({ phase = "preparing" }: { phase?: ChatGenerationPhase }) {
  const [constellationIndex, setConstellationIndex] = useState(0);
  const [motionTimestamp, setMotionTimestamp] = useState(0);
  const phaseTiming = CONSTELLATION_PHASE_TIMING[phase] ?? CONSTELLATION_PHASE_TIMING.preparing;

  useEffect(() => {
    if (THINKING_CONSTELLATION_VARIANTS.length <= 1) return;

    let timerId: ReturnType<typeof setTimeout> | null = null;

    const syncConstellation = () => {
      const now = Date.now();
      setConstellationIndex(resolveConstellationIndex(now, phaseTiming.stepMs));

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
  }, [phaseTiming.stepMs]);

  useEffect(() => {
    if (phase === "preparing") return;

    let timerId: ReturnType<typeof setTimeout> | null = null;

    const syncMotion = () => {
      setMotionTimestamp(Date.now());
      timerId = setTimeout(syncMotion, phaseTiming.motionTickMs);
    };

    syncMotion();

    return () => {
      if (timerId !== null) {
        clearTimeout(timerId);
      }
    };
  }, [phase, phaseTiming.motionTickMs]);

  const currentConstellation = THINKING_CONSTELLATION_VARIANTS[constellationIndex] ?? THINKING_CONSTELLATION_VARIANTS[0];
  if (!currentConstellation) return null;

  const baseNodeSize = Math.max(4, THINKING_CONSTELLATION_BASE_WIDTH * 0.03);
  const displayNodes = applyPhaseNodeMotion(currentConstellation.nodes, phase, motionTimestamp, phaseTiming);

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
    const fromNode = displayNodes[fromIndex];
    const toNode = displayNodes[toIndex];

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
    const linkMotion = resolveLinkMotion(phase, index, fromNode, toNode, motionTimestamp, phaseTiming);
    const linkStartX =
      phase === "generating" ? fromNode.x + (toNode.x - fromNode.x) * ((1 - linkMotion.scale) / 2) : fromNode.x;
    const linkStartY =
      phase === "generating" ? fromNode.y + (toNode.y - fromNode.y) * ((1 - linkMotion.scale) / 2) : fromNode.y;

    return (
      <span
        key={`thinking-link-${index}`}
        className="constellation-loader__link"
        style={{
          left: `${linkStartX}%`,
          top: `${linkStartY}%`,
          width: `${length * linkMotion.scale}px`,
          opacity: linkMotion.opacity,
          transform: `translateY(-50%) rotate(${angle}deg)`,
          ["--link-delay" as string]: `${(index * -phaseTiming.linkDelayMs) / 1000}s`,
        }}
      ></span>
    );
  });

  const nodes = Array.from({ length: THINKING_CONSTELLATION_NODE_COUNT }).map((_, index) => {
    const node = displayNodes[index];
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
