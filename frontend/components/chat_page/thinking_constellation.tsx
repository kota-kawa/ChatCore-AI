import {
  THINKING_CONSTELLATION_BASE_HEIGHT,
  THINKING_CONSTELLATION_BASE_WIDTH,
  THINKING_CONSTELLATION_LINKS,
  THINKING_CONSTELLATION_NODES,
} from "../../lib/chat_page/constants";

export function ThinkingConstellation() {
  const baseNodeSize = Math.max(4, THINKING_CONSTELLATION_BASE_WIDTH * 0.03);

  const links = THINKING_CONSTELLATION_LINKS.map(([fromIndex, toIndex], index) => {
    const fromNode = THINKING_CONSTELLATION_NODES[fromIndex];
    const toNode = THINKING_CONSTELLATION_NODES[toIndex];
    if (!fromNode || !toNode) {
      return null;
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

  const nodes = Array.from({ length: 8 }).map((_, index) => {
    const node = THINKING_CONSTELLATION_NODES[index];
    if (!node) {
      return <span key={`thinking-node-${index}`} className="constellation-loader__node"></span>;
    }

    return (
      <span
        key={`thinking-node-${index}`}
        className="constellation-loader__node"
        style={{
          left: `${node.x}%`,
          top: `${node.y}%`,
          width: `${baseNodeSize * node.size}px`,
          height: `${baseNodeSize * node.size}px`,
          opacity: 1,
          transform: "translate(-50%, -50%) scale(1)",
          ["--node-delay" as string]: `${index * -0.18}s`,
        }}
      ></span>
    );
  });

  return (
    <div className="constellation-loader thinking-message__constellation is-ready" aria-hidden="true">
      {links}
      {nodes}
    </div>
  );
}
