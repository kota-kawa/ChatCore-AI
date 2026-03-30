import { getSharedDomRefs } from "../core/dom";
import { isChatViewportNearBottom, scrollMessageToBottom } from "./message_utils";

type ZodiacNode = {
  x: number;
  y: number;
  size?: number;
};

type ZodiacConstellation = {
  name: string;
  nodes: ZodiacNode[];
  links: Array<[number, number]>;
};

const ZODIAC_NODE_COUNT = 8;
const ZODIAC_LINK_COUNT = 8;
const ZODIAC_STEP_MS = 2400;
const ZODIAC_SYNC_MS = 180;
const ZODIAC_CONSTELLATIONS: ZodiacConstellation[] = [
  {
    name: "牡羊座",
    nodes: [
      { x: 22, y: 58, size: 0.92 },
      { x: 37, y: 36, size: 1 },
      { x: 51, y: 49, size: 0.86 },
      { x: 67, y: 34, size: 1.08 },
      { x: 80, y: 46, size: 0.78 }
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4]]
  },
  {
    name: "牡牛座",
    nodes: [
      { x: 20, y: 48, size: 0.82 },
      { x: 31, y: 28, size: 0.94 },
      { x: 45, y: 50, size: 1.08 },
      { x: 59, y: 28, size: 0.94 },
      { x: 72, y: 48, size: 0.82 },
      { x: 52, y: 68, size: 0.9 }
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [2, 5]]
  },
  {
    name: "双子座",
    nodes: [
      { x: 24, y: 24, size: 0.82 },
      { x: 24, y: 72, size: 0.82 },
      { x: 42, y: 22, size: 0.94 },
      { x: 42, y: 72, size: 0.94 },
      { x: 60, y: 26, size: 0.82 },
      { x: 60, y: 68, size: 0.82 },
      { x: 78, y: 24, size: 0.94 },
      { x: 78, y: 68, size: 0.94 }
    ],
    links: [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [2, 4], [4, 6], [1, 3]]
  },
  {
    name: "蟹座",
    nodes: [
      { x: 26, y: 50, size: 0.88 },
      { x: 36, y: 34, size: 0.82 },
      { x: 50, y: 36, size: 1 },
      { x: 60, y: 50, size: 0.88 },
      { x: 48, y: 66, size: 0.9 },
      { x: 30, y: 64, size: 0.82 }
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]]
  },
  {
    name: "獅子座",
    nodes: [
      { x: 22, y: 56, size: 0.86 },
      { x: 33, y: 39, size: 0.92 },
      { x: 46, y: 30, size: 1.06 },
      { x: 60, y: 38, size: 0.92 },
      { x: 56, y: 56, size: 0.84 },
      { x: 70, y: 68, size: 0.92 },
      { x: 82, y: 56, size: 0.82 }
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]]
  },
  {
    name: "乙女座",
    nodes: [
      { x: 20, y: 28, size: 0.82 },
      { x: 30, y: 66, size: 0.9 },
      { x: 42, y: 34, size: 0.84 },
      { x: 54, y: 64, size: 0.96 },
      { x: 66, y: 38, size: 0.84 },
      { x: 76, y: 60, size: 0.9 },
      { x: 86, y: 74, size: 0.8 }
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]]
  },
  {
    name: "天秤座",
    nodes: [
      { x: 20, y: 62, size: 0.78 },
      { x: 38, y: 62, size: 0.88 },
      { x: 56, y: 62, size: 1.02 },
      { x: 74, y: 62, size: 0.78 },
      { x: 38, y: 42, size: 0.82 },
      { x: 56, y: 34, size: 0.94 },
      { x: 74, y: 42, size: 0.82 }
    ],
    links: [[0, 1], [1, 2], [2, 3], [1, 4], [4, 5], [5, 6], [6, 2]]
  },
  {
    name: "蠍座",
    nodes: [
      { x: 18, y: 28, size: 0.8 },
      { x: 30, y: 42, size: 0.86 },
      { x: 42, y: 34, size: 0.82 },
      { x: 54, y: 48, size: 0.92 },
      { x: 66, y: 40, size: 0.82 },
      { x: 78, y: 56, size: 0.9 },
      { x: 88, y: 68, size: 1 }
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]]
  },
  {
    name: "射手座",
    nodes: [
      { x: 22, y: 60, size: 0.84 },
      { x: 40, y: 42, size: 1 },
      { x: 58, y: 24, size: 0.82 },
      { x: 58, y: 60, size: 0.88 },
      { x: 76, y: 42, size: 0.92 },
      { x: 88, y: 26, size: 0.82 },
      { x: 78, y: 74, size: 0.78 }
    ],
    links: [[0, 1], [1, 2], [1, 3], [3, 4], [4, 5], [4, 6]]
  },
  {
    name: "山羊座",
    nodes: [
      { x: 20, y: 34, size: 0.84 },
      { x: 34, y: 64, size: 0.94 },
      { x: 46, y: 36, size: 0.82 },
      { x: 60, y: 60, size: 1.02 },
      { x: 74, y: 38, size: 0.84 },
      { x: 82, y: 54, size: 0.88 },
      { x: 90, y: 70, size: 0.78 }
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]]
  },
  {
    name: "水瓶座",
    nodes: [
      { x: 18, y: 40, size: 0.78 },
      { x: 30, y: 28, size: 0.88 },
      { x: 42, y: 42, size: 0.82 },
      { x: 54, y: 30, size: 0.92 },
      { x: 66, y: 44, size: 0.82 },
      { x: 78, y: 32, size: 0.88 },
      { x: 90, y: 46, size: 0.78 }
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]]
  },
  {
    name: "魚座",
    nodes: [
      { x: 16, y: 30, size: 0.78 },
      { x: 30, y: 44, size: 0.9 },
      { x: 16, y: 58, size: 0.78 },
      { x: 44, y: 44, size: 1 },
      { x: 58, y: 44, size: 0.88 },
      { x: 84, y: 30, size: 0.78 },
      { x: 70, y: 44, size: 0.9 },
      { x: 84, y: 58, size: 0.78 }
    ],
    links: [[0, 1], [1, 2], [1, 3], [3, 4], [4, 6], [6, 5], [6, 7]]
  }
];

const activeZodiacLoaders = new Set<HTMLElement>();
let zodiacLoopId: number | null = null;
let zodiacResizeBound = false;
let zodiacDomObserver: MutationObserver | null = null;

function getCurrentZodiacIndex() {
  return Math.floor(Date.now() / ZODIAC_STEP_MS) % ZODIAC_CONSTELLATIONS.length;
}

function getLoaderMetrics(loader: HTMLElement) {
  const rect = loader.getBoundingClientRect();
  if (rect.width > 0 && rect.height > 0) {
    return { width: rect.width, height: rect.height };
  }

  return { width: 206, height: 86 };
}

function applyZodiacConstellation(loader: HTMLElement, zodiacIndex: number) {
  const constellation = ZODIAC_CONSTELLATIONS[zodiacIndex];
  const nodes = Array.from(loader.querySelectorAll<HTMLElement>(".constellation-loader__node"));
  const links = Array.from(loader.querySelectorAll<HTMLElement>(".constellation-loader__link"));
  const { width, height } = getLoaderMetrics(loader);
  const baseNodeSize = Math.max(4, width * 0.03);

  nodes.forEach((node, index) => {
    const config = constellation.nodes[index];

    if (!config) {
      node.style.left = "50%";
      node.style.top = "50%";
      node.style.width = "0px";
      node.style.height = "0px";
      node.style.opacity = "0";
      node.style.transform = "translate(-50%, -50%) scale(0.32)";
      return;
    }

    const nodeSize = baseNodeSize * (config.size || 1);
    node.style.left = `${config.x}%`;
    node.style.top = `${config.y}%`;
    node.style.width = `${nodeSize}px`;
    node.style.height = `${nodeSize}px`;
    node.style.opacity = "1";
    node.style.transform = "translate(-50%, -50%) scale(1)";
  });

  links.forEach((link, index) => {
    const config = constellation.links[index];

    if (!config) {
      link.style.left = "50%";
      link.style.top = "50%";
      link.style.width = "0px";
      link.style.opacity = "0";
      link.style.transform = "translateY(-50%) rotate(0deg)";
      return;
    }

    const start = constellation.nodes[config[0]];
    const end = constellation.nodes[config[1]];

    if (!start || !end) {
      link.style.width = "0px";
      link.style.opacity = "0";
      return;
    }

    const dx = ((end.x - start.x) / 100) * width;
    const dy = ((end.y - start.y) / 100) * height;
    const angle = Math.atan2(dy, dx) * (180 / Math.PI);
    const length = Math.hypot(dx, dy);

    link.style.left = `${start.x}%`;
    link.style.top = `${start.y}%`;
    link.style.width = `${length}px`;
    link.style.opacity = "1";
    link.style.transform = `translateY(-50%) rotate(${angle}deg)`;
  });

  loader.dataset.zodiacIndex = String(zodiacIndex);
  loader.dataset.zodiacName = constellation.name;
  loader.dataset.zodiacSizeKey = `${Math.round(width)}x${Math.round(height)}`;
}

function cleanupZodiacRuntime() {
  if (zodiacLoopId !== null) {
    window.clearInterval(zodiacLoopId);
    zodiacLoopId = null;
  }

  if (zodiacResizeBound) {
    window.removeEventListener("resize", handleZodiacResize);
    zodiacResizeBound = false;
  }

  if (zodiacDomObserver) {
    zodiacDomObserver.disconnect();
    zodiacDomObserver = null;
  }
}

function ensureZodiacDomObserver() {
  if (zodiacDomObserver || !document.body) return;

  zodiacDomObserver = new MutationObserver(() => {
    syncZodiacLoaders(false);
  });
  zodiacDomObserver.observe(document.body, {
    childList: true,
    subtree: true
  });
}

function syncZodiacLoaders(forceCurrent = false) {
  const zodiacIndex = getCurrentZodiacIndex();

  activeZodiacLoaders.forEach((loader) => {
    if (!loader.isConnected) {
      activeZodiacLoaders.delete(loader);
      return;
    }

    const currentIndex = Number(loader.dataset.zodiacIndex ?? "-1");
    const sizeKey = (() => {
      const { width, height } = getLoaderMetrics(loader);
      return `${Math.round(width)}x${Math.round(height)}`;
    })();

    if (forceCurrent || currentIndex !== zodiacIndex || loader.dataset.zodiacSizeKey !== sizeKey) {
      applyZodiacConstellation(loader, zodiacIndex);
    }
  });

  if (activeZodiacLoaders.size === 0) {
    cleanupZodiacRuntime();
  }
}

function handleZodiacResize() {
  syncZodiacLoaders(true);
}

function ensureZodiacLoop() {
  if (zodiacLoopId === null) {
    zodiacLoopId = window.setInterval(() => {
      syncZodiacLoaders(false);
    }, ZODIAC_SYNC_MS);
  }

  if (!zodiacResizeBound) {
    window.addEventListener("resize", handleZodiacResize);
    zodiacResizeBound = true;
  }

  ensureZodiacDomObserver();
}

function setupZodiacLoader(loader: HTMLElement) {
  if (loader.dataset.zodiacReady === "true") return;

  loader.dataset.zodiacReady = "true";
  activeZodiacLoaders.add(loader);

  Array.from(loader.querySelectorAll<HTMLElement>(".constellation-loader__node")).forEach((node, index) => {
    node.style.setProperty("--node-delay", `${index * -0.18}s`);
  });

  Array.from(loader.querySelectorAll<HTMLElement>(".constellation-loader__link")).forEach((link, index) => {
    link.style.setProperty("--link-delay", `${index * -0.16}s`);
  });

  applyZodiacConstellation(loader, getCurrentZodiacIndex());
  ensureZodiacLoop();

  window.requestAnimationFrame(() => {
    loader.classList.add("is-ready");
    syncZodiacLoaders(true);
  });
}

function appendConstellationLoader(parent: HTMLElement, modifierClass: string) {
  const loader = document.createElement("div");
  loader.className = `constellation-loader ${modifierClass}`;
  loader.setAttribute("aria-hidden", "true");

  for (let index = 1; index <= ZODIAC_LINK_COUNT; index += 1) {
    const link = document.createElement("span");
    link.className = "constellation-loader__link";
    loader.appendChild(link);
  }

  for (let index = 1; index <= ZODIAC_NODE_COUNT; index += 1) {
    const node = document.createElement("span");
    node.className = "constellation-loader__node";
    loader.appendChild(node);
  }

  parent.appendChild(loader);
  return loader;
}

function shouldAutoScrollForGeneration() {
  return isChatViewportNearBottom();
}

function createThinkingPlaceholder() {
  const { chatMessages } = getSharedDomRefs();
  if (!chatMessages) return null;
  const shouldScrollToBottom = shouldAutoScrollForGeneration();

  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper bot-message-wrapper thinking-message-wrapper";

  const thinking = document.createElement("div");
  thinking.className = "thinking-message";
  thinking.setAttribute("role", "status");
  thinking.setAttribute("aria-live", "polite");
  thinking.setAttribute("aria-label", "AIが応答を準備しています");

  const loader = appendConstellationLoader(thinking, "thinking-message__constellation");
  wrapper.appendChild(thinking);
  chatMessages.appendChild(wrapper);
  setupZodiacLoader(loader);

  if (shouldScrollToBottom) {
    scrollMessageToBottom();
  }

  return wrapper;
}

function initConstellationLoaders() {
  document.querySelectorAll<HTMLElement>(".constellation-loader").forEach((loader) => {
    setupZodiacLoader(loader);
  });
}

initConstellationLoaders();

export { createThinkingPlaceholder };
