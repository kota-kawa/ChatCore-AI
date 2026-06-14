// 認証フローのステップ：メールアドレス入力 / 確認コード入力 / パスキー設定
// Authentication flow steps: email entry / verification code / passkey setup
export type AuthStep = "entry" | "code" | "passkey";
// メール認証フローの種別：ログイン / 新規登録 / 未開始
// Email authentication flow type: login / register / not started
export type EmailAuthFlow = "login" | "register" | null;
// パスキー設定時の認証プロバイダー：メール / Google / 未選択
// Authentication provider when setting up passkey: email / Google / not selected
export type PasskeySetupProvider = "email" | "google" | null;
