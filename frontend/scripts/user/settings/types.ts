import { z } from "zod";

import {
  LikedPromptsApiResponseSchema,
  LikedPromptApiSchema,
  MyPromptsApiResponseSchema,
  PromptManageMutationApiResponseSchema,
  PromptRecordApiSchema,
  type LikedPromptApi,
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

function normalizeLikedPrompt(entry: LikedPromptApi) {
  const prompt = normalizePromptRecord({
    id: entry.prompt_id,
    title: entry.title,
    content: entry.content,
    category: entry.category,
    input_examples: entry.input_examples,
    output_examples: entry.output_examples,
    created_at: entry.prompt_created_at ?? entry.created_at
  });
  return {
    id: entry.id ?? undefined,
    likeId: entry.like_id ?? entry.id ?? undefined,
    promptId: entry.prompt_id ?? undefined,
    prompt,
    title: prompt.title,
    content: prompt.content,
    category: prompt.category,
    inputExamples: prompt.inputExamples,
    outputExamples: prompt.outputExamples,
    createdAt: normalizeOptionalDateTime(entry.prompt_created_at ?? entry.created_at),
    likedAt: normalizeOptionalDateTime(entry.liked_at)
  };
}

export const LikedPromptSchema = LikedPromptApiSchema.transform(normalizeLikedPrompt);
export type LikedPrompt = z.infer<typeof LikedPromptSchema>;

export type PromptManageMutationResponse = z.infer<typeof PromptManageMutationApiResponseSchema>;

export function parseMyPromptsResponse(raw: unknown): PromptRecord[] {
  const response = parseWithSchema(
    MyPromptsApiResponseSchema,
    raw,
    "プロンプト一覧レスポンスの形式が不正です。"
  );
  return (response.prompts ?? []).map((prompt) => normalizePromptRecord(prompt));
}

export function parseLikedPromptsResponse(raw: unknown): LikedPrompt[] {
  const response = parseWithSchema(
    LikedPromptsApiResponseSchema,
    raw,
    "いいねしたプロンプトレスポンスの形式が不正です。"
  );
  return (response.prompts ?? []).map((entry) => normalizeLikedPrompt(entry));
}

export function parsePromptManageMutationResponse(raw: unknown): PromptManageMutationResponse {
  return parseWithSchema(
    PromptManageMutationApiResponseSchema,
    raw,
    "操作結果レスポンスの形式が不正です。"
  );
}

// MCP OAuth 同意画面と設定画面で使用する連携情報
// MCP OAuth consent and connection data used by the consent and settings pages.
const McpOAuthConsentSchema = z.object({
  client_name: z.string().trim().min(1),
  client_id: z.string().trim().min(1),
  client_host: z.string().transform((value) => value.trim()),
  redirect_host: z.string().trim().min(1),
  scope: z.string().trim().min(1),
  localhost_warning: z.boolean()
});

const McpOAuthConnectionsResponseSchema = z.object({
  connections: z.array(z.object({
    id: z.union([z.string(), z.number()]).transform(String),
    client_name: z.string().trim().min(1),
    client_host: z.string().transform((value) => value.trim()),
    created_at: z.string().trim().min(1),
    last_used_at: z.string().trim().min(1).nullable()
  }))
});

const ClaudeOAuthClientStatusSchema = z.discriminatedUnion("configured", [
  z.object({ configured: z.literal(false) }),
  z.object({
    configured: z.literal(true),
    client_id: z.string().trim().min(1),
    created_at: z.string().trim().min(1),
    redirect_uri: z.string().url(),
    mcp_server_url: z.string().url()
  })
]);

const ClaudeOAuthClientCredentialsSchema = z.object({
  client_id: z.string().trim().min(1),
  client_secret: z.string().trim().min(1),
  redirect_uri: z.string().url(),
  mcp_server_url: z.string().url()
});

const McpOAuthConsentDecisionSchema = z.object({
  redirect_url: z.string().url()
});

export type McpOAuthConsent = z.infer<typeof McpOAuthConsentSchema>;
export type McpOAuthConnection = z.infer<typeof McpOAuthConnectionsResponseSchema>["connections"][number];
export type ClaudeOAuthClientStatus = z.infer<typeof ClaudeOAuthClientStatusSchema>;
export type ClaudeOAuthClientCredentials = z.infer<typeof ClaudeOAuthClientCredentialsSchema>;

export function parseMcpOAuthConsent(raw: unknown): McpOAuthConsent {
  return parseWithSchema(McpOAuthConsentSchema, raw, "OAuth 同意情報の形式が不正です。");
}

export function parseMcpOAuthConnections(raw: unknown): McpOAuthConnection[] {
  return parseWithSchema(
    McpOAuthConnectionsResponseSchema,
    raw,
    "AIサービス連携一覧の形式が不正です。"
  ).connections;
}

export function parseClaudeOAuthClientStatus(raw: unknown): ClaudeOAuthClientStatus {
  return parseWithSchema(
    ClaudeOAuthClientStatusSchema,
    raw,
    "連携用認証情報の状態形式が不正です。"
  );
}

export function parseClaudeOAuthClientCredentials(raw: unknown): ClaudeOAuthClientCredentials {
  return parseWithSchema(
    ClaudeOAuthClientCredentialsSchema,
    raw,
    "連携用認証情報の形式が不正です。"
  );
}

export function parseMcpOAuthConsentDecision(raw: unknown): string {
  return parseWithSchema(
    McpOAuthConsentDecisionSchema,
    raw,
    "OAuth 同意結果の形式が不正です。"
  ).redirect_url;
}
