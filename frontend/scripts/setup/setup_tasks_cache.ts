import type { TaskItem } from "./setup_types";
import { CACHE_TTL_MS, STORAGE_KEYS } from "../core/constants";
import type { Locale } from "../../lib/i18n/config";

const TASKS_CACHE_KEY_PREFIX = STORAGE_KEYS.tasksCachePrefix;

type TaskCachePayload = {
  cachedAt: number;
  tasks: TaskItem[];
};

export type TaskCacheScope = "auth" | "guest";

function getTasksCacheKey(scope: TaskCacheScope, locale: Locale) {
  return `${TASKS_CACHE_KEY_PREFIX}${scope}:${locale}`;
}

export function readCachedTasks(scope: TaskCacheScope, locale: Locale) {
  try {
    const raw = localStorage.getItem(getTasksCacheKey(scope, locale));
    if (!raw) return null;
    const payload = JSON.parse(raw) as TaskCachePayload;
    if (!payload || !Array.isArray(payload.tasks) || typeof payload.cachedAt !== "number") {
      return null;
    }
    if (Date.now() - payload.cachedAt > CACHE_TTL_MS.tasks) {
      return null;
    }
    return payload.tasks;
  } catch {
    return null;
  }
}

export function writeCachedTasks(scope: TaskCacheScope, locale: Locale, tasks: TaskItem[]) {
  try {
    const payload: TaskCachePayload = {
      cachedAt: Date.now(),
      tasks
    };
    localStorage.setItem(getTasksCacheKey(scope, locale), JSON.stringify(payload));
  } catch {
    // localStorage が使えない環境では保存をスキップ
  }
}

export function invalidateTasksCache() {
  try {
    for (const scope of ["guest", "auth"]) {
      for (const locale of ["ja", "en"]) {
        localStorage.removeItem(`${TASKS_CACHE_KEY_PREFIX}${scope}:${locale}`);
      }
      localStorage.removeItem(`${TASKS_CACHE_KEY_PREFIX}${scope}`);
    }
  } catch {
    // localStorage が使えない環境では削除をスキップ
  }
}
