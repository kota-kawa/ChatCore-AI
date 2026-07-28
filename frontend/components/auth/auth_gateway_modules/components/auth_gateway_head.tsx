import { useRouter } from "next/router";
import { SeoHead } from "../../../SeoHead";
import { useTranslation } from "../../../../contexts/locale_context";

// 認証ゲートウェイページ専用のSEOヘッドコンポーネント（インデックス非対象）
// SEO head component dedicated to the auth gateway page (excluded from indexing)
export function AuthGatewayHead() {
  const router = useRouter();
  const { t } = useTranslation();
  return (
    <SeoHead
      title={t("auth.title")}
      description={t("auth.description")}
      canonicalPath={router.pathname}
      noindex
    />
  );
}
