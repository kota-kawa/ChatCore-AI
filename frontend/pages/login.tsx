// ログインページ（/login）。認証用の共通コンポーネント AuthGatewayPage を描画するだけの薄いページ。
// The login page (/login): a thin page that just renders the shared AuthGatewayPage component.

import AuthGatewayPage from "../components/auth/auth_gateway_page";

// ログインページのメインコンポーネント
// Main component for the login page
export default function LoginPage() {
  // 認証用ゲートウェイコンポーネントを描画する
  // Render the authentication gateway component
  return <AuthGatewayPage />;
}
