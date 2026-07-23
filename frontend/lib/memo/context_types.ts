// パーソナル・コンテキスト金庫（マイコンテキスト）のフロント型定義。
// Frontend types for the personal context vault ("My Context").
import type {
  ContextFactCreateRequest,
  ContextFactListResponse,
  ContextFactResponse,
  ContextFactUpdateRequest,
} from "../../types/generated/api_schemas";

export type ContextFact = ContextFactResponse;
export type ContextFactType = ContextFact["fact_type"];
export type ContextFactStatus = ContextFact["status"];
export type ContextFactSourceKind = ContextFact["source_kind"];

export type ContextFactImportancePreset = 25 | 50 | 75;

export type ContextFactListPayload = ContextFactListResponse & {
  error?: string;
};

export type ContextFactMutationPayload = {
  status?: string;
  fact?: ContextFact;
  error?: string;
};

export type ContextFactCreateInput = ContextFactCreateRequest;

type ContextFactUpdateFields = Pick<
  ContextFactUpdateRequest,
  "title" | "content" | "fact_type" | "importance" | "status"
>;

export type ContextFactUpdateInput = Pick<ContextFactUpdateRequest, "revision"> & {
  [Field in keyof ContextFactUpdateFields]?: Exclude<ContextFactUpdateFields[Field], null>;
};

export const CONTEXT_FACT_TYPE_LABELS: Record<ContextFactType, string> = {
  profile: "経歴・プロフィール",
  preference: "好み・方針",
  project: "プロジェクト文脈",
  decision: "過去の決定",
  reference: "参考リンク・資料",
};

export const CONTEXT_FACT_TYPE_OPTIONS: { value: ContextFactType; label: string }[] = [
  { value: "profile", label: CONTEXT_FACT_TYPE_LABELS.profile },
  { value: "preference", label: CONTEXT_FACT_TYPE_LABELS.preference },
  { value: "project", label: CONTEXT_FACT_TYPE_LABELS.project },
  { value: "decision", label: CONTEXT_FACT_TYPE_LABELS.decision },
  { value: "reference", label: CONTEXT_FACT_TYPE_LABELS.reference },
];

export const CONTEXT_FACT_SOURCE_LABELS: Record<ContextFactSourceKind, string> = {
  manual: "手動",
  mcp: "MCP",
  chat: "チャット",
  import: "インポート",
};

export const CONTEXT_FACT_IMPORTANCE_OPTIONS: {
  value: `${ContextFactImportancePreset}`;
  label: string;
}[] = [
  { value: "25", label: "低" },
  { value: "50", label: "標準" },
  { value: "75", label: "高" },
];

export function getContextFactImportanceLabel(importance: number): string {
  if (importance <= 33) return "低";
  if (importance >= 67) return "高";
  return "標準";
}

export function toContextFactImportancePreset(importance: number): ContextFactImportancePreset {
  if (importance <= 33) return 25;
  if (importance >= 67) return 75;
  return 50;
}
