import { useCallback, useState } from "react";

import { copyTextToClipboard } from "../../scripts/chat/message_utils";

// コピーアクションボタンのprops型定義
// Props type definition for the copy action button
type CopyActionButtonProps = {
  getText: () => string;
};

// メッセージをクリップボードにコピーするアクションボタン（成功・失敗のフィードバックアニメーション付き）
// Action button to copy a message to the clipboard, with success/failure feedback animation
export function CopyActionButton({ getText }: CopyActionButtonProps) {
  // アイコンクラスとステータスクラスでコピー結果を視覚的に表現する
  // Visually represent the copy result using icon and status classes
  const [iconClass, setIconClass] = useState("bi-clipboard");
  const [statusClass, setStatusClass] = useState("");
  const [disabled, setDisabled] = useState(false);

  // コピーの実行と結果フィードバックを管理するコールバック
  // Callback that handles copying and manages result feedback
  const handleClick = useCallback(async () => {
    if (disabled) return;
    setDisabled(true);
    try {
      await copyTextToClipboard(getText());
      setIconClass("bi-check-lg");
      setStatusClass("copy-btn--success");
    } catch {
      setIconClass("bi-x-lg");
      setStatusClass("copy-btn--error");
    } finally {
      // 2秒後にアイコンを元の状態にリセットする
      // Reset the icon to its original state after 2 seconds
      window.setTimeout(() => {
        setIconClass("bi-clipboard");
        setStatusClass("");
        setDisabled(false);
      }, 2000);
    }
  }, [disabled, getText]);

  return (
    <button
      type="button"
      className={`copy-btn message-action-btn ${statusClass}`.trim()}
      aria-label="メッセージをコピー"
      data-tooltip="このメッセージをコピー"
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
