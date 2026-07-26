import { useCallback, useEffect, useState } from "react";

import {
  DEFAULT_READING_SIZE,
  readReadingSize,
  writeReadingSize,
  type ReadingSize
} from "../../scripts/prompt_share/storage";

// 詳細モーダルの本文表示サイズを保持し、選択をlocalStorageへ永続化する
// Keeps the detail modal's reading size and persists the choice to localStorage
export function usePromptReadingSize() {
  const [readingSize, setReadingSize] = useState<ReadingSize>(DEFAULT_READING_SIZE);

  // SSRとの初回描画差分を避けるため、保存値の復元はマウント後に行う
  // Restore the stored value after mount so the first render still matches SSR output
  useEffect(() => {
    setReadingSize(readReadingSize());
  }, []);

  const changeReadingSize = useCallback((size: ReadingSize) => {
    setReadingSize(size);
    writeReadingSize(size);
  }, []);

  return { readingSize, changeReadingSize };
}
