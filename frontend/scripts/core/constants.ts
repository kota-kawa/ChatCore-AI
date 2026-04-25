const SHORT_CACHE_TTL_MS = 30_000;

export const STORAGE_KEYS = {
  currentChatRoomId: "currentChatRoomId",
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

export const API_PATHS = {
  currentUser: "/api/current_user",
  getChatRooms: "/api/get_chat_rooms",
  chat: "/api/chat",
  chatStop: "/api/chat_stop",
  chatGenerationStream: "/api/chat_generation_stream"
} as const;

export const ROUTES = {
  login: "/login",
  logout: "/logout",
  settings: "/settings"
} as const;

export const AUTH_SUCCESS_HINT = {
  queryParam: "auth",
  successValue: "success"
} as const;
