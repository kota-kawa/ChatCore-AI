// ユーザーの「遷移しそうな」意図（hover / focus / touchstart）を捉えて、対象ルートを先読みするフック。
// A hook that prefetches a target route on user intent (hover / focus / touchstart).
//
// クリックを待たずに Next.js の router.prefetch を発火させることで、遅い回線でも遷移を体感的に速くする。
// Firing router.prefetch before the click makes navigation feel instant even on slow links.
// 一度先読みしたルートは記録し、重複したプリフェッチを避ける。
// Each route is prefetched at most once to avoid duplicate work.

import { useCallback, useMemo, useRef } from "react";
import { useRouter } from "next/router";

export type IntentPrefetchHandlers = {
  onMouseEnter: () => void;
  onFocus: () => void;
  onTouchStart: () => void;
};

export function useIntentPrefetch(href: string | undefined): IntentPrefetchHandlers {
  const router = useRouter();
  const prefetchedRef = useRef<Set<string>>(new Set());

  const trigger = useCallback(() => {
    if (!href) return;
    if (prefetchedRef.current.has(href)) return;
    prefetchedRef.current.add(href);
    void router.prefetch(href).catch(() => {
      // プリフェッチは最適化のみ。失敗しても次回再試行できるよう記録を取り消す。
      // Prefetch is optimization only; un-record on failure so it can retry next time.
      prefetchedRef.current.delete(href);
    });
  }, [href, router]);

  return useMemo(
    () => ({ onMouseEnter: trigger, onFocus: trigger, onTouchStart: trigger }),
    [trigger],
  );
}
