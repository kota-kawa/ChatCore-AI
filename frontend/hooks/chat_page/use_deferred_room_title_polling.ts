import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";

import type { ChatRoom } from "../../lib/chat_page/types";
import { ChatRoomTitleResponseSchema } from "../../types/generated/api_schemas";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { readJsonBodySafe } from "../../scripts/core/runtime_validation";

const DEFERRED_ROOM_TITLE_POLL_DELAYS_MS = [250, 500, 1_000, 2_000, 4_000] as const;

function waitForPollDelay(delayMs: number, signal: AbortSignal): Promise<boolean> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve(false);
      return;
    }

    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve(true);
    }, delayMs);
    const onAbort = () => {
      window.clearTimeout(timer);
      resolve(false);
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export function useDeferredRoomTitlePolling(setChatRooms: Dispatch<SetStateAction<ChatRoom[]>>) {
  const pollsByRoomRef = useRef(new Map<string, AbortController>());

  useEffect(() => {
    const pollsByRoom = pollsByRoomRef.current;
    return () => {
      pollsByRoom.forEach((controller) => controller.abort());
      pollsByRoom.clear();
    };
  }, []);

  const applyRoomTitleUpdate = useCallback(
    (roomId: string, title: unknown, allowedCurrentTitles?: readonly string[]) => {
      if (typeof title !== "string") return;
      const normalizedTitle = title.trim();
      if (!normalizedTitle) return;
      const allowedTitles = allowedCurrentTitles ? new Set(allowedCurrentTitles) : null;

      setChatRooms((previous) => {
        let changed = false;
        const next = previous.map((room) => {
          if (room.id !== roomId || (allowedTitles && !allowedTitles.has(room.title))) return room;
          if (room.title === normalizedTitle) return room;
          changed = true;
          return { ...room, title: normalizedTitle };
        });
        return changed ? next : previous;
      });
    },
    [setChatRooms],
  );

  const startDeferredRoomTitlePolling = useCallback(
    (roomId: string, initialTitleCandidates: readonly string[]) => {
      const candidates = initialTitleCandidates;
      if (!candidates.length) return;

      pollsByRoomRef.current.get(roomId)?.abort();
      const controller = new AbortController();
      pollsByRoomRef.current.set(roomId, controller);

      const poll = async () => {
        try {
          for (const delayMs of DEFERRED_ROOM_TITLE_POLL_DELAYS_MS) {
            if (!(await waitForPollDelay(delayMs, controller.signal))) return;

            let response: Response;
            try {
              response = await resilientFetch(
                `/api/chat_room_title?room_id=${encodeURIComponent(roomId)}`,
                { credentials: "same-origin", signal: controller.signal },
                { timeoutMs: 2_000, retries: 0 },
              );
            } catch {
              if (controller.signal.aborted) return;
              continue;
            }

            if (controller.signal.aborted || response.status === 404) return;
            if (!response.ok) {
              if (response.status >= 500) continue;
              return;
            }

            const payload = ChatRoomTitleResponseSchema.safeParse(await readJsonBodySafe(response));
            if (controller.signal.aborted) return;
            if (!payload.success) return;
            const title = payload.data.title.trim();
            if (!title || candidates.includes(title)) continue;

            applyRoomTitleUpdate(roomId, title, candidates);
            return;
          }
        } catch {
          // タイトル確認はベストエフォートで、回答の成否へ影響させない。
        } finally {
          if (pollsByRoomRef.current.get(roomId) === controller) {
            pollsByRoomRef.current.delete(roomId);
          }
        }
      };

      void poll();
    },
    [applyRoomTitleUpdate],
  );

  return { applyRoomTitleUpdate, startDeferredRoomTitlePolling };
}
