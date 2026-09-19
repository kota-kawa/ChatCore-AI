import { ModalShell } from "../../../ui/modal_shell";
import { useTranslation } from "../../../../contexts/locale_context";

// 認証メッセージモーダルのprops型定義
// Props type definition for the authentication message modal
type AuthMessageModalProps = {
  isModalClosing: boolean;
  message: string | null;
  onHide: () => void;
};

// 認証処理の結果メッセージを表示するモーダルコンポーネント
// 共通のModalShell（role="dialog"・フォーカストラップ・Escape/背景クリックでの閉じる操作）に乗せつつ、
// 見た目は既存の.modal-content/.close/#modalMessageをそのまま流用する。
// Modal component that displays result messages from authentication processes.
// Rides on the shared ModalShell (role="dialog", focus trap, Escape/backdrop close) while
// reusing the existing .modal-content/.close/#modalMessage visuals as-is.
export function AuthMessageModal({ isModalClosing, message, onHide }: AuthMessageModalProps) {
  const { t } = useTranslation();
  return (
    <ModalShell
      isOpen={Boolean(message)}
      onClose={onHide}
      id="messageModal"
      // isModalClosing中は閉じるアニメーション用クラスを維持する（既存の hide-animation と同じ仕組み）
      // Keep the closing-animation class while isModalClosing is true (same mechanism as the old hide-animation)
      className={`auth-message-modal${isModalClosing ? " hide-animation" : ""}`}
      labelledBy="modalMessage"
      initialFocusSelector=".close"
    >
      {/* クリックイベントの伝播を止めてモーダル本体のクリックで閉じないようにする */}
      {/* Stop click propagation so clicking inside the modal doesn't close it */}
      <div className="modal-content" onClick={(event) => event.stopPropagation()}>
        <button className="close cc-press" type="button" onClick={onHide} aria-label={t("common.close")}>
          &times;
        </button>
        <p id="modalMessage">{message}</p>
      </div>
    </ModalShell>
  );
}
