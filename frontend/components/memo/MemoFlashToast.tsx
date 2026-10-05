import type { FlashState } from "../../lib/memo/types";

// 画面下に固定で出す通知。スクロール位置に関係なく見え、一覧を押し下げない。
// 成功は role="status"（読み上げを邪魔しない）、失敗は role="alert"。操作（「元に戻す」）は 1 つだけ付けられる。
// A notice pinned to the bottom of the screen: visible wherever the page is scrolled and it never pushes the
// list down. Success is role="status" (polite), failure role="alert". It can carry one action ("Undo").
export function MemoFlashToast({ flash, onAction }: { flash: FlashState | null; onAction: () => void }) {
  if (!flash) return null;
  return (
    <div className={`memo-toast memo-toast--${flash.type}`} role={flash.type === "error" ? "alert" : "status"}>
      <span className="memo-toast__text">{flash.text}</span>
      {flash.action && (
        <button type="button" className="memo-toast__action" onClick={onAction}>
          {flash.action.label}
        </button>
      )}
    </div>
  );
}
