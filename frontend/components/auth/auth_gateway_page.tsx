import { Outfit } from "next/font/google";
import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { ensureCsrfProtection } from "../../scripts/core/csrf";
import {
  authenticateWithPasskey,
  browserSupportsPasskeys,
  PasskeyCancelledError,
  registerPasskey
} from "../../scripts/core/passkeys";
import { fetchJson } from "../../scripts/core/runtime_validation";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { REDIRECT_DELAY_MS } from "./auth_gateway_modules/constants";
import { AuthCodeStep } from "./auth_gateway_modules/components/auth_code_step";
import { AuthEntryStep } from "./auth_gateway_modules/components/auth_entry_step";
import { AuthGatewayHead } from "./auth_gateway_modules/components/auth_gateway_head";
import { AuthMessageModal } from "./auth_gateway_modules/components/auth_message_modal";
import { AuthPasskeyStep } from "./auth_gateway_modules/components/auth_passkey_step";
import { LoadingSpinnerOverlay } from "./auth_gateway_modules/components/loading_spinner_overlay";
import { useModalMessage } from "./auth_gateway_modules/hooks/use_modal_message";
import { AuthGatewayGlobalStyles } from "./auth_gateway_modules/styles/auth_gateway_global_styles";
import type { AuthStep, EmailAuthFlow, PasskeySetupProvider } from "./auth_gateway_modules/types";
import { buildGoogleLoginUrl, getPostAuthRedirectPath, getSearchParams } from "./auth_gateway_modules/url_utils";

// 認証ページで使用するフォントの設定（Google Fonts）
// Font configuration for the auth page (Google Fonts)
const authHeadingFont = Outfit({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap"
});

// パスキー・Google・メール認証の3方式に対応した認証ゲートウェイページのメインコンポーネント
// Main component for the auth gateway page supporting passkey, Google, and email authentication
export default function AuthGatewayPage() {
  // 現在の認証ステップ（エントリー → コード入力 → パスキー設定）
  // Current authentication step (entry → code input → passkey setup)
  const [step, setStep] = useState<AuthStep>("entry");
  const [email, setEmail] = useState("");
  const [authCode, setAuthCode] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  // 各非同期処理の進行中フラグ
  // Flags indicating each async operation is in progress
  const [sendingCode, setSendingCode] = useState(false);
  const [verifyingCode, setVerifyingCode] = useState(false);
  const [redirectingAfterAuth, setRedirectingAfterAuth] = useState(false);
  const [passkeyPending, setPasskeyPending] = useState(false);
  const [supportsPasskeys, setSupportsPasskeys] = useState(false);
  // メール認証フローの種別（ログイン / 新規登録）とパスキープロバイダー
  // Email auth flow type (login / register) and passkey provider
  const [emailAuthFlow, setEmailAuthFlow] = useState<EmailAuthFlow>(null);
  const [passkeySetupProvider, setPasskeySetupProvider] = useState<PasskeySetupProvider>(null);

  const {
    hideModal,
    isModalClosing,
    modalMessage,
    showModalMessage
  } = useModalMessage();

  const redirectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // タイマーをクリアしてrefをリセットするユーティリティ
  // Utility to clear a timer and reset its ref
  const clearTimer = (timerRef: MutableRefObject<ReturnType<typeof setTimeout> | null>) => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  // 認証完了後に指定パスへ遅延リダイレクトをスケジュールする
  // Schedule a delayed redirect to the specified path after authentication completes
  const scheduleRedirect = (targetPath: string = getPostAuthRedirectPath()) => {
    clearTimer(redirectTimerRef);
    setRedirectingAfterAuth(true);
    redirectTimerRef.current = setTimeout(() => {
      window.location.href = targetPath;
    }, REDIRECT_DELAY_MS);
  };

  // 現在の処理状態に応じてローディングオーバーレイのメッセージを決定する
  // Determine the loading overlay message based on the current processing state
  const loadingState = (() => {
    if (redirectingAfterAuth) {
      return {
        message: "画面を準備しています。まもなく移動します。",
        title: emailAuthFlow === "register" ? "アカウントを作成しました" : "ログインしています"
      };
    }
    if (verifyingCode) {
      return {
        message: "認証コードを照合し、ログイン情報を準備しています。",
        title: "認証コードを確認中"
      };
    }
    if (sendingCode) {
      return {
        message: "メールに届く6桁のコードを確認してください。",
        title: "認証メールを送信中"
      };
    }
    if (passkeyPending) {
      return {
        message: "ブラウザまたは端末の案内に従ってください。",
        title: "Passkeyを確認中"
      };
    }
    return null;
  })();

  // マウント時にCSRF保護を有効化し、パスキーサポートを確認する
  // On mount, enable CSRF protection and check for passkey support
  useEffect(() => {
    ensureCsrfProtection();
    document.body.classList.add("auth-page");
    setSupportsPasskeys(browserSupportsPasskeys());
    return () => {
      document.body.classList.remove("auth-page");
      clearTimer(redirectTimerRef);
    };
  }, []);

  // マウント時にログイン済みか確認し、パスキー設定が必要な場合はそのステップへ遷移する
  // On mount, check if already logged in and transition to passkey setup step if needed
  useEffect(() => {
    let cancelled = false;

    const checkLoginState = async () => {
      const query = getSearchParams();
      const nextPath = getPostAuthRedirectPath();
      const supportsPasskeysNow = browserSupportsPasskeys();
      const shouldOfferPasskeySetup = supportsPasskeysNow && query.get("offer_passkey_setup") === "1";
      const queryFlow = query.get("flow") === "register" ? "register" : "login";
      const provider = query.get("provider") === "google" ? "google" : "email";

      try {
        const response = await resilientFetch("/api/current_user", {
          credentials: "same-origin"
        });
        const data = await response.json();

        if (!cancelled && data.logged_in) {
          if (shouldOfferPasskeySetup) {
            // パスキー設定ステップを表示する
            // Show the passkey setup step
            setEmailAuthFlow(queryFlow);
            setPasskeySetupProvider(provider);
            setStep("passkey");
            showModalMessage(
              provider === "google"
                ? "Googleでログインしました。必要ならこのままPasskeyを追加できます。"
                : "アカウントを作成しました。必要ならこのままPasskeyを追加できます。"
            );
            return;
          }
          window.location.href = nextPath;
        }
      } catch (error) {
        console.error("Error checking login state:", error);
      }
    };

    const checkTimerId = window.setTimeout(() => {
      void checkLoginState();
    }, 0);

    return () => {
      cancelled = true;
      clearTimeout(checkTimerId);
    };
  }, []);

  // メールアドレスに認証コードを送信する処理
  // Handle sending the authentication code to the email address
  const handleSendCode = async () => {
    const trimmedEmail = email.trim();
    setErrorMessage("");
    setEmailAuthFlow(null);
    setPasskeySetupProvider(null);
    setRedirectingAfterAuth(false);

    if (!trimmedEmail) {
      setErrorMessage("メールアドレスを入力してください。");
      return;
    }

    setSendingCode(true);
    try {
      const { payload: data } = await fetchJson<Record<string, unknown>>(
        "/api/auth/send_email_code",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: trimmedEmail })
        },
        resilientFetch
      );

      if (data.status === "success") {
        setStep("code");
        showModalMessage("認証コードを送信しました。メールを確認してください。");
      } else {
        setErrorMessage(typeof data.error === "string" ? data.error : "認証コード送信に失敗しました。");
      }
    } catch (error) {
      console.error("Error sending email auth code:", error);
      setErrorMessage("サーバーエラーが発生しました。");
    } finally {
      setSendingCode(false);
    }
  };

  // 入力された認証コードをサーバーで検証する処理
  // Handle verifying the entered authentication code on the server
  const handleVerifyCode = async () => {
    const trimmedCode = authCode.trim();
    setErrorMessage("");
    setRedirectingAfterAuth(false);

    if (!trimmedCode) {
      setErrorMessage("認証コードを入力してください。");
      return;
    }

    setVerifyingCode(true);
    try {
      const { payload: data } = await fetchJson<Record<string, unknown>>(
        "/api/auth/verify_email_code",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ authCode: trimmedCode })
        },
        resilientFetch
      );

      if (data.status === "success") {
        const flow = data.flow === "register" ? "register" : "login";
        const shouldOfferPasskeySetup = flow === "register" && supportsPasskeys && data.offer_passkey_setup === true;
        setEmailAuthFlow(flow);
        setPasskeySetupProvider("email");

        if (shouldOfferPasskeySetup) {
          // 新規登録かつパスキー対応デバイスの場合はパスキー設定へ進む
          // Proceed to passkey setup for new registrations on supported devices
          setStep("passkey");
          showModalMessage("アカウントを作成しました。必要ならこのままPasskeyを追加できます。");
        } else {
          scheduleRedirect();
        }
      } else {
        setErrorMessage(typeof data.error === "string" ? data.error : "認証に失敗しました。");
      }
    } catch (error) {
      console.error("Error verifying email auth code:", error);
      setErrorMessage("サーバーエラーが発生しました。");
    } finally {
      setVerifyingCode(false);
    }
  };

  // パスキーを使ってログインする処理
  // Handle authentication using a passkey
  const handlePasskeyLogin = async () => {
    setErrorMessage("");
    setRedirectingAfterAuth(false);
    setPasskeyPending(true);
    try {
      await authenticateWithPasskey();
      window.location.href = getPostAuthRedirectPath();
    } catch (error) {
      // ユーザーがキャンセルした場合はエラー表示しない
      // Don't show an error when the user cancelled
      if (error instanceof PasskeyCancelledError) {
        return;
      }
      setErrorMessage(error instanceof Error ? error.message : "Passkey認証に失敗しました。");
    } finally {
      setPasskeyPending(false);
    }
  };

  // パスキーをデバイスに登録する処理
  // Handle registering a passkey on the device
  const handlePasskeyRegistration = async () => {
    setErrorMessage("");
    setRedirectingAfterAuth(false);
    setPasskeyPending(true);
    try {
      await registerPasskey();
      showModalMessage("Passkeyを保存しました。");
      scheduleRedirect();
    } catch (error) {
      if (error instanceof PasskeyCancelledError) {
        return;
      }
      setErrorMessage(error instanceof Error ? error.message : "Passkey登録に失敗しました。");
    } finally {
      setPasskeyPending(false);
    }
  };

  return (
    <>
      <AuthGatewayHead />

      <div className="auth-page-root">
        <div className="chat-background" />

        <div className="auth-container">
          {/* 処理中のローディングオーバーレイ / Loading overlay during processing */}
          <LoadingSpinnerOverlay
            message={loadingState?.message}
            title={loadingState?.title}
            visible={loadingState !== null}
          />

          {/* ステップに応じてアイコンを切り替える / Switch icon based on current step */}
          <div className="bot-icon">{step === "passkey" ? "🔐" : supportsPasskeys ? "🌿" : "✉️"}</div>
          <h1 className="title">アカウントに続ける</h1>
          <p className="subtitle">
            Passkey、Google、メール認証に対応しています。
            <br />
            初めての場合はメール認証後にアカウントを作成します。
          </p>

          <div className="error-message" role="alert">{errorMessage}</div>

          {/* エントリーステップ：ログイン方法の選択 / Entry step: select login method */}
          {step === "entry" ? (
            <AuthEntryStep
              email={email}
              passkeyPending={passkeyPending}
              sendingCode={sendingCode}
              supportsPasskeys={supportsPasskeys}
              onEmailChange={setEmail}
              onGoogleLogin={() => {
                window.location.href = buildGoogleLoginUrl();
              }}
              onPasskeyLogin={() => {
                void handlePasskeyLogin();
              }}
              onSendCode={() => {
                void handleSendCode();
              }}
            />
          ) : null}

          {/* コードステップ：認証コードの入力 / Code step: enter authentication code */}
          {step === "code" ? (
            <AuthCodeStep
              authCode={authCode}
              verifyingCode={verifyingCode}
              onAuthCodeChange={setAuthCode}
              onBack={() => {
                setAuthCode("");
                setErrorMessage("");
                setStep("entry");
              }}
              onVerifyCode={() => {
                void handleVerifyCode();
              }}
            />
          ) : null}

          {/* パスキーステップ：パスキーの登録 / Passkey step: register passkey */}
          {step === "passkey" ? (
            <AuthPasskeyStep
              emailAuthFlow={emailAuthFlow}
              passkeyPending={passkeyPending}
              passkeySetupProvider={passkeySetupProvider}
              onLater={() => scheduleRedirect()}
              onRegisterPasskey={() => {
                void handlePasskeyRegistration();
              }}
            />
          ) : null}
        </div>

        <AuthMessageModal
          isModalClosing={isModalClosing}
          message={modalMessage}
          onHide={hideModal}
        />
      </div>

      <AuthGatewayGlobalStyles fontFamily={authHeadingFont.style.fontFamily} />
    </>
  );
}
