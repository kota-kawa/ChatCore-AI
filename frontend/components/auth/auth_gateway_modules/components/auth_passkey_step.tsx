import type { EmailAuthFlow, PasskeySetupProvider } from "../types";

type AuthPasskeyStepProps = {
  emailAuthFlow: EmailAuthFlow;
  passkeyPending: boolean;
  passkeySetupProvider: PasskeySetupProvider;
  onLater: () => void;
  onRegisterPasskey: () => void;
};

export function AuthPasskeyStep({
  emailAuthFlow,
  passkeyPending,
  passkeySetupProvider,
  onLater,
  onRegisterPasskey
}: AuthPasskeyStepProps) {
  return (
    <div className="passkey-panel">
      <p className="step-caption">
        {emailAuthFlow === "register"
          ? (
            passkeySetupProvider === "google"
              ? "Googleログインは完了しています。必要ならこの端末にPasskeyを追加してください。"
              : "アカウント作成は完了しています。必要ならこの端末にPasskeyを追加してください。"
          )
          : "この端末にPasskeyを保存すると、次回からメールコードなしで入れます。"}
      </p>
      <button
        type="button"
        className="passkey-btn"
        onClick={onRegisterPasskey}
        disabled={passkeyPending}
      >
        この端末にPasskeyを保存
      </button>
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
