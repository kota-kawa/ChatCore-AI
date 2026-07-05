const SHORT_CACHE_TTL_MS = 30_000;

export const STORAGE_KEYS = {
  currentChatRoomId: "currentChatRoomId",
  activeChatRoomId: "chatcore.chat.activeRoomId",
  activeChatRoomMode: "chatcore.chat.activeRoomMode",
  activeChatGeneration: "chatcore.chat.activeGeneration",
  homePageViewState: "chatcore.home.viewState",
  authStateCache: "chatcore.auth.loggedIn",
  authStateCachedAt: "chatcore.auth.cachedAt",
  tasksCachePrefix: "chatcore.tasks.v2.",
  setupInfoDraft: "chatcore.setup.infoDraft",
  temporaryModeEnabled: "chatcore.setup.temporaryModeEnabled"
} as const;

export const CACHE_TTL_MS = {
  authState: SHORT_CACHE_TTL_MS,
  tasks: SHORT_CACHE_TTL_MS
} as const;

export const AUTH_SUCCESS_HINT = {
  queryParam: "auth",
  successValue: "success"
} as const;
