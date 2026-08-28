import {
  UserSkillApiSchema,
  UserSkillMutationApiResponseSchema,
  UserSkillsApiResponseSchema,
  type UserSkillApi,
} from "../../types/generated/api_schemas";
import { fetchJsonOrThrow, isRecord } from "../../scripts/core/runtime_validation";
import { resilientFetch } from "../../scripts/core/resilient_fetch";

type SkillFetchImpl = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export const MAX_USER_SKILL_NAME_LENGTH = 100;
export const MAX_USER_SKILL_INSTRUCTIONS_LENGTH = 12_000;

function parseSkillsPayload(payload: unknown): UserSkillApi[] {
  const parsed = UserSkillsApiResponseSchema.safeParse(payload);
  if (!parsed.success) throw new Error("Skillの一覧を読み込めませんでした。");
  return parsed.data.skills ?? [];
}

function parseSkillMutationPayload(payload: unknown): UserSkillApi {
  const parsed = UserSkillMutationApiResponseSchema.safeParse(payload);
  if (!parsed.success || !parsed.data.skill) {
    throw new Error("Skillの更新結果を読み込めませんでした。");
  }
  return UserSkillApiSchema.parse(parsed.data.skill);
}

export async function fetchUserSkills(fetchImpl: SkillFetchImpl = resilientFetch): Promise<UserSkillApi[]> {
  const { payload } = await fetchJsonOrThrow<unknown>("/api/skills", undefined, {
    defaultMessage: "Skillの読み込みに失敗しました。",
    fetchImpl,
  });
  return parseSkillsPayload(payload);
}

export async function createUserSkill(
  name: string,
  instructions: string,
  fetchImpl: SkillFetchImpl = resilientFetch,
): Promise<UserSkillApi> {
  const { payload } = await fetchJsonOrThrow<unknown>("/api/skills", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ name, instructions }),
  }, {
    defaultMessage: "Skillの追加に失敗しました。",
    fetchImpl,
  });
  return parseSkillMutationPayload(payload);
}

export async function updateUserSkillState(
  skillId: number,
  isEnabled: boolean,
  fetchImpl: SkillFetchImpl = resilientFetch,
): Promise<UserSkillApi> {
  const { payload } = await fetchJsonOrThrow<unknown>(`/api/skills/${skillId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ is_enabled: isEnabled }),
  }, {
    defaultMessage: "Skillの状態を更新できませんでした。",
    fetchImpl,
  });
  return parseSkillMutationPayload(payload);
}

export async function deleteUserSkill(
  skillId: number,
  fetchImpl: SkillFetchImpl = resilientFetch,
): Promise<void> {
  await fetchJsonOrThrow<unknown>(`/api/skills/${skillId}`, {
    method: "DELETE",
    credentials: "same-origin",
  }, {
    defaultMessage: "Skillの削除に失敗しました。",
    fetchImpl,
  });
}

export function isSkillApiRecord(value: unknown): value is UserSkillApi {
  return isRecord(value) && UserSkillApiSchema.safeParse(value).success;
}

export type UserSkill = UserSkillApi;
