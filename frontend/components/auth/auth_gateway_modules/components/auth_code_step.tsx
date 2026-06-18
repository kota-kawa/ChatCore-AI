// メール認証コード入力ステップのprops型定義
// Props type definition for the email authentication code input step
type AuthCodeStepProps = {
  authCode: string;
  verifyingCode: boolean;
  onAuthCodeChange: (value: string) => void;
  onBack: () => void;
  onVerifyCode: () => void;
};

// メールに届いた認証コードを入力・送信するUIコンポーネント
// UI component for entering and submitting the authentication code received by email
export function AuthCodeStep({
  authCode,
  verifyingCode,
  onAuthCodeChange,
  onBack,
  onVerifyCode
}: AuthCodeStepProps) {
  return (
    <div className="code-panel">
      <p className="step-caption">メールに届いた認証コードを入力してください。</p>
      <label htmlFor="authCode" className="email-label">認証コード</label>
      <input
        type="text"
        id="authCode"
        name="authCode"
        required
        className="email-input"
        placeholder="認証コードを入力"
        value={authCode}
        onChange={(event) => onAuthCodeChange(event.target.value)}
        autoComplete="one-time-code"
        disabled={verifyingCode}
      />
      {/* 認証コードを送信するボタン / Button to submit the authentication code */}
      <button
        type="button"
        className="submit-btn cc-press"
        onClick={onVerifyCode}
        disabled={verifyingCode}
      >
        {verifyingCode ? "認証コードを確認中..." : "認証して続ける"}
      </button>
      {/* 認証中のステータス表示 / Status display while verifying */}
      {verifyingCode ? (
        <div className="code-status" role="status" aria-live="polite">
          <span className="code-status-pulse" aria-hidden="true" />
          <span>ログインの準備をしています。このままお待ちください。</span>
        </div>
      ) : null}
      {/* メールアドレス入力画面に戻るボタン / Button to go back to email input */}
      <button
        type="button"
        className="ghost-btn cc-press"
        onClick={onBack}
        disabled={verifyingCode}
      >
        戻る
      </button>
    </div>
  );
}
