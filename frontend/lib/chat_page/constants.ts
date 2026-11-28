// チャット画面で共有する定数（文字数上限、既定モデル、ページサイズ、スクロール閾値、思考中アニメーションの星座、モデル選択肢）。
// Constants shared by the chat page: length limits, the default model, page sizes, scroll thresholds, the thinking-animation constellations, and the model options.
import type { ModelOption } from "./types";
import chatContract from "../../data/chat_contract.json";

function toPositiveInteger(value: unknown, fallback: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  const parsed = Math.trunc(value);
  return parsed > 0 ? parsed : fallback;
}

// 履歴の既定ページサイズは API 契約（data/chat_contract.json）から読み、値が不正なら 50 にする。
// The default history page size is read from the API contract (data/chat_contract.json), falling back to 50 when the value is invalid.
const chatHistoryContract = (chatContract as { chat_history?: { page_size_default?: number } }).chat_history;
const chatHistoryPageSizeDefault = chatHistoryContract?.page_size_default;

export const MAX_CHAT_MESSAGE_LENGTH = 30000;
export const MAX_SETUP_INFO_LENGTH = 30000;
export const MAX_RENDERED_CHAT_MESSAGES = 1000;
export const DEFAULT_MODEL = "gpt-6-luna";
export const CHAT_ROOMS_PAGE_SIZE = 20;
export const CHAT_HISTORY_PAGE_SIZE = toPositiveInteger(chatHistoryPageSizeDefault, 50);
// 末尾からこの距離（px）以内なら「最下部にいる」とみなし、新しい出力に合わせて自動スクロールを続ける。
// Within this distance (px) of the bottom the view counts as "at the bottom" and keeps auto-scrolling with new output.
export const STICKY_SCROLL_BOTTOM_THRESHOLD_PX = 72;
export const THINKING_CONSTELLATION_BASE_WIDTH = 208;
export const THINKING_CONSTELLATION_BASE_HEIGHT = 86;
export const THINKING_CONSTELLATION_NODE_COUNT = 9;
export const THINKING_CONSTELLATION_LINK_COUNT = 10;
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

// 生成フェーズの星座：黄道十二星座。実際の星の並びを舞台の縦横比に合わせて置いている。
// 星と線の数は星座ごとに違ってよく、上の NODE_COUNT / LINK_COUNT が上限になる。
// 星は左から右の順に並べ、切り替え時に各星が近くの位置へ動くようにしている。
// Constellations for the generating phase: the twelve zodiac signs, laid out from the real
// star patterns to suit the stage's aspect ratio. Star and line counts may differ per
// constellation, up to NODE_COUNT / LINK_COUNT above. Stars are ordered left to right so
// each one moves to a nearby position when the shape changes.
export const THINKING_CONSTELLATION_VARIANTS: ThinkingConstellationVariant[] = [
  {
    // 頭の小さな鉤から背へ伸びるゆるい弧
    // A gentle arc running from the small hook of the head toward the back
    name: "牡羊座",
    nodes: [
      { x: 18.3, y: 42.4, size: 0.94 },
      { x: 62.4, y: 37.1, size: 1.12 },
      { x: 78.1, y: 50.1, size: 0.94 },
      { x: 81.7, y: 62.9, size: 0.8 },
    ],
    links: [[0, 1], [1, 2], [2, 3]],
  },
  {
    // ヒアデスのV字から二本の角が伸び、後ろへ胴が続く
    // Two horns reaching out from the Hyades V, with the body trailing behind
    name: "牡牛座",
    nodes: [
      { x: 12.5, y: 27.8, size: 1.12 },
      { x: 12.5, y: 71.4, size: 0.94 },
      { x: 47.3, y: 67.5, size: 1.12 },
      { x: 48.7, y: 49.4, size: 0.94 },
      { x: 56.2, y: 64.9, size: 0.94 },
      { x: 68.3, y: 72.2, size: 0.94 },
      { x: 87.5, y: 71.6, size: 0.8 },
    ],
    links: [[1, 2], [0, 3], [2, 4], [3, 4], [4, 5], [5, 6]],
  },
  {
    // 頭の二つ星を結び、足もとへ並んで伸びる二本の体
    // Two bodies running side by side from the joined pair of head stars
    name: "双子座",
    nodes: [
      { x: 21.3, y: 64.2, size: 1.12 },
      { x: 21.3, y: 30.9, size: 1.12 },
      { x: 37.5, y: 20.9, size: 0.8 },
      { x: 45.3, y: 79.1, size: 0.94 },
      { x: 56.9, y: 73.5, size: 0.8 },
      { x: 61.5, y: 28.2, size: 0.94 },
      { x: 77.7, y: 25.8, size: 0.94 },
      { x: 78.7, y: 76.3, size: 1.12 },
    ],
    links: [[0, 1], [1, 2], [0, 3], [2, 5], [3, 4], [4, 7], [5, 6]],
  },
  {
    // 中央の星から三方へ伸びるY字
    // A Y branching three ways from the central star
    name: "蟹座",
    nodes: [
      { x: 21.7, y: 20.9, size: 0.94 },
      { x: 40.9, y: 33.7, size: 0.8 },
      { x: 49, y: 43.6, size: 0.94 },
      { x: 61.5, y: 79.1, size: 0.94 },
      { x: 78.3, y: 25.7, size: 1.12 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [2, 4]],
  },
  {
    // 頭の「獅子の大鎌」と、尾のデネボラへ伸びる胴
    // The Sickle for the head and a body stretching to Denebola at the tail
    name: "獅子座",
    nodes: [
      { x: 21.2, y: 68.3, size: 1.12 },
      { x: 37.4, y: 65, size: 0.94 },
      { x: 37.4, y: 43.8, size: 0.94 },
      { x: 62.9, y: 46.7, size: 1.12 },
      { x: 64.3, y: 31.7, size: 0.94 },
      { x: 68.2, y: 79.1, size: 1.12 },
      { x: 68.7, y: 59.1, size: 0.8 },
      { x: 75.5, y: 20.9, size: 0.8 },
      { x: 78.8, y: 30.1, size: 0.94 },
    ],
    links: [[0, 1], [0, 2], [2, 3], [1, 5], [3, 4], [3, 6], [5, 6], [4, 7], [7, 8]],
  },
  {
    // 菱形の胴から腕と裾が広がり、スピカが輝く
    // Arms and skirt fanning out from a diamond body, with Spica shining
    name: "乙女座",
    nodes: [
      { x: 24.3, y: 65.5, size: 0.8 },
      { x: 38.9, y: 51.3, size: 0.94 },
      { x: 42.3, y: 79.1, size: 1.12 },
      { x: 47.6, y: 64.1, size: 0.8 },
      { x: 50.3, y: 20.9, size: 0.94 },
      { x: 52.6, y: 40.8, size: 0.94 },
      { x: 57.7, y: 53.4, size: 0.94 },
      { x: 65.3, y: 51.6, size: 0.8 },
      { x: 75.7, y: 45, size: 0.94 },
    ],
    links: [[0, 1], [1, 3], [2, 3], [1, 5], [4, 5], [3, 6], [5, 6], [6, 7], [7, 8]],
  },
  {
    // 三角の竿から二つの皿が下がる天秤
    // A balance: two pans hanging from a triangular beam
    name: "天秤座",
    nodes: [
      { x: 29.4, y: 79.1, size: 0.94 },
      { x: 31, y: 44.2, size: 0.94 },
      { x: 47.6, y: 20.9, size: 1.12 },
      { x: 58.8, y: 76.9, size: 0.94 },
      { x: 70.6, y: 49.4, size: 1.12 },
    ],
    links: [[0, 1], [1, 2], [1, 4], [2, 4], [3, 4]],
  },
  {
    // 三つ星の頭からアンタレスを通り、尾の先で巻き上がるS字
    // An S-curve from the three-star head through Antares to the curled stinger
    name: "蠍座",
    nodes: [
      { x: 16.8, y: 50, size: 0.94 },
      { x: 25.6, y: 69.2, size: 0.8 },
      { x: 26.6, y: 28.1, size: 1.12 },
      { x: 33.2, y: 79.1, size: 0.8 },
      { x: 46.2, y: 48.1, size: 0.94 },
      { x: 65.1, y: 30.7, size: 1.12 },
      { x: 76.5, y: 51.9, size: 0.94 },
      { x: 80.9, y: 36, size: 0.94 },
      { x: 83.2, y: 20.9, size: 0.94 },
    ],
    links: [[0, 1], [0, 2], [1, 3], [3, 4], [4, 5], [5, 7], [6, 7], [7, 8]],
  },
  {
    // 注ぎ口・ふた・取っ手がそろった「ティーポット」
    // The Teapot, with its spout, lid, and handle
    name: "射手座",
    nodes: [
      { x: 24.8, y: 59.7, size: 0.8 },
      { x: 31.5, y: 71.6, size: 0.94 },
      { x: 31.9, y: 43.1, size: 1.12 },
      { x: 40.3, y: 42.1, size: 0.8 },
      { x: 51.3, y: 20.9, size: 0.94 },
      { x: 62.9, y: 46.3, size: 0.94 },
      { x: 67.1, y: 79.1, size: 1.12 },
      { x: 75.2, y: 41.4, size: 0.94 },
    ],
    links: [[0, 1], [0, 2], [1, 3], [2, 3], [3, 4], [1, 6], [4, 5], [5, 6], [5, 7], [6, 7]],
  },
  {
    // 二つの角から尾までをつなぐ、逆三角の舟形
    // A boat-like inverted triangle joining the two horns to the tail
    name: "山羊座",
    nodes: [
      { x: 27.2, y: 35.5, size: 1.12 },
      { x: 30.6, y: 37.9, size: 0.94 },
      { x: 37.7, y: 60.9, size: 0.94 },
      { x: 39.8, y: 38.3, size: 0.8 },
      { x: 48.2, y: 39.9, size: 0.8 },
      { x: 55.5, y: 79.1, size: 0.8 },
      { x: 58.3, y: 72.6, size: 0.8 },
      { x: 71.3, y: 30.2, size: 1.12 },
      { x: 72.8, y: 20.9, size: 0.94 },
    ],
    links: [[0, 1], [0, 2], [1, 3], [3, 4], [2, 5], [5, 6], [4, 7], [6, 7], [7, 8]],
  },
  {
    // 肩の星の並びに小さなY字の水瓶があり、水が流れ落ちる
    // A small Y-shaped jar on the line of shoulder stars, pouring a stream of water
    name: "水瓶座",
    nodes: [
      { x: 27.1, y: 79.1, size: 0.94 },
      { x: 27.3, y: 37.1, size: 0.8 },
      { x: 27.7, y: 56.1, size: 0.94 },
      { x: 34.9, y: 32.7, size: 0.94 },
      { x: 35.9, y: 20.9, size: 0.8 },
      { x: 41.1, y: 41.1, size: 0.94 },
      { x: 44.6, y: 35.7, size: 1.12 },
      { x: 56.9, y: 50.6, size: 1.12 },
      { x: 72.9, y: 61.5, size: 0.8 },
    ],
    links: [[0, 2], [1, 2], [1, 3], [3, 4], [3, 5], [5, 6], [6, 7], [7, 8]],
  },
  {
    // 小さな輪の魚から長いリボンが伸び、結び目で折り返す
    // A long ribbon running from the small ring of one fish and turning back at the knot
    name: "魚座",
    nodes: [
      { x: 16.4, y: 67.8, size: 1.12 },
      { x: 22.6, y: 43.8, size: 0.8 },
      { x: 28.2, y: 20.9, size: 1.12 },
      { x: 39, y: 48.7, size: 0.94 },
      { x: 57.5, y: 50.9, size: 0.94 },
      { x: 66.5, y: 79.1, size: 0.8 },
      { x: 67.7, y: 53.6, size: 0.8 },
      { x: 76, y: 47.9, size: 0.8 },
      { x: 83.6, y: 68.9, size: 0.94 },
    ],
    links: [[0, 1], [1, 2], [0, 3], [3, 4], [4, 6], [5, 6], [6, 7], [5, 8], [7, 8]],
  },
];

// 画面に出すモデルの選択肢。value が API に渡すモデル ID で、descriptionKey は説明文の翻訳キー。
// Model choices shown in the UI: value is the model id sent to the API, and descriptionKey is the translation key of its description.
export const MODEL_OPTIONS: ModelOption[] = [
  {
    value: "openai/gpt-oss-120b",
    label: "GPT-OSS 120B",
    descriptionKey: "chat.modelFast",
    shortLabel: "GPT-OSS 120B",
  },
  {
    value: "gpt-6-luna",
    label: "GPT-6 Luna",
    descriptionKey: "chat.modelBalanced",
    shortLabel: "GPT-6 Luna",
  },
  {
    value: "qwen/qwen3.8-27b",
    label: "Qwen 3.8 27B",
    descriptionKey: "chat.modelDeepThinking",
    shortLabel: "Qwen 3.8 27B",
  },
  {
    value: "claude-haiku-5-5",
    label: "Claude Haiku 5.5",
    descriptionKey: "chat.modelCarefulWriting",
    shortLabel: "Claude Haiku 5.5",
  },
];
