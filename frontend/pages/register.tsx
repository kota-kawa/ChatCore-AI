// 新規登録ページ（/register）。認証ゲートウェイ画面をそのまま表示する。
// Sign-up page (/register); simply renders the authentication gateway screen.
import AuthGatewayPage from "../components/auth/auth_gateway_page";

// 登録ページのメインコンポーネント
// Main component for the register page
export default function RegisterPage() {
  // 認証用ゲートウェイコンポーネントを描画する
  // Render the authentication gateway component
  return <AuthGatewayPage />;
}
