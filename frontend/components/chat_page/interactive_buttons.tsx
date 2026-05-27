import { memo, useCallback, useState } from "react";
import { useHomePageChatContext } from "../../contexts/chat_page/home_page_context";
import type { InteractiveButtonsV1 } from "../../lib/chat_page/types";

type Props = {
  buttons: InteractiveButtonsV1;
  messageId: string;
};

function InteractiveButtonsComponent({ buttons, messageId }: Props) {
  const { handleSendMessage } = useHomePageChatContext();
  const [hasResponded, setHasResponded] = useState(false);

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

export const InteractiveButtons = memo(InteractiveButtonsComponent);
