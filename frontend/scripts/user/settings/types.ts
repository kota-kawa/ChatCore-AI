import { z } from "zod";

const PromptIdSchema = z.union([z.string(), z.number()]);
const NullableStringSchema = z.string().nullable().optional().transform((value) => value ?? "");
const OptionalDateTimeSchema = z.string().nullable().optional().transform((value) => {
  const normalized = value?.trim();
  return normalized ? normalized : undefined;
});

const PromptRecordApiSchema = z.object({
  id: PromptIdSchema.optional(),
  title: z.string(),
  content: z.string(),
  category: NullableStringSchema,
  input_examples: NullableStringSchema,
  output_examples: NullableStringSchema,
  created_at: OptionalDateTimeSchema
});

export const PromptRecordSchema = z.object({
  id: PromptIdSchema.optional(),
  title: z.string(),
  content: z.string(),
  category: z.string(),
  inputExamples: z.string(),
  outputExamples: z.string(),
  createdAt: z.string().optional()
});

export type PromptRecord = z.infer<typeof PromptRecordSchema>;

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

function normalizePromptRecord(prompt: z.infer<typeof PromptRecordApiSchema>): PromptRecord {
  return {
    id: prompt.id,
    title: prompt.title,
    content: prompt.content,
    category: prompt.category,
    inputExamples: prompt.input_examples,
    outputExamples: prompt.output_examples,
    createdAt: prompt.created_at
  };
}

export const toPromptRecord = (raw: unknown): PromptRecord => {
  const prompt = parseWithSchema(PromptRecordApiSchema, raw, "プロンプトデータの形式が不正です。");
  return normalizePromptRecord(prompt);
};

export const PromptListEntrySchema = z.object({
  id: PromptIdSchema.optional(),
  promptId: PromptIdSchema.optional(),
  prompt: PromptRecordSchema,
  title: z.string(),
  content: z.string(),
  category: z.string(),
  inputExamples: z.string(),
  outputExamples: z.string(),
  createdAt: z.string().optional()
});

export type PromptListEntry = z.infer<typeof PromptListEntrySchema>;

const PromptListEntryBaseApiSchema = z.object({
  id: PromptIdSchema.optional(),
  prompt_id: PromptIdSchema.optional(),
  created_at: OptionalDateTimeSchema
});

const PromptListEntryWithNestedPromptApiSchema = PromptListEntryBaseApiSchema.extend({
  prompt: PromptRecordApiSchema
});

const PromptListEntryLegacyApiSchema = PromptListEntryBaseApiSchema.merge(PromptRecordApiSchema);
const PromptListEntryApiSchema = z.union([PromptListEntryWithNestedPromptApiSchema, PromptListEntryLegacyApiSchema]);

function normalizePromptListEntry(entry: z.infer<typeof PromptListEntryApiSchema>): PromptListEntry {
  const prompt = normalizePromptRecord("prompt" in entry ? entry.prompt : entry);
  return {
    id: entry.id,
    promptId: entry.prompt_id,
    prompt,
    title: prompt.title,
    content: prompt.content,
    category: prompt.category,
    inputExamples: prompt.inputExamples,
    outputExamples: prompt.outputExamples,
    createdAt: entry.created_at
  };
}

export const toPromptListEntry = (raw: unknown): PromptListEntry => {
  const entry = parseWithSchema(PromptListEntryApiSchema, raw, "プロンプトリストデータの形式が不正です。");
  return normalizePromptListEntry(entry);
};

const MyPromptsApiResponseSchema = z.object({
  prompts: z.array(PromptRecordApiSchema).default([])
});

const PromptListApiResponseSchema = z.object({
  prompts: z.array(PromptListEntryApiSchema).default([])
});

const PromptManageMutationApiResponseSchema = z.object({
  message: z.string().optional()
});

export type PromptManageMutationResponse = z.infer<typeof PromptManageMutationApiResponseSchema>;

export function parseMyPromptsResponse(raw: unknown): PromptRecord[] {
  const response = parseWithSchema(
    MyPromptsApiResponseSchema,
    raw,
    "プロンプト一覧レスポンスの形式が不正です。"
  );
  return response.prompts.map(normalizePromptRecord);
}

export function parsePromptListResponse(raw: unknown): PromptListEntry[] {
  const response = parseWithSchema(
    PromptListApiResponseSchema,
    raw,
    "プロンプトリストレスポンスの形式が不正です。"
  );
  return response.prompts.map(normalizePromptListEntry);
}

export function parsePromptManageMutationResponse(raw: unknown): PromptManageMutationResponse {
  return parseWithSchema(
    PromptManageMutationApiResponseSchema,
    raw,
    "操作結果レスポンスの形式が不正です。"
  );
}
