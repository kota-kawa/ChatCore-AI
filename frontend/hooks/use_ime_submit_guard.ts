// IME変換確定のEnterを送信と誤認しないためのReactフック
// React hook that keeps the Enter which confirms an IME conversion from being read as "send"
import { useCallback, useMemo, useRef } from "react";
import type { CompositionEvent as ReactCompositionEvent, KeyboardEvent as ReactKeyboardEvent } from "react";

import {
  isImeCompositionKeyEvent,
  isWithinCompositionGrace,
  shouldArmCompositionGrace,
} from "../lib/ui/ime_composition";

export type ImeSubmitGuard<T> = {
  // textarea / input にそのまま展開する composition ハンドラ
  // Composition handlers to spread onto the textarea / input
  compositionHandlers: {
    onCompositionEnd: (event: ReactCompositionEvent<T>) => void;
  };
  // 変換に属するキー入力なら true。送信ハンドラの先頭で弾く用途。
  // True when the key press belongs to a conversion; bail out of the submit handler on true.
  isComposingKeyEvent: (event: ReactKeyboardEvent<T>) => boolean;
};

export function useImeSubmitGuard<T = HTMLTextAreaElement>(): ImeSubmitGuard<T> {
  // 変換中かどうかのフラグは自前で持たず、ブラウザの申告に任せる。compositionend が届かない
  // まま入力欄を離れると自前のフラグが立ち残り、以後その欄から送信できなくなるため。
  // Composition state is left to the browser rather than tracked here: a flag of our own would
  // stay stuck when compositionend never arrives, and that input could then never send again.
  const compositionEndedAtRef = useRef(Number.NEGATIVE_INFINITY);

  const onCompositionEnd = useCallback((event: ReactCompositionEvent<T>) => {
    compositionEndedAtRef.current = shouldArmCompositionGrace(event.data)
      ? event.timeStamp
      : Number.NEGATIVE_INFINITY;
  }, []);

  const isComposingKeyEvent = useCallback((event: ReactKeyboardEvent<T>) => {
    const nativeEvent = event.nativeEvent as KeyboardEvent | undefined;
    const reportedByBrowser = isImeCompositionKeyEvent({
      key: event.key,
      keyCode: nativeEvent?.keyCode,
      isComposing: nativeEvent?.isComposing,
    });
    if (reportedByBrowser) return true;
    return isWithinCompositionGrace(event.timeStamp, compositionEndedAtRef.current);
  }, []);

  const compositionHandlers = useMemo(() => ({ onCompositionEnd }), [onCompositionEnd]);

  return { compositionHandlers, isComposingKeyEvent };
}
