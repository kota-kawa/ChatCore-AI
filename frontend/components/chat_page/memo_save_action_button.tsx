import { useCallback, useState } from "react";

import { isRecord } from "../../lib/utils";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { extractApiErrorMessage, readJsonBodySafe } from "../../scripts/core/runtime_validation";

// メモ保存ボタンのprops型定義
// Props type definition for the memo save action button
type MemoSaveActionButtonProps = {
  getText: () => string;
};

// AIの回答をメモとして保存するアクションボタン（保存状態のフィードバックアニメーション付き）
// Action button to save an AI response as a memo, with feedback animation for save state
export function MemoSaveActionButton({ getText }: MemoSaveActionButtonProps) {
  // アイコンとバリアントクラスで保存状態を視覚的に表現する
  // Visually represent the save state using icon and variant classes
  const [iconClass, setIconClass] = useState("bi-bookmark-plus");
  const [variantClass, setVariantClass] = useState("");
  const [disabled, setDisabled] = useState(false);

  // メモ保存APIの呼び出しと結果フィードバックを管理するコールバック
  // Callback that calls the memo save API and manages result feedback
  const handleClick = useCallback(async () => {
    if (disabled) return;

    const aiResponse = getText().trim();
    // テキストが空の場合はエラーフィードバックを表示する
    // Show error feedback if the text is empty
    if (!aiResponse) {
      setIconClass("bi-x-lg");
      setVariantClass("memo-save-btn--error");
      window.setTimeout(() => {
        setIconClass("bi-bookmark-plus");
        setVariantClass("");
      }, 2000);
      return;
    }

    setDisabled(true);
    setVariantClass("memo-save-btn--loading");
    setIconClass("bi-hourglass-split");

    try {
      // メモ保存APIにAI回答をPOSTする
      // POST the AI response to the memo save API
      const response = await resilientFetch("/memo/api", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          ai_response: aiResponse,
          title: "",
        }),
      });

      const rawPayload = await readJsonBodySafe(response);
      const status = isRecord(rawPayload) ? rawPayload.status : undefined;

      if (!response.ok || status === "fail") {
        throw new Error(extractApiErrorMessage(rawPayload, "メモの保存に失敗しました。", response.status));
      }

      setIconClass("bi-check-lg");
      setVariantClass("memo-save-btn--success");
    } catch {
      setIconClass("bi-x-lg");
      setVariantClass("memo-save-btn--error");
    } finally {
      setDisabled(false);
      // 2秒後にアイコンを元の状態にリセットする
      // Reset icon to original state after 2 seconds
      window.setTimeout(() => {
        setIconClass("bi-bookmark-plus");
        setVariantClass("");
      }, 2000);
    }
  }, [disabled, getText]);

  return (
    <button
      type="button"
      className={`memo-save-btn message-action-btn ${variantClass}`.trim()}
      aria-label="メモに保存"
      data-tooltip="この回答をメモに保存"
      data-tooltip-placement="top"
      disabled={disabled}
      onClick={() => {
        void handleClick();
      }}
    >
      <i className={`bi ${iconClass}`}></i>
    </button>
  );
}
