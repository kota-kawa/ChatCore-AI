import { useCallback, useEffect, useRef } from "react";

import { recordPromptImpressions } from "../../scripts/prompt_share/api";
import { getPromptId } from "./prompt_share_page_utils";
import type { PromptRecord } from "./prompt_card";

// まとめ送信までの待ち時間。スクロール中に 1 枚ずつ送らず、静止したら 1 回で送る。
// Delay before a batch is sent, so scrolling does not fire one request per card.
const IMPRESSION_FLUSH_DELAY_MS = 1500;

// 一覧のカードが画面に入った回数を記録する。1 投稿につき、このページを開いている間は 1 回だけ数える。
// Record how often feed cards were shown. Each prompt counts once for as long as the page stays open.
export function usePromptImpressionTracker() {
  const seenIdsRef = useRef(new Set<string>());
  const pendingIdsRef = useRef<string[]>([]);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flush = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const promptIds = pendingIdsRef.current;
    if (promptIds.length === 0) {
      return;
    }
    pendingIdsRef.current = [];
    void recordPromptImpressions(promptIds).catch(() => {
      // 計測の失敗で閲覧を妨げない。送れなかった分は数えない。
      // Never let measurement interrupt reading; uncounted impressions are simply lost.
    });
  }, []);

  useEffect(() => {
    // 離脱直前に残りをまとめて送る。fetch の keepalive がページ終了後の完了を許す。
    // Flush what is left right before the page goes away; fetch keepalive lets it complete.
    const handlePageHide = () => flush();
    window.addEventListener("pagehide", handlePageHide);
    return () => {
      window.removeEventListener("pagehide", handlePageHide);
      flush();
    };
  }, [flush]);

  return useCallback(
    (prompt: PromptRecord) => {
      const promptId = getPromptId(prompt);
      if (!promptId || seenIdsRef.current.has(promptId)) {
        return;
      }
      seenIdsRef.current.add(promptId);
      pendingIdsRef.current.push(promptId);
      if (timerRef.current === null) {
        timerRef.current = setTimeout(flush, IMPRESSION_FLUSH_DELAY_MS);
      }
    },
    [flush]
  );
}
