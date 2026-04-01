import { useCallback, useState } from "react";

import { extractApiErrorMessage, readJsonBodySafe } from "../../scripts/core/runtime_validation";

type MemoSaveActionButtonProps = {
  getText: () => string;
};

export function MemoSaveActionButton({ getText }: MemoSaveActionButtonProps) {
  const [iconClass, setIconClass] = useState("bi-bookmark-plus");
  const [variantClass, setVariantClass] = useState("");
  const [disabled, setDisabled] = useState(false);

  const handleClick = useCallback(async () => {
    if (disabled) return;

    const aiResponse = getText().trim();
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
      const response = await fetch("/memo/api", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          input_content: "",
          ai_response: aiResponse,
          title: "",
          tags: "",
        }),
      });

      const rawPayload = await readJsonBodySafe(response);
      const status =
        rawPayload && typeof rawPayload === "object" && "status" in rawPayload
          ? (rawPayload as { status?: unknown }).status
          : undefined;

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
