// AI の応答待ち中に出す「星座」アニメーション。生成フェーズ（準備・Web検索・生成）ごとに星座の形と切り替え間隔を変える。chat_message_list.tsx から使われる。
// Constellation animation shown while waiting for the AI; shape and cadence change per generation phase (preparing, web search, generating); used by chat_message_list.tsx.
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

// Web検索フェーズの星座：探しものにちなんだ虫眼鏡と、狩人・渡り鳥・天馬の星座。
// Constellations for the web search phase: a magnifier plus the hunter, the migrating swan, and the winged horse.
const WEB_SEARCH_CONSTELLATION_VARIANTS: ThinkingConstellationVariant[] = [
  {
    // 正六角形のレンズと斜めに伸びる柄の虫眼鏡
    // A magnifier: regular-hexagon lens with a diagonal handle
    name: "検索レンズ",
    nodes: [
      { x: 37.5, y: 44.9, size: 0.94 },
      { x: 39.7, y: 25.1, size: 0.94 },
      { x: 43.5, y: 59.4, size: 0.94 },
      { x: 47.9, y: 19.8, size: 0.94 },
      { x: 51.7, y: 54.1, size: 1.12 },
      { x: 53.9, y: 34.3, size: 0.94 },
      { x: 57.1, y: 67.2, size: 0.8 },
      { x: 62.5, y: 80.2, size: 0.94 },
    ],
    links: [[0, 1], [0, 2], [1, 3], [2, 4], [3, 5], [4, 5], [4, 6], [6, 7]],
  },
  {
    // 三つ星の帯を挟んで肩と足が向かい合う、横たわる狩人
    // The hunter lying on his side: shoulders and feet facing across the three-star belt
    name: "オリオン座",
    nodes: [
      { x: 28.2, y: 28, size: 0.8 },
      { x: 30.1, y: 59.1, size: 1.12 },
      { x: 37.8, y: 20.9, size: 0.94 },
      { x: 50.1, y: 33.3, size: 0.94 },
      { x: 52.5, y: 48.4, size: 0.94 },
      { x: 54.9, y: 63.5, size: 0.94 },
      { x: 69.1, y: 79.1, size: 0.94 },
      { x: 71.8, y: 31.7, size: 1.12 },
    ],
    links: [[0, 1], [0, 2], [1, 5], [2, 3], [3, 4], [4, 5], [3, 7], [5, 6]],
  },
  {
    // 翼を広げて天の川を渡る北十字
    // The Northern Cross, wings spread, flying along the Milky Way
    name: "白鳥座",
    nodes: [
      { x: 32.3, y: 36.9, size: 0.8 },
      { x: 39.3, y: 40, size: 0.94 },
      { x: 45.7, y: 79.1, size: 0.94 },
      { x: 47.5, y: 56.4, size: 0.8 },
      { x: 47.8, y: 37.2, size: 0.94 },
      { x: 48.9, y: 20.9, size: 1.12 },
      { x: 57.1, y: 42.2, size: 0.94 },
      { x: 67.7, y: 37.2, size: 0.8 },
    ],
    links: [[0, 1], [1, 4], [2, 3], [3, 4], [4, 5], [4, 6], [6, 7]],
  },
  {
    // 秋の大四辺形から首と前脚を伸ばして駆ける天馬
    // The winged horse galloping, neck and forelegs reaching out from the Great Square
    name: "ペガスス座",
    nodes: [
      { x: 29.7, y: 59.7, size: 0.94 },
      { x: 31, y: 29.8, size: 1.12 },
      { x: 48.4, y: 59.7, size: 0.94 },
      { x: 48.7, y: 31.9, size: 1.12 },
      { x: 54.2, y: 27.4, size: 0.94 },
      { x: 54.7, y: 69.2, size: 0.8 },
      { x: 63.2, y: 79.1, size: 0.8 },
      { x: 63.2, y: 20.9, size: 0.8 },
      { x: 70.3, y: 71.1, size: 1.12 },
    ],
    links: [[0, 1], [0, 2], [1, 3], [2, 3], [3, 4], [2, 5], [4, 7], [5, 6], [6, 8]],
  },
];

// 準備フェーズの星座：方角を確かめる目印になる北天の星の並び。
// Constellations for the preparing phase: northern star patterns used to find one's bearings.
const PREPARING_CONSTELLATION_VARIANTS: ThinkingConstellationVariant[] = [
  {
    // 北を指す道しるべ、ひしゃくの桝と柄
    // The signpost to north: the bowl and handle of the Dipper
    name: "北斗七星",
    nodes: [
      { x: 12.5, y: 56.1, size: 1.12 },
      { x: 27.3, y: 28.7, size: 0.94 },
      { x: 39.7, y: 32.9, size: 1.12 },
      { x: 55.3, y: 40.3, size: 0.8 },
      { x: 59.9, y: 69.5, size: 0.94 },
      { x: 82.4, y: 71.3, size: 0.94 },
      { x: 87.5, y: 36.2, size: 1.12 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [3, 6], [5, 6]],
  },
  {
    // 北の空に浮かぶ五つ星のW
    // The five-star W of the northern sky
    name: "カシオペヤ座",
    nodes: [
      { x: 14.8, y: 20.9, size: 0.8 },
      { x: 36.8, y: 51.9, size: 0.94 },
      { x: 54, y: 35.2, size: 1.12 },
      { x: 69.1, y: 79.1, size: 1.12 },
      { x: 85.2, y: 35.9, size: 0.94 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4]],
  },
  {
    // 七つの星が半円に並ぶ冠
    // A crown of seven stars set in a half circle
    name: "かんむり座",
    nodes: [
      { x: 26.2, y: 29.1, size: 0.8 },
      { x: 28.7, y: 66.2, size: 0.94 },
      { x: 39.2, y: 78.8, size: 0.8 },
      { x: 49.7, y: 79.1, size: 0.94 },
      { x: 61.2, y: 77.2, size: 1.12 },
      { x: 68.1, y: 20.9, size: 0.8 },
      { x: 73.8, y: 50.8, size: 0.94 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 6], [5, 6]],
  },
  {
    // ベガの三角と、弦を張る平行四辺形の竪琴
    // A lyre: Vega's triangle above a parallelogram of strings
    name: "こと座",
    nodes: [
      { x: 21.2, y: 55.9, size: 0.94 },
      { x: 33.6, y: 76.1, size: 0.94 },
      { x: 51.4, y: 23.9, size: 0.8 },
      { x: 64.3, y: 45.9, size: 0.94 },
      { x: 77.5, y: 26.4, size: 0.8 },
      { x: 78.8, y: 57, size: 1.12 },
    ],
    links: [[0, 1], [0, 2], [1, 3], [2, 3], [3, 4], [3, 5], [4, 5]],
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

  // リンクとノードは常に定数で決めた個数だけ描画し、現在の星座で使わない分は、使っている星や線に重ねて不可視にする。要素の増減がなく、余った分は星から分かれ出て星へ戻るので、星座が切り替わるとき CSS の遷移で形が変わる
  // Links and nodes are always rendered up to a fixed count; the ones the current constellation does not use are hidden on top of a star or line that is in use. Elements are never added or removed, and spare ones split off from and return to a star, so CSS transitions morph one shape into the next
  const visibleLinkCount = currentConstellation.links.length;
  const visibleNodeCount = currentConstellation.nodes.length;

  const links = Array.from({ length: THINKING_CONSTELLATION_LINK_COUNT }).map((_, index) => {
    const isVisible = index < visibleLinkCount;
    const [fromIndex, toIndex] = currentConstellation.links[index % visibleLinkCount];
    const fromNode = currentConstellation.nodes[fromIndex];
    const toNode = currentConstellation.nodes[toIndex];

    const dx = ((toNode.x - fromNode.x) / 100) * THINKING_CONSTELLATION_BASE_WIDTH;
    const dy = ((toNode.y - fromNode.y) / 100) * THINKING_CONSTELLATION_BASE_HEIGHT;
    const rawAngle = (Math.atan2(dy, dx) * 180) / Math.PI;
    const angle = toNearestAngle(rawAngle, previousLinkAnglesRef.current[index]);
    previousLinkAnglesRef.current[index] = angle;
    // 長さは舞台の幅に対する割合で持ち、スマホ幅で舞台が縮んでも星どうしをちょうど結ぶ
    // Length is a share of the stage width, so links still meet their stars when the stage shrinks on phones
    const lengthPercent = isVisible ? (Math.hypot(dx, dy) / THINKING_CONSTELLATION_BASE_WIDTH) * 100 : 0;

    return (
      <span
        key={`thinking-link-${index}`}
        className="constellation-loader__link"
        style={{
          left: `${fromNode.x}%`,
          top: `${fromNode.y}%`,
          width: `${lengthPercent}%`,
          opacity: isVisible ? 1 : 0,
          transform: `translateY(-50%) rotate(${angle}deg)`,
          ["--link-delay" as string]: `${(index * -phaseTiming.linkDelayMs) / 1000}s`,
          ["--morph-delay" as string]: `${(index * MORPH_STAGGER_MS) / 1000}s`,
        }}
      ></span>
    );
  });

  const nodes = Array.from({ length: THINKING_CONSTELLATION_NODE_COUNT }).map((_, index) => {
    const isVisible = index < visibleNodeCount;
    const node = currentConstellation.nodes[index % visibleNodeCount];
    const nodeSize = isVisible ? baseNodeSize * (node.size ?? 1) : 0;

    return (
      <span
        key={`thinking-node-${index}`}
        className="constellation-loader__node"
        style={{
          left: `${node.x}%`,
          top: `${node.y}%`,
          width: `${nodeSize}px`,
          height: `${nodeSize}px`,
          opacity: isVisible ? 1 : 0,
          transform: `translate(-50%, -50%) scale(${isVisible ? 1 : 0.32})`,
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
