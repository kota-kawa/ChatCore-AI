import type { ModelOption } from "./types";
import chatContract from "../../data/chat_contract.json";

function toPositiveInteger(value: unknown, fallback: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  const parsed = Math.trunc(value);
  return parsed > 0 ? parsed : fallback;
}

const chatHistoryContract = (chatContract as { chat_history?: { page_size_default?: number } }).chat_history;
const chatHistoryPageSizeDefault = chatHistoryContract?.page_size_default;

export const MAX_CHAT_MESSAGE_LENGTH = 30000;
export const MAX_SETUP_INFO_LENGTH = 30000;
export const MAX_RENDERED_CHAT_MESSAGES = 1000;
export const DEFAULT_MODEL = "openai/gpt-oss-120b";
export const CHAT_ROOMS_PAGE_SIZE = 20;
export const CHAT_HISTORY_PAGE_SIZE = toPositiveInteger(chatHistoryPageSizeDefault, 50);
export const STICKY_SCROLL_BOTTOM_THRESHOLD_PX = 72;
export const THINKING_CONSTELLATION_BASE_WIDTH = 208;
export const THINKING_CONSTELLATION_BASE_HEIGHT = 86;
export const THINKING_CONSTELLATION_NODE_COUNT = 8;
export const THINKING_CONSTELLATION_LINK_COUNT = 8;
export const THINKING_CONSTELLATION_STEP_MS = 3200;

export type ThinkingConstellationNode = {
  x: number;
  y: number;
  size?: number;
};

export type ThinkingConstellationVariant = {
  name: string;
  nodes: ThinkingConstellationNode[];
  links: Array<[number, number]>;
};

// すべてのバリアントを 8 ノード / 8 リンクに統一している。
// 個数を揃えることで星座同士のモーフィングが常に 1 対 1 の対応になり、
// 「中央から湧いて出る / 中央に吸い込まれる」不自然な動きが起きない。
// Every variant uses exactly 8 nodes / 8 links so that morphing between
// constellations is always a 1:1 mapping — no element ever pops in from or
// collapses into the center.
export const THINKING_CONSTELLATION_VARIANTS: ThinkingConstellationVariant[] = [
  {
    // 右へ流れてから先端で巻く、雄羊の角のひとつづきの弧
    // A single sweeping arc that curls at the tip, like a ram's horn
    name: "牡羊座",
    nodes: [
      { x: 14, y: 62, size: 0.84 },
      { x: 24, y: 44, size: 0.9 },
      { x: 38, y: 31, size: 0.96 },
      { x: 54, y: 26, size: 1.08 },
      { x: 68, y: 30, size: 0.9 },
      { x: 79, y: 40, size: 0.86 },
      { x: 85, y: 54, size: 0.92 },
      { x: 76, y: 64, size: 0.8 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7], [7, 5]],
  },
  {
    // ヒアデス星団のV字の顔と、右へ大きく開いた二本の角
    // The Hyades V-shaped face with two horns opening wide to the right
    name: "牡牛座",
    nodes: [
      { x: 20, y: 44, size: 0.84 },
      { x: 30, y: 58, size: 0.9 },
      { x: 40, y: 48, size: 1.06 },
      { x: 32, y: 34, size: 0.82 },
      { x: 54, y: 46, size: 0.9 },
      { x: 66, y: 58, size: 0.86 },
      { x: 84, y: 66, size: 0.94 },
      { x: 74, y: 26, size: 0.98 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 0], [2, 4], [4, 5], [5, 6], [4, 7]],
  },
  {
    // 手をつないだ双子。緩やかに膨らむ二本の柱と二本の横木の左右対称なはしご
    // Twins holding hands: a symmetric ladder of two gently bowed posts and two rungs
    name: "双子座",
    nodes: [
      { x: 30, y: 26, size: 0.94 },
      { x: 26, y: 47, size: 0.84 },
      { x: 30, y: 68, size: 0.94 },
      { x: 70, y: 26, size: 0.94 },
      { x: 74, y: 47, size: 0.84 },
      { x: 70, y: 68, size: 0.94 },
      { x: 50, y: 31, size: 0.9 },
      { x: 50, y: 63, size: 0.9 },
    ],
    links: [[0, 1], [1, 2], [3, 4], [4, 5], [0, 6], [6, 3], [2, 7], [7, 5]],
  },
  {
    // 中央の菱形の甲羅から左右へ鋏を伸ばす蟹。完全な左右対称
    // A crab: diamond shell with claws reaching out to both sides, fully symmetric
    name: "蟹座",
    nodes: [
      { x: 43, y: 45, size: 0.96 },
      { x: 57, y: 45, size: 0.96 },
      { x: 50, y: 60, size: 0.86 },
      { x: 50, y: 30, size: 0.9 },
      { x: 28, y: 31, size: 0.84 },
      { x: 15, y: 44, size: 0.9 },
      { x: 72, y: 31, size: 0.84 },
      { x: 85, y: 44, size: 0.9 },
    ],
    links: [[3, 0], [3, 1], [0, 2], [1, 2], [0, 4], [4, 5], [1, 6], [6, 7]],
  },
  {
    // レグルスから立ち上がる「ししの大鎌」のたてがみの環と、デネボラへ流れる尾
    // The Sickle: a mane loop rising from Regulus, with the tail flowing to Denebola
    name: "獅子座",
    nodes: [
      { x: 26, y: 63, size: 1.06 },
      { x: 20, y: 45, size: 0.86 },
      { x: 28, y: 31, size: 0.9 },
      { x: 42, y: 26, size: 0.94 },
      { x: 52, y: 35, size: 0.88 },
      { x: 47, y: 51, size: 0.82 },
      { x: 69, y: 57, size: 0.86 },
      { x: 87, y: 45, size: 0.96 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 0], [4, 6], [6, 7]],
  },
  {
    // なだらかなサインカーブの波と、スピカから下がる菱形の裾
    // A gentle sine wave with a diamond hem hanging below Spica
    name: "乙女座",
    nodes: [
      { x: 13, y: 35, size: 0.8 },
      { x: 26, y: 55, size: 0.9 },
      { x: 39, y: 35, size: 0.84 },
      { x: 52, y: 55, size: 1.04 },
      { x: 65, y: 35, size: 0.84 },
      { x: 78, y: 55, size: 0.9 },
      { x: 89, y: 38, size: 0.8 },
      { x: 40, y: 71, size: 0.86 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [1, 7], [7, 3]],
  },
  {
    // 頂点から左右へ均等に吊られた天秤。梁の両端に皿を下げる
    // Scales hung evenly from an apex, with a dish at each end of the beam
    name: "天秤座",
    nodes: [
      { x: 50, y: 24, size: 1.02 },
      { x: 28, y: 38, size: 0.9 },
      { x: 72, y: 38, size: 0.9 },
      { x: 50, y: 38, size: 0.8 },
      { x: 20, y: 60, size: 0.82 },
      { x: 34, y: 64, size: 0.82 },
      { x: 66, y: 64, size: 0.82 },
      { x: 80, y: 60, size: 0.82 },
    ],
    links: [[0, 1], [0, 2], [1, 3], [3, 2], [1, 4], [4, 5], [2, 7], [6, 7]],
  },
  {
    // 左端の鋏から尾の毒針まで、緩やかに反り上がるJ字のカーブ
    // From the pincers to the stinger: a smooth J-curve rising at the tail
    name: "蠍座",
    nodes: [
      { x: 16, y: 26, size: 0.84 },
      { x: 13, y: 48, size: 0.84 },
      { x: 26, y: 40, size: 0.92 },
      { x: 40, y: 50, size: 0.86 },
      { x: 54, y: 58, size: 0.9 },
      { x: 68, y: 56, size: 0.86 },
      { x: 80, y: 45, size: 0.9 },
      { x: 87, y: 28, size: 1.02 },
    ],
    links: [[0, 1], [0, 2], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7]],
  },
  {
    // 南斗六星の「ティーポット」。胴体・蓋・注ぎ口・取っ手
    // The Teapot asterism: body, lid, spout and handle
    name: "射手座",
    nodes: [
      { x: 32, y: 38, size: 0.94 },
      { x: 60, y: 38, size: 0.94 },
      { x: 26, y: 62, size: 0.9 },
      { x: 66, y: 62, size: 0.9 },
      { x: 46, y: 26, size: 1.02 },
      { x: 14, y: 30, size: 0.86 },
      { x: 84, y: 40, size: 0.8 },
      { x: 80, y: 58, size: 0.8 },
    ],
    links: [[0, 2], [1, 3], [2, 3], [0, 4], [4, 1], [0, 5], [1, 6], [6, 7]],
  },
  {
    // 両端が持ち上がった三角帽子のような、閉じた舟形のシルエット
    // A closed boat silhouette with both tips lifted, like a tricorn hat
    name: "山羊座",
    nodes: [
      { x: 14, y: 34, size: 0.92 },
      { x: 25, y: 52, size: 0.84 },
      { x: 39, y: 62, size: 0.88 },
      { x: 55, y: 64, size: 0.96 },
      { x: 70, y: 58, size: 0.84 },
      { x: 82, y: 46, size: 0.88 },
      { x: 88, y: 30, size: 0.94 },
      { x: 50, y: 34, size: 0.8 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7], [7, 0]],
  },
  {
    // 水瓶から流れ落ちる二段の波。上下の波を水流がつなぐ
    // Two tiers of waves pouring from the urn, joined by falling streams
    name: "水瓶座",
    nodes: [
      { x: 16, y: 36, size: 0.82 },
      { x: 32, y: 25, size: 0.9 },
      { x: 48, y: 36, size: 0.84 },
      { x: 64, y: 25, size: 0.9 },
      { x: 80, y: 36, size: 0.82 },
      { x: 28, y: 58, size: 0.84 },
      { x: 44, y: 68, size: 0.9 },
      { x: 60, y: 58, size: 0.84 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [5, 6], [6, 7], [1, 5], [3, 7]],
  },
  {
    // 菱形の魚と、結び目から伸びる二本の紐
    // A diamond-shaped fish with two cords stretching from the knot
    name: "魚座",
    nodes: [
      { x: 86, y: 62, size: 1 },
      { x: 66, y: 47, size: 0.84 },
      { x: 48, y: 33, size: 0.86 },
      { x: 33, y: 24, size: 0.82 },
      { x: 19, y: 29, size: 0.9 },
      { x: 28, y: 40, size: 0.82 },
      { x: 58, y: 68, size: 0.84 },
      { x: 34, y: 73, size: 0.9 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 2], [0, 6], [6, 7]],
  },
];

export const THINKING_CONSTELLATION_NODES = THINKING_CONSTELLATION_VARIANTS[0]?.nodes ?? [];
export const THINKING_CONSTELLATION_LINKS = THINKING_CONSTELLATION_VARIANTS[0]?.links ?? [];

export const MODEL_OPTIONS: ModelOption[] = [
  { value: "openai/gpt-oss-120b", label: "GROQ | GPT-OSS 120B（標準・高品質な応答）", shortLabel: "GPT-OSS 120B" },
  {
    value: "gpt-5-mini",
    label: "OPENAI | GPT-5 mini（高品質・推論が必要な作業向け）",
    shortLabel: "GPT-5 mini",
  },
  { value: "gemini-2.5-flash", label: "Gemini | 2.5 Flash（軽い作業向け）", shortLabel: "Gemini 2.5" },
];
