// 認証メッセージモーダルのprops型定義
// Props type definition for the authentication message modal
type AuthMessageModalProps = {
  isModalClosing: boolean;
  message: string | null;
  onHide: () => void;
};

// 認証処理の結果メッセージを表示するモーダルコンポーネント
// Modal component that displays result messages from authentication processes
export function AuthMessageModal({ isModalClosing, message, onHide }: AuthMessageModalProps) {
  return (
    <div
      id="messageModal"
      // messageがある場合にモーダルを開き、クローズ中はアニメーションクラスを付与する
      // Open the modal when message is present; add animation class while closing
      className={`modal ${message ? "is-open" : ""} ${isModalClosing ? "hide-animation" : ""}`}
      onClick={onHide}
    >
      {/* クリックイベントの伝播を止めてモーダル本体のクリックで閉じないようにする */}
      {/* Stop click propagation so clicking inside the modal doesn't close it */}
      <div className="modal-content" onClick={(event) => event.stopPropagation()}>
        <button className="close" type="button" onClick={onHide} aria-label="閉じる">
          &times;
        </button>
        <p id="modalMessage">{message}</p>
      </div>
    </div>
  );
}
