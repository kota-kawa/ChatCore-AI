// アシスタントの回答から自動保存された記憶を知らせる小さな通知。「記憶しました：タイトル」と「取り消す」、記憶の画面へのリンクを出し、
// 取り消すと「取り消しました」に変わる。取り消しの状態は呼び出し側（hooks/chat_page/use_auto_saved_memories.ts）が持つ。
// chat_message_list.tsx から描画される。
// Small notices telling the user which memories were auto-saved from an assistant answer: "Remembered: title" with an
// undo button and a link to the memory screen, turning into "Undone" after an undo. The undo state is owned by the
// caller (hooks/chat_page/use_auto_saved_memories.ts). Rendered by chat_message_list.tsx.
import Link from "next/link";
import { memo, useCallback, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import type { AutoSavedMemory } from "../../lib/chat_page/auto_saved_memory_api";
import type { AutoSavedMemoryEntry } from "../../lib/chat_page/auto_saved_memory_state";

type Props = {
  entries: readonly AutoSavedMemoryEntry[];
  onUndo: (memory: AutoSavedMemory) => Promise<void>;
};

function AutoSavedMemoryNotice({ entry, onUndo }: { entry: AutoSavedMemoryEntry; onUndo: Props["onUndo"] }) {
  const { t } = useTranslation();
  // 押してから結果が届くまでの二重送信を防ぐ。 / Blocks a second press while the undo is in flight.
  const [undoing, setUndoing] = useState(false);
  const undone = entry.status === "undone";

  const handleUndo = useCallback(async () => {
    if (undoing) return;
    setUndoing(true);
    try {
      await onUndo(entry);
    } finally {
      setUndoing(false);
    }
  }, [entry, onUndo, undoing]);

  return (
    <li className="memory-notice" data-status={entry.status}>
      <div className="memory-notice__body" role="status">
        <i className={`bi ${undone ? "bi-arrow-counterclockwise" : "bi-bookmark-check"}`} aria-hidden="true"></i>
        {undone ? (
          <span className="memory-notice__text">{t("chat.memoryNotice.undone")}</span>
        ) : (
          <span className="memory-notice__text">
            <span className="memory-notice__label">{t("chat.memoryNotice.saved")}</span>
            <span className="memory-notice__title">{entry.title}</span>
          </span>
        )}
      </div>
      {undone ? null : (
        <div className="memory-notice__actions">
          <button
            type="button"
            className="memory-notice__undo"
            disabled={undoing}
            aria-label={t("chat.memoryNotice.undoLabel", { title: entry.title })}
            onClick={() => void handleUndo()}
          >
            {t("chat.memoryNotice.undo")}
          </button>
          <Link className="memory-notice__link" href="/memo?view=context">
            <span>{t("chat.memoryNotice.open")}</span>
            <i className="bi bi-arrow-right" aria-hidden="true"></i>
          </Link>
        </div>
      )}
    </li>
  );
}

// 1 件の回答から保存された記憶（最大 3 件）の一覧。
// The memories (up to three) saved from one answer.
function AutoSavedMemoryNoticesComponent({ entries, onUndo }: Props) {
  const { t } = useTranslation();
  if (entries.length === 0) return null;
  return (
    <ul className="memory-notices" aria-label={t("chat.memoryNotice.label")}>
      {entries.map((entry) => (
        <AutoSavedMemoryNotice key={entry.id} entry={entry} onUndo={onUndo} />
      ))}
    </ul>
  );
}

export const AutoSavedMemoryNotices = memo(AutoSavedMemoryNoticesComponent);
AutoSavedMemoryNotices.displayName = "AutoSavedMemoryNotices";
