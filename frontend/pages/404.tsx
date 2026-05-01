import { SeoHead } from "../components/SeoHead";

export default function NotFoundPage() {
  return (
    <>
      <SeoHead
        title="ページが見つかりません | Chat Core"
        description="お探しのページは存在しないか、移動・削除された可能性があります。"
        noindex
      />
      <main className="global-error-boundary" role="main">
        <div className="global-error-boundary__card">
          <h1>404 - ページが見つかりません</h1>
          <p>お探しのページは存在しないか、移動・削除された可能性があります。</p>
          <a href="/" className="cc-texture-btn cc-texture-btn--indigo">
            トップページへ戻る
          </a>
        </div>
      </main>
    </>
  );
}
