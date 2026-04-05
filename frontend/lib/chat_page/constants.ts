import type { ModelOption } from "./types";
import chatContract from "../../data/chat_contract.json";

function toPositiveInteger(value: unknown, fallback: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  const parsed = Math.trunc(value);
  return parsed > 0 ? parsed : fallback;
}

const chatHistoryContract = (chatContract as { chat_history?: { page_size_default?: number } }).chat_history;
const chatHistoryPageSizeDefault = chatHistoryContract?.page_size_default;

export const DEFAULT_MODEL = "openai/gpt-oss-120b";
export const CHAT_HISTORY_PAGE_SIZE = toPositiveInteger(chatHistoryPageSizeDefault, 50);
export const STICKY_SCROLL_BOTTOM_THRESHOLD_PX = 72;
export const THINKING_CONSTELLATION_BASE_WIDTH = 208;
export const THINKING_CONSTELLATION_BASE_HEIGHT = 86;
export const THINKING_CONSTELLATION_NODE_COUNT = 8;
export const THINKING_CONSTELLATION_LINK_COUNT = 8;
export const THINKING_CONSTELLATION_STEP_MS = 2400;

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

export const THINKING_CONSTELLATION_VARIANTS: ThinkingConstellationVariant[] = [
  {
    name: "牡羊座",
    nodes: [
      { x: 22, y: 58, size: 0.92 },
      { x: 37, y: 36, size: 1 },
      { x: 51, y: 49, size: 0.86 },
      { x: 67, y: 34, size: 1.08 },
      { x: 80, y: 46, size: 0.78 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4]],
  },
  {
    name: "牡牛座",
    nodes: [
      { x: 20, y: 48, size: 0.82 },
      { x: 31, y: 28, size: 0.94 },
      { x: 45, y: 50, size: 1.08 },
      { x: 59, y: 28, size: 0.94 },
      { x: 72, y: 48, size: 0.82 },
      { x: 52, y: 68, size: 0.9 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [2, 5]],
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
      { x: 78, y: 68, size: 0.94 },
    ],
    links: [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [2, 4], [4, 6], [1, 3]],
  },
  {
    name: "蟹座",
    nodes: [
      { x: 26, y: 50, size: 0.88 },
      { x: 36, y: 34, size: 0.82 },
      { x: 50, y: 36, size: 1 },
      { x: 60, y: 50, size: 0.88 },
      { x: 48, y: 66, size: 0.9 },
      { x: 30, y: 64, size: 0.82 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]],
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
      { x: 82, y: 56, size: 0.82 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]],
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
      { x: 86, y: 74, size: 0.8 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]],
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
      { x: 74, y: 42, size: 0.82 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [1, 4], [4, 5], [5, 6], [6, 2]],
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
      { x: 88, y: 68, size: 1 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]],
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
      { x: 78, y: 74, size: 0.78 },
    ],
    links: [[0, 1], [1, 2], [1, 3], [3, 4], [4, 5], [4, 6]],
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
      { x: 90, y: 70, size: 0.78 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]],
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
      { x: 90, y: 46, size: 0.78 },
    ],
    links: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]],
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
      { x: 84, y: 58, size: 0.78 },
    ],
    links: [[0, 1], [1, 2], [1, 3], [3, 4], [4, 6], [6, 5], [6, 7]],
  },
];

export const THINKING_CONSTELLATION_NODES = THINKING_CONSTELLATION_VARIANTS[0]?.nodes ?? [];
export const THINKING_CONSTELLATION_LINKS = THINKING_CONSTELLATION_VARIANTS[0]?.links ?? [];

export const MODEL_OPTIONS: ModelOption[] = [
  { value: "openai/gpt-oss-120b", label: "GROQ | GPT-OSS 120B（標準・高品質な応答）", shortLabel: "GPT-OSS 120B" },
  {
    value: "gpt-5-mini-2025-08-07",
    label: "OPENAI | GPT-5 mini（高品質・推論が必要な作業向け）",
    shortLabel: "GPT-5 mini",
  },
  { value: "gemini-2.5-flash", label: "Gemini | 2.5 Flash（軽い作業向け）", shortLabel: "Gemini 2.5" },
];
