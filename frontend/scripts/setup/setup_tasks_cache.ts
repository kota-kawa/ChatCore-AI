import type { TaskItem } from "./setup_types";

const AUTH_STATE_CACHE_KEY = "chatcore.auth.loggedIn";
const TASKS_CACHE_KEY_PREFIX = "chatcore.tasks.v2.";
const TASKS_CACHE_TTL_MS = 30_000;

type TaskCachePayload = {
  cachedAt: number;
  tasks: TaskItem[];
};

function getTasksCacheKey() {
  let scope = "guest";
  try {
    if (localStorage.getItem(AUTH_STATE_CACHE_KEY) === "1") {
      scope = "auth";
    }
  } catch {
    // localStorage が使えない環境では guest スコープを使用
  }
  return `${TASKS_CACHE_KEY_PREFIX}${scope}`;
}

export function readCachedTasks() {
  try {
    const raw = localStorage.getItem(getTasksCacheKey());
    if (!raw) return null;
    const payload = JSON.parse(raw) as TaskCachePayload;
    if (!payload || !Array.isArray(payload.tasks) || typeof payload.cachedAt !== "number") {
      return null;
    }
    if (Date.now() - payload.cachedAt > TASKS_CACHE_TTL_MS) {
      return null;
    }
    return payload.tasks;
  } catch {
    return null;
  }
}

export function writeCachedTasks(tasks: TaskItem[]) {
  try {
    const payload: TaskCachePayload = {
      cachedAt: Date.now(),
      tasks
    };
    localStorage.setItem(getTasksCacheKey(), JSON.stringify(payload));
  } catch {
    // localStorage が使えない環境では保存をスキップ
  }
}

export function invalidateTasksCache() {
  try {
    localStorage.removeItem(`${TASKS_CACHE_KEY_PREFIX}guest`);
    localStorage.removeItem(`${TASKS_CACHE_KEY_PREFIX}auth`);
  } catch {
    // localStorage が使えない環境では削除をスキップ
  }
}
