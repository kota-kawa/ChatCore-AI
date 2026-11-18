import type { ChatRoomMode } from "./types";

const LOGGED_IN_USER_SCOPE_PREFIX = "user:";

function encodeScopeSegments(segments: string[]) {
  return segments.map((segment) => encodeURIComponent(segment)).join(":");
}

export function createStructuredUiStateScope(options: {
  loggedIn: boolean;
  roomMode: ChatRoomMode;
  roomId: string | null;
  userScope: string | null;
  answerId: string;
  blockId: string;
}): string | undefined {
  if (
    !options.loggedIn ||
    options.roomMode !== "normal" ||
    !options.roomId ||
    !options.userScope?.startsWith(LOGGED_IN_USER_SCOPE_PREFIX)
  ) {
    return undefined;
  }

  return encodeScopeSegments([options.userScope, options.roomId, options.answerId, options.blockId]);
}

export function createStructuredUiMetricsScope(
  userScope: string | null,
  roomId: string,
  roomMode: ChatRoomMode,
): string | null {
  if (roomMode !== "normal" || !userScope?.startsWith(LOGGED_IN_USER_SCOPE_PREFIX)) return null;
  return encodeScopeSegments([userScope, roomId]);
}

export function readStructuredUiScopeRoomId(stateScope: string): string | null {
  const [, encodedRoomId] = stateScope.split(":");
  if (!encodedRoomId) return null;
  try {
    return decodeURIComponent(encodedRoomId);
  } catch {
    return null;
  }
}

export function readStructuredUiScopeUserScope(stateScope: string): string | null {
  const [encodedUserScope] = stateScope.split(":");
  if (!encodedUserScope) return null;
  try {
    return decodeURIComponent(encodedUserScope);
  } catch {
    return null;
  }
}
