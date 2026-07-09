import { useCallback, useEffect, useRef, useState } from "react";

// カード操作時の一時的な視覚効果とタイマーを管理する
// Manages temporary card action effects and their timers
export function usePromptShareActionEffects() {
  const [actionEffectIds, setActionEffectIds] = useState<Set<string>>(new Set());
  // アニメーション効果のタイマーIDを管理し、素早い連続操作でタイマーが積み重ならないようにする
  // Stores animation effect timer IDs to cancel previous timers on rapid successive actions
  const actionEffectTimersRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    return () => {
      actionEffectTimersRef.current.forEach((timerId) => {
        window.clearTimeout(timerId);
      });
      actionEffectTimersRef.current.clear();
    };
  }, []);

  // いいね時などのアニメーション効果を発火させ、一定時間後に自動解除する
  // Triggers a visual animation effect and automatically removes it after a fixed duration
  const triggerActionEffect = useCallback((effectId: string) => {
    const activeTimerId = actionEffectTimersRef.current.get(effectId);
    if (activeTimerId) {
      window.clearTimeout(activeTimerId);
    }

    setActionEffectIds((current) => {
      const next = new Set(current);
      next.add(effectId);
      return next;
    });

    const timerId = window.setTimeout(() => {
      actionEffectTimersRef.current.delete(effectId);
      setActionEffectIds((current) => {
        const next = new Set(current);
        next.delete(effectId);
        return next;
      });
    }, 720);

    actionEffectTimersRef.current.set(effectId, timerId);
  }, []);

  return {
    actionEffectIds,
    triggerActionEffect
  };
}
