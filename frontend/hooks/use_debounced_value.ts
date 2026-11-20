// 値の変化を delayMs だけ遅らせて返す hook。入力のたびに通信する検索で、打鍵ごとの取得を 1 回にまとめるために使う。
// Hook returning a value delayed by delayMs; used by searches so that a burst of keystrokes causes one fetch.
import { useEffect, useState } from "react";

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
