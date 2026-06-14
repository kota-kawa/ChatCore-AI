import type { EmailAuthFlow, PasskeySetupProvider } from "../types";

// パスキー設定ステップのprops型定義
// Props type definition for the passkey setup step
type AuthPasskeyStepProps = {
  emailAuthFlow: EmailAuthFlow;
  passkeyPending: boolean;
  passkeySetupProvider: PasskeySetupProvider;
  onLater: () => void;
  onRegisterPasskey: () => void;
};

// パスキーをデバイスに登録するよう促すUIコンポーネント
// UI component that prompts the user to register a passkey on their device
export function AuthPasskeyStep({
  emailAuthFlow,
  passkeyPending,
  passkeySetupProvider,
  onLater,
  onRegisterPasskey
}: AuthPasskeyStepProps) {
  return (
    <div className="passkey-panel">
      {/* 認証フローとプロバイダーに応じてキャプションを切り替える */}
      {/* Switch caption based on auth flow and provider */}
      <p className="step-caption">
        {emailAuthFlow === "register"
          ? (
            passkeySetupProvider === "google"
              ? "Googleログインは完了しています。必要ならこの端末にPasskeyを追加してください。"
              : "アカウント作成は完了しています。必要ならこの端末にPasskeyを追加してください。"
          )
          : "この端末にPasskeyを保存すると、次回からメールコードなしで入れます。"}
      </p>
      {/* パスキー登録ボタン / Passkey registration button */}
      <button
        type="button"
        className="passkey-btn"
        onClick={onRegisterPasskey}
        disabled={passkeyPending}
      >
        この端末にPasskeyを保存
      </button>
      {/* パスキー設定をスキップするボタン / Button to skip passkey setup */}
      <button
        type="button"
        className="ghost-btn"
        onClick={onLater}
      >
        後で設定する
      </button>
    </div>
  );
}
