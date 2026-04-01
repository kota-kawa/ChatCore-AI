import { useCallback, useState } from "react";

import { copyTextToClipboard } from "../../scripts/chat/message_utils";

type CopyActionButtonProps = {
  getText: () => string;
};

export function CopyActionButton({ getText }: CopyActionButtonProps) {
  const [iconClass, setIconClass] = useState("bi-clipboard");
  const [statusClass, setStatusClass] = useState("");

  const handleClick = useCallback(async () => {
    try {
      await copyTextToClipboard(getText());
      setIconClass("bi-check-lg");
      setStatusClass("copy-btn--success");
    } catch {
      setIconClass("bi-x-lg");
      setStatusClass("copy-btn--error");
    } finally {
      window.setTimeout(() => {
        setIconClass("bi-clipboard");
        setStatusClass("");
      }, 2000);
    }
  }, [getText]);

  return (
    <button
      type="button"
      className={`copy-btn message-action-btn ${statusClass}`.trim()}
      aria-label="メッセージをコピー"
      data-tooltip="このメッセージをコピー"
      data-tooltip-placement="top"
      onClick={() => {
        void handleClick();
      }}
    >
      <i className={`bi ${iconClass}`}></i>
    </button>
  );
}
