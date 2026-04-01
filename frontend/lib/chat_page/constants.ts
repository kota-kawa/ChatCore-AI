import type { CSSProperties } from "react";
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
export const THINKING_CONSTELLATION_NODES = [
  { x: 22, y: 58, size: 0.92 },
  { x: 37, y: 36, size: 1 },
  { x: 51, y: 49, size: 0.86 },
  { x: 67, y: 34, size: 1.08 },
  { x: 80, y: 46, size: 0.78 },
];
export const THINKING_CONSTELLATION_LINKS: Array<[number, number]> = [
  [0, 1],
  [1, 2],
  [2, 3],
  [3, 4],
];

export const roomMenuBaseStyle: CSSProperties = {
  position: "absolute",
  top: "50%",
  right: 0,
  transform: "translateY(-50%)",
  background: "#fff",
  border: "1px solid #ddd",
  borderRadius: "6px",
  boxShadow: "0 2px 4px rgba(0,0,0,.1)",
  zIndex: 10,
  minWidth: "140px",
  overflow: "hidden",
};

export const roomMenuItemBaseStyle: CSSProperties = {
  padding: "8px 16px",
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  fontSize: "14px",
  borderBottom: "1px solid #ddd",
};

export const MODEL_OPTIONS: ModelOption[] = [
  { value: "openai/gpt-oss-120b", label: "GROQ | GPT-OSS 120B（標準・高品質な応答）", shortLabel: "GPT-OSS 120B" },
  {
    value: "gpt-5-mini-2025-08-07",
    label: "OPENAI | GPT-5 mini（高品質・推論が必要な作業向け）",
    shortLabel: "GPT-5 mini",
  },
  { value: "gemini-2.5-flash", label: "Gemini | 2.5 Flash（軽い作業向け）", shortLabel: "Gemini 2.5" },
];
