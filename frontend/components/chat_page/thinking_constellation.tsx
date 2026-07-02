import { useEffect, useRef, useState } from "react";
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

// 各生成フェーズにおける星座アニメーションのタイミング設定の型
// Type for constellation animation timing settings per generation phase
type ConstellationPhaseTiming = {
  stepMs: number;
  linkDelayMs: number;
  nodeDelayMs: number;
};

// 生成フェーズごとの星座アニメーションタイミング設定
// Constellation animation timing settings per generation phase
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

// Web検索フェーズ専用の星座バリアント定義。
// いずれも 8 ノード / 8 リンクで、正多角形・等間隔リングなど整った幾何学配置にしている。
// Constellation variant definitions for the web search phase.
// Each uses 8 nodes / 8 links laid out on clean geometry (regular polygons, even rings).
const WEB_SEARCH_CONSTELLATION_VARIANTS: ThinkingConstellationVariant[] = [
  {
    // 正六角形のレンズと斜めに伸びる柄の虫眼鏡
    // A magnifier: regular-hexagon lens with a diagonal handle
    name: "検索レンズ",
    nodes: [
      { x: 58, y: 42, size: 0.88 },
      { x: 50, y: 25, size: 0.9 },
      { x: 34, y: 25, size: 0.9 },
      { x: 26, y: 42, size: 0.88 },
      { x: 34, y: 59, size: 0.9 },
      { x: 50, y: 59, size: 0.96 },
      { x: 66, y: 68, size: 0.86 },
      { x: 80, y: 76, size: 0.82 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 0], [5, 6], [6, 7]],
  },
  {
    // 中心星のまわりを等間隔の7つの星が周回する軌道
    // An orbit: seven evenly spaced stars circling a central one
    name: "検索オービット",
    nodes: [
      { x: 50, y: 50, size: 1.06 },
      { x: 80, y: 50, size: 0.84 },
      { x: 69, y: 30, size: 0.88 },
      { x: 43, y: 25, size: 0.84 },
      { x: 23, y: 39, size: 0.88 },
      { x: 23, y: 61, size: 0.84 },
      { x: 43, y: 75, size: 0.88 },
      { x: 69, y: 70, size: 0.84 },
    ],
    links: [[1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7], [7, 1], [0, 1]],
  },
  {
    // 正六角形の環と中央を貫く芯のハニカム
    // A honeycomb: regular hexagonal ring with a core bar through the center
    name: "検索ハニカム",
    nodes: [
      { x: 82, y: 50, size: 0.86 },
      { x: 66, y: 29, size: 0.9 },
      { x: 34, y: 29, size: 0.9 },
      { x: 18, y: 50, size: 0.86 },
      { x: 34, y: 71, size: 0.9 },
      { x: 66, y: 71, size: 0.9 },
      { x: 42, y: 50, size: 1.0 },
      { x: 58, y: 50, size: 1.04 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 0], [6, 7], [7, 0]],
  },
];

// 準備フェーズ専用の星座バリアント定義。こちらも 8 ノード / 8 リンクで統一。
// Constellation variant definitions for the preparing phase, also 8 nodes / 8 links each.
const PREPARING_CONSTELLATION_VARIANTS: ThinkingConstellationVariant[] = [
  {
    // 中心から等角度で花びらのように広がる6本のスポークと右のアクセント
    // A core: six spokes fanning out at even angles like petals, with a right accent
    name: "準備コア",
    nodes: [
      { x: 50, y: 50, size: 1.08 },
      { x: 50, y: 29, size: 0.84 },
      { x: 73, y: 40, size: 0.9 },
      { x: 73, y: 61, size: 0.84 },
      { x: 50, y: 71, size: 0.9 },
      { x: 27, y: 61, size: 0.84 },
      { x: 27, y: 40, size: 0.9 },
      { x: 88, y: 50, size: 0.8 },
    ],
    links: [[0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6], [2, 7], [3, 7]],
  },
  {
    // 幹からふた手に分かれ、先端でまた結ばれる木の葉形の分岐
    // A branching leaf: the trunk forks in two and rejoins at the tip
    name: "準備分岐",
    nodes: [
      { x: 14, y: 50, size: 0.86 },
      { x: 32, y: 50, size: 0.92 },
      { x: 48, y: 50, size: 1.08 },
      { x: 64, y: 33, size: 0.88 },
      { x: 80, y: 27, size: 0.82 },
      { x: 64, y: 67, size: 0.88 },
      { x: 80, y: 73, size: 0.82 },
      { x: 90, y: 50, size: 0.92 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [2, 5], [5, 6], [4, 7], [6, 7]],
  },
  {
    // 交差する二本の波と中央の横木が描く二重らせん
    // A double helix: two crossing waves tied by central rungs
    name: "準備ヘリックス",
    nodes: [
      { x: 18, y: 30, size: 0.86 },
      { x: 38, y: 62, size: 0.9 },
      { x: 58, y: 30, size: 0.9 },
      { x: 78, y: 62, size: 0.86 },
      { x: 18, y: 62, size: 0.86 },
      { x: 38, y: 30, size: 0.9 },
      { x: 58, y: 62, size: 0.9 },
      { x: 78, y: 30, size: 0.86 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [4, 5], [5, 6], [6, 7], [1, 5], [2, 6]],
  },
];

// 生成フェーズに応じた星座バリアントの配列を返す
// Return the array of constellation variants for the given generation phase
function resolveConstellationVariants(phase: ChatGenerationPhase) {
  if (phase === "web-search") return WEB_SEARCH_CONSTELLATION_VARIANTS;
  if (phase === "generating") return THINKING_CONSTELLATION_VARIANTS;
  return PREPARING_CONSTELLATION_VARIANTS;
}

// タイムスタンプとステップ時間から現在の星座インデックスを算出する
// Calculate the current constellation index from timestamp and step duration
function resolveConstellationIndex(timestamp: number, stepMs: number, variantCount: number) {
  if (variantCount <= 0) return 0;
  return Math.floor(timestamp / stepMs) % variantCount;
}

// モーフィング時に要素を端から順に波打たせるための時間差（1要素あたりのミリ秒）
// Per-element stagger (ms) that makes the morph ripple across the constellation
const MORPH_STAGGER_MS = 45;

// 前回の回転角に対して最短経路になるよう、角度を ±360° 単位で補正する。
// CSS の transform 遷移は数値をそのまま補間するため、-170°→170° のような
// 境界をまたぐ変化を放置すると線が大回りに一回転してしまう。
// Normalize an angle so the CSS transform transition takes the shortest path.
// CSS interpolates raw numbers, so an uncorrected -170°→170° change would
// spin the link the long way around.
function toNearestAngle(angle: number, previousAngle: number | undefined) {
  if (typeof previousAngle !== "number" || !Number.isFinite(previousAngle)) return angle;
  let adjusted = angle;
  while (adjusted - previousAngle > 180) adjusted -= 360;
  while (previousAngle - adjusted > 180) adjusted += 360;
  return adjusted;
}

// AI生成中のフェーズに応じてアニメーションする星座ローダーコンポーネント
// Constellation loader component that animates based on the AI generation phase
export function ThinkingConstellation({ phase = "preparing" }: { phase?: ChatGenerationPhase }) {
  const [constellationIndex, setConstellationIndex] = useState(0);
  const phaseTiming = CONSTELLATION_PHASE_TIMING[phase] ?? CONSTELLATION_PHASE_TIMING.preparing;
  const constellationVariants = resolveConstellationVariants(phase);
  // リンクごとの前回の回転角。星座が切り替わっても線が最短経路で回るように保持する
  // Previous rotation angle per link, kept so lines rotate the shortest way between variants
  const previousLinkAnglesRef = useRef<number[]>([]);

  // 星座バリアントを一定間隔でウォールクロックに同期して切り替えるタイマー
  // Timer that switches constellation variants at intervals synchronized with the wall clock
  useEffect(() => {
    if (constellationVariants.length <= 1) return;

    let timerId: ReturnType<typeof setTimeout> | null = null;

    // ウォールクロックと同期して次の切り替えタイミングを計算する
    // Calculate the next switch timing synchronized with the wall clock
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
    const fromNode = link ? currentConstellation.nodes[link[0]] : undefined;
    const toNode = link ? currentConstellation.nodes[link[1]] : undefined;

    if (!link || !fromNode || !toNode) {
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
            ["--morph-delay" as string]: `${(index * MORPH_STAGGER_MS) / 1000}s`,
          }}
        ></span>
      );
    }

    const dx = ((toNode.x - fromNode.x) / 100) * THINKING_CONSTELLATION_BASE_WIDTH;
    const dy = ((toNode.y - fromNode.y) / 100) * THINKING_CONSTELLATION_BASE_HEIGHT;
    const rawAngle = (Math.atan2(dy, dx) * 180) / Math.PI;
    const angle = toNearestAngle(rawAngle, previousLinkAnglesRef.current[index]);
    previousLinkAnglesRef.current[index] = angle;
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
          ["--morph-delay" as string]: `${(index * MORPH_STAGGER_MS) / 1000}s`,
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
            ["--morph-delay" as string]: `${(index * MORPH_STAGGER_MS) / 1000}s`,
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
          ["--morph-delay" as string]: `${(index * MORPH_STAGGER_MS) / 1000}s`,
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
