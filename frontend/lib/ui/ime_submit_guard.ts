// IME変換確定のEnterを送信と誤認しないためのガード
// Guard that keeps the Enter which confirms an IME conversion from being read as "send"
import { useCallback, useMemo, useRef } from "react";
import type { CompositionEvent as ReactCompositionEvent, KeyboardEvent as ReactKeyboardEvent } from "react";

// Safari（macOS）は変換確定のEnterで compositionend を keydown より先に発火させるため、
// keydown 時点では isComposing が false になっている。同一キー入力から生まれた2つの
// イベントの間隔はミリ秒未満なので、この猶予内のEnterは変換確定として扱う。
// Safari on macOS fires compositionend before the keydown of the very same Enter press, so
// isComposing is already false by the time the key handler runs. Both events come from one
// physical key press and land within a millisecond of each other, so an Enter inside this
// grace window is treated as the confirmation, not as a send.
const COMPOSITION_END_GRACE_MS = 50;

// 変換中の keydown に対してブラウザが返す値。Chrome/Edge は keyCode 229、
// Firefox は key === "Process" を返す。
// Values browsers report for a keydown that belongs to an in-flight conversion:
// Chrome/Edge use keyCode 229, Firefox uses key === "Process".
const IME_KEY_CODE = 229;
const IME_KEY_NAME = "Process";

export function isImeCompositionKeyEvent<T>(event: ReactKeyboardEvent<T>): boolean {
  const nativeEvent = event.nativeEvent as KeyboardEvent | undefined;
  if (nativeEvent?.isComposing) return true;
  if (nativeEvent?.keyCode === IME_KEY_CODE) return true;
  return event.key === IME_KEY_NAME;
}

export type ImeSubmitGuard<T> = {
  // textarea / input にそのまま展開する composition ハンドラ
  // Composition handlers to spread onto the textarea / input
  compositionHandlers: {
    onCompositionStart: (event: ReactCompositionEvent<T>) => void;
    onCompositionEnd: (event: ReactCompositionEvent<T>) => void;
  };
  // 変換に属するキー入力なら true。送信ハンドラの先頭で弾く用途。
  // True when the key press belongs to a conversion; bail out of the submit handler on true.
  isComposingKeyEvent: (event: ReactKeyboardEvent<T>) => boolean;
};

export function useImeSubmitGuard<T = HTMLTextAreaElement>(): ImeSubmitGuard<T> {
  const isComposingRef = useRef(false);
  const compositionEndedAtRef = useRef(Number.NEGATIVE_INFINITY);

  const onCompositionStart = useCallback(() => {
    isComposingRef.current = true;
  }, []);

  const onCompositionEnd = useCallback((event: ReactCompositionEvent<T>) => {
    isComposingRef.current = false;
    compositionEndedAtRef.current = event.timeStamp;
  }, []);

  const isComposingKeyEvent = useCallback((event: ReactKeyboardEvent<T>) => {
    if (isComposingRef.current) return true;
    if (isImeCompositionKeyEvent(event)) return true;
    return event.timeStamp - compositionEndedAtRef.current < COMPOSITION_END_GRACE_MS;
  }, []);

  const compositionHandlers = useMemo(
    () => ({ onCompositionStart, onCompositionEnd }),
    [onCompositionEnd, onCompositionStart],
  );

  return { compositionHandlers, isComposingKeyEvent };
}
