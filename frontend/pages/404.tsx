import { SeoHead } from "../components/SeoHead";
import { useTranslation } from "../contexts/locale_context";

// 404エラーページコンポーネント（検索エンジンにインデックスさせない）
// 404 error page component (excluded from search engine indexing)
export default function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <>
      <SeoHead
        title={t("notFound.title")}
        description={t("notFound.description")}
        noindex
      />
      <main className="global-error-boundary" role="main">
        <div className="global-error-boundary__card">
          <h1>{t("notFound.heading")}</h1>
          <p>{t("notFound.description")}</p>
          {/* トップページへの導線 / Link back to the top page */}
          <a href="/" className="cc-texture-btn cc-texture-btn--indigo cc-press">
            {t("notFound.backHome")}
          </a>
        </div>
      </main>
    </>
  );
}
