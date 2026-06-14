import { useRouter } from "next/router";
import { SeoHead } from "../../../SeoHead";

// 認証ゲートウェイページ専用のSEOヘッドコンポーネント（インデックス非対象）
// SEO head component dedicated to the auth gateway page (excluded from indexing)
export function AuthGatewayHead() {
  const router = useRouter();
  return (
    <SeoHead
      title="ログイン・新規登録 | Chat Core"
      description="Chat Coreのログイン・新規登録ページです。"
      canonicalPath={router.pathname}
      noindex
    />
  );
}
