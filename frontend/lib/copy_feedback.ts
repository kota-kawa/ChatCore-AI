// コピーボタンのフィードバック（アイコンをチェックマークに差し替えて戻す）に関わる共有定数。
// React フック（hooks/use_copy_feedback.ts）と本文中のコピーボタン（scripts/chat/message_copy_buttons.ts）の
// 両方から参照できるよう、React 非依存のここに置く。
//
// Shared constants for the copy-button feedback (swap the icon to a check mark, then revert).
// Kept React-free so both the hook (hooks/use_copy_feedback.ts) and the in-message copy buttons
// (scripts/chat/message_copy_buttons.ts) can import it.

// 成功／失敗アイコンを見せてから通常アイコンへ戻すまでの時間（ミリ秒）。全コピーボタンで共通。
// How long the success / failure icon stays before the normal icon returns. Shared by every copy button.
export const COPY_FEEDBACK_RESET_MS = 2000;

// アイドル／成功／失敗で使う bootstrap-icons のクラス名。
// bootstrap-icons class names used for the idle / success / failure states.
export const COPY_IDLE_ICON = "bi-clipboard";
export const COPY_SUCCESS_ICON = "bi-check-lg";
export const COPY_ERROR_ICON = "bi-x-lg";
