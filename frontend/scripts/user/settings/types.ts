import { z } from "zod";

import {
  MyPromptsApiResponseSchema,
  PromptListApiResponseSchema,
  PromptListEntryApiSchema,
  PromptListEntryLegacyApiSchema,
  PromptManageMutationApiResponseSchema,
  PromptRecordApiSchema,
  type PromptListEntryApi,
  type PromptListEntryLegacyApi,
  type PromptRecordApi
} from "../../../types/generated/api_schemas";

function parseWithSchema<TSchema extends z.ZodTypeAny>(
  schema: TSchema,
  raw: unknown,
  invalidMessage: string
): z.infer<TSchema> {
  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    throw new Error(invalidMessage);
  }
  return parsed.data;
}

function normalizeNullableString(value: string | null | undefined): string {
  return value ?? "";
}

function normalizeOptionalDateTime(value: string | null | undefined): string | undefined {
  const normalized = value?.trim();
  return normalized ? normalized : undefined;
}

function normalizePromptRecord(prompt: PromptRecordApi): {
  id?: string | number;
  title: string;
  content: string;
  category: string;
  inputExamples: string;
  outputExamples: string;
  createdAt?: string;
} {
  return {
    id: prompt.id ?? undefined,
    title: prompt.title,
    content: prompt.content,
    category: normalizeNullableString(prompt.category),
    inputExamples: normalizeNullableString(prompt.input_examples),
    outputExamples: normalizeNullableString(prompt.output_examples),
    createdAt: normalizeOptionalDateTime(prompt.created_at)
  };
}

export const PromptRecordSchema = PromptRecordApiSchema.transform(normalizePromptRecord);
export type PromptRecord = z.infer<typeof PromptRecordSchema>;

export const toPromptRecord = (raw: unknown): PromptRecord => {
  return parseWithSchema(PromptRecordSchema, raw, "プロンプトデータの形式が不正です。");
};

function isPromptListEntryWithNestedPrompt(
  entry: PromptListEntryApi | PromptListEntryLegacyApi
): entry is PromptListEntryApi {
  return "prompt" in entry;
}

function normalizePromptListEntry(entry: PromptListEntryApi | PromptListEntryLegacyApi) {
  const prompt = normalizePromptRecord(isPromptListEntryWithNestedPrompt(entry) ? entry.prompt : entry);
  return {
    id: entry.id ?? undefined,
    promptId: entry.prompt_id ?? undefined,
    prompt,
    title: prompt.title,
    content: prompt.content,
    category: prompt.category,
    inputExamples: prompt.inputExamples,
    outputExamples: prompt.outputExamples,
    createdAt: normalizeOptionalDateTime(entry.created_at)
  };
}

const PromptListEntryApiUnionSchema = z.union([PromptListEntryApiSchema, PromptListEntryLegacyApiSchema]);
export const PromptListEntrySchema = PromptListEntryApiUnionSchema.transform(normalizePromptListEntry);
export type PromptListEntry = z.infer<typeof PromptListEntrySchema>;

export const toPromptListEntry = (raw: unknown): PromptListEntry => {
  return parseWithSchema(PromptListEntrySchema, raw, "プロンプトリストデータの形式が不正です。");
};

export type PromptManageMutationResponse = z.infer<typeof PromptManageMutationApiResponseSchema>;

export function parseMyPromptsResponse(raw: unknown): PromptRecord[] {
  const response = parseWithSchema(
    MyPromptsApiResponseSchema,
    raw,
    "プロンプト一覧レスポンスの形式が不正です。"
  );
  return (response.prompts ?? []).map((prompt) => normalizePromptRecord(prompt));
}

export function parsePromptListResponse(raw: unknown): PromptListEntry[] {
  const response = parseWithSchema(
    PromptListApiResponseSchema,
    raw,
    "プロンプトリストレスポンスの形式が不正です。"
  );
  return (response.prompts ?? []).map((entry) => normalizePromptListEntry(entry));
}

export function parsePromptManageMutationResponse(raw: unknown): PromptManageMutationResponse {
  return parseWithSchema(
    PromptManageMutationApiResponseSchema,
    raw,
    "操作結果レスポンスの形式が不正です。"
  );
}
