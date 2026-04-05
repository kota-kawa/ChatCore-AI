import { useEffect, useState } from "react";
import {
  THINKING_CONSTELLATION_BASE_HEIGHT,
  THINKING_CONSTELLATION_BASE_WIDTH,
  THINKING_CONSTELLATION_LINK_COUNT,
  THINKING_CONSTELLATION_NODE_COUNT,
  THINKING_CONSTELLATION_STEP_MS,
  THINKING_CONSTELLATION_VARIANTS,
} from "../../lib/chat_page/constants";

function resolveConstellationIndex(timestamp: number) {
  if (THINKING_CONSTELLATION_VARIANTS.length === 0) return 0;
  return Math.floor(timestamp / THINKING_CONSTELLATION_STEP_MS) % THINKING_CONSTELLATION_VARIANTS.length;
}

export function ThinkingConstellation() {
  const [constellationIndex, setConstellationIndex] = useState(0);

  useEffect(() => {
    if (THINKING_CONSTELLATION_VARIANTS.length <= 1) return;

    let timerId: ReturnType<typeof setTimeout> | null = null;

    const syncConstellation = () => {
      const now = Date.now();
      setConstellationIndex(resolveConstellationIndex(now));

      const elapsedInStep = now % THINKING_CONSTELLATION_STEP_MS;
      const delay = Math.max(48, THINKING_CONSTELLATION_STEP_MS - elapsedInStep + 18);
      timerId = setTimeout(syncConstellation, delay);
    };

    syncConstellation();

    return () => {
      if (timerId !== null) {
        clearTimeout(timerId);
      }
    };
  }, []);

  const currentConstellation = THINKING_CONSTELLATION_VARIANTS[constellationIndex] ?? THINKING_CONSTELLATION_VARIANTS[0];
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
            ["--link-delay" as string]: `${index * -0.16}s`,
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
            ["--link-delay" as string]: `${index * -0.16}s`,
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
          ["--link-delay" as string]: `${index * -0.16}s`,
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
            ["--node-delay" as string]: `${index * -0.18}s`,
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
          ["--node-delay" as string]: `${index * -0.18}s`,
        }}
      ></span>
    );
  });

  return (
    <div
      className="constellation-loader thinking-message__constellation is-ready"
      data-constellation-name={currentConstellation.name}
      aria-hidden="true"
    >
      {links}
      {nodes}
    </div>
  );
}
