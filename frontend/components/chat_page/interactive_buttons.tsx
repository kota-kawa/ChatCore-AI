import { memo, useCallback, useState } from "react";
import { useHomePageChatContext } from "../../contexts/chat_page/home_page_context";
import type { InteractiveButtonsV1 } from "../../lib/chat_page/types";

// インタラクティブボタンのprops型定義
// Props type definition for interactive buttons
type Props = {
  buttons: InteractiveButtonsV1;
  messageId: string;
};

// AIが提示した選択肢ボタン（Yes/No または複数選択肢）をレンダリングするコンポーネント
// Component that renders choice buttons presented by the AI (Yes/No or multiple options)
function InteractiveButtonsComponent({ buttons, messageId }: Props) {
  const { handleSendMessage } = useHomePageChatContext();
  // いずれかのボタンが押されたら二重送信を防ぐためにフラグを立てる
  // Set flag to prevent double submission after any button is pressed
  const [hasResponded, setHasResponded] = useState(false);

  // ボタン選択時にメッセージを送信し、以後のボタンを無効化する
  // Send the selected option as a message and disable all buttons afterwards
  const handleSelect = useCallback(
    (text: string) => {
      if (hasResponded) return;
      setHasResponded(true);
      handleSendMessage(text);
    },
    [handleSendMessage, hasResponded]
  );

  return (
    <div className="interactive-buttons-container">
      <div className="interactive-buttons-question">{buttons.question}</div>
      <div className="interactive-buttons-actions">
        {/* Yes/No形式と複数選択肢形式を切り替える / Switch between Yes/No and multiple-option formats */}
        {buttons.type === "yes_no" ? (
          <>
            <button
              type="button"
              className="interactive-button primary"
              onClick={() => handleSelect("Yes")}
              disabled={hasResponded}
            >
              Yes
            </button>
            <button
              type="button"
              className="interactive-button secondary"
              onClick={() => handleSelect("No")}
              disabled={hasResponded}
            >
              No
            </button>
          </>
        ) : (
          buttons.options?.map((option, index) => (
            <button
              key={index}
              type="button"
              className={`interactive-button ${index === 0 ? "primary" : "secondary"}`}
              onClick={() => handleSelect(option)}
              disabled={hasResponded}
            >
              {option}
            </button>
          ))
        )}
      </div>
    </div>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const InteractiveButtons = memo(InteractiveButtonsComponent);
