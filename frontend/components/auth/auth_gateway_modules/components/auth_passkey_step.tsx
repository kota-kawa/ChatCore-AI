import type { EmailAuthFlow, PasskeySetupProvider } from "../types";
import { useTranslation } from "../../../../contexts/locale_context";

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
  const { locale, t } = useTranslation();
  return (
    <div className="passkey-panel">
      {/* 認証フローとプロバイダーに応じてキャプションを切り替える */}
      {/* Switch caption based on auth flow and provider */}
      <p className="step-caption">
        {emailAuthFlow === "register"
          ? (
            passkeySetupProvider === "google"
              ? (locale === "en" ? "Google sign-in is complete. You can add a passkey to this device now." : "Googleログインは完了しています。必要ならこの端末にPasskeyを追加してください。")
              : (locale === "en" ? "Your account is ready. You can add a passkey to this device now." : "アカウント作成は完了しています。必要ならこの端末にPasskeyを追加してください。")
          )
          : (locale === "en" ? "Save a passkey on this device to sign in without an email code next time." : "この端末にPasskeyを保存すると、次回からメールコードなしで入れます。")}
      </p>
      {/* パスキー登録ボタン / Passkey registration button */}
      <button
        type="button"
        className="passkey-btn cc-press"
        onClick={onRegisterPasskey}
        disabled={passkeyPending}
      >
        {t("auth.passkeyRegister")}
      </button>
      {/* パスキー設定をスキップするボタン / Button to skip passkey setup */}
      <button
        type="button"
        className="ghost-btn cc-press"
        onClick={onLater}
      >
        {t("auth.passkeySkip")}
      </button>
    </div>
  );
}
