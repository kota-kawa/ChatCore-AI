import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";

import { SeoHead } from "../../components/SeoHead";
import "../../scripts/core/csrf";
import {
  decideMcpOAuthConsent,
  loadMcpOAuthConsent,
  McpOAuthApiError
} from "../../scripts/user/settings/api";
import { MCP_PROMPTS_WRITE_SCOPE_LABEL } from "../../scripts/user/settings/constants";
import type { McpOAuthConsent } from "../../scripts/user/settings/types";

// MCP OAuth の認可画面。外部AIサービスに投稿権限を渡す前に、ユーザーへ接続先を明示する。
// MCP OAuth authorization page that clearly identifies the external AI service before granting publishing access.
export default function McpOAuthAuthorizePage() {
  const router = useRouter();
  const request = useMemo(() => {
    const raw = router.query.request;
    return typeof raw === "string" ? raw : "";
  }, [router.query.request]);
  const [consent, setConsent] = useState<McpOAuthConsent | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!router.isReady) {
      return;
    }
    if (!request) {
      setErrorMessage("認可リクエストが見つかりません。AIサービスからもう一度接続してください。");
      return;
    }

    let cancelled = false;
    const loadConsent = async () => {
      setConsent(null);
      setErrorMessage("");
      try {
        const nextConsent = await loadMcpOAuthConsent(request);
        if (!cancelled) {
          setConsent(nextConsent);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (error instanceof McpOAuthApiError && error.status === 401) {
          const nextPath = router.asPath.startsWith("/") ? router.asPath : "/oauth/authorize";
          window.location.replace(`/login?next=${encodeURIComponent(nextPath)}`);
          return;
        }
        setErrorMessage(error instanceof Error ? error.message : "認可情報の取得に失敗しました。");
      }
    };

    void loadConsent();
    return () => {
      cancelled = true;
    };
  }, [request, router]);

  const decide = async (decision: "approve" | "deny") => {
    if (!request || submitting) {
      return;
    }

    setSubmitting(true);
    setErrorMessage("");
    try {
      const redirectUrl = await decideMcpOAuthConsent(request, decision);
      window.location.assign(redirectUrl);
    } catch (error) {
      if (error instanceof McpOAuthApiError && error.status === 401) {
        const nextPath = router.asPath.startsWith("/") ? router.asPath : "/oauth/authorize";
        window.location.replace(`/login?next=${encodeURIComponent(nextPath)}`);
        return;
      }
      setErrorMessage(error instanceof Error ? error.message : "認可操作に失敗しました。");
      setSubmitting(false);
    }
  };

  return (
    <>
      <SeoHead
        title="AIサービス連携の確認 | Chat Core"
        description="外部AIサービスへの投稿権限を確認します。"
        canonicalPath="/oauth/authorize"
        noindex
      />

      <main className="user-settings-page" style={{ minHeight: "100vh", padding: "3rem 1rem" }}>
        <section className="settings-card" style={{ maxWidth: "640px", margin: "0 auto" }} aria-labelledby="oauth-authorize-title">
          <h1 id="oauth-authorize-title">AIサービス連携の確認</h1>
          {errorMessage ? (
            <p className="settings-inline-feedback settings-inline-feedback--error" role="alert">
              <i className="settings-inline-feedback__icon bi bi-exclamation-circle-fill" aria-hidden="true"></i>
              {errorMessage}
            </p>
          ) : null}

          {!consent && !errorMessage ? <p aria-live="polite">連携情報を確認しています。</p> : null}

          {consent ? (
            <div className="security-stack">
              <div className="security-panel">
                <p className="security-panel__description">
                  次のAIサービスに、あなたの名前で公開プロンプトを投稿する権限を付与します。
                </p>
                <dl>
                  <dt>AIサービス</dt>
                  <dd>{consent.client_name}</dd>
                  <dt>クライアントID</dt>
                  <dd>{consent.client_id}</dd>
                  <dt>接続元</dt>
                  <dd>{consent.client_host}</dd>
                  <dt>戻り先</dt>
                  <dd>{consent.redirect_host}</dd>
                  <dt>許可する操作</dt>
                  <dd>{MCP_PROMPTS_WRITE_SCOPE_LABEL}（{consent.scope}）</dd>
                </dl>
                {consent.localhost_warning ? (
                  <p className="settings-inline-feedback settings-inline-feedback--error" role="alert">
                    <i className="settings-inline-feedback__icon bi bi-exclamation-triangle-fill" aria-hidden="true"></i>
                    この連携はローカル環境に戻ります。信頼できるAIサービスであることを確認してください。
                  </p>
                ) : null}
              </div>
              <div className="button-group">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={submitting}
                  onClick={() => {
                    void decide("deny");
                  }}
                >
                  拒否する
                </button>
                <button
                  type="button"
                  className="primary-button"
                  disabled={submitting}
                  onClick={() => {
                    void decide("approve");
                  }}
                >
                  {submitting ? "処理中..." : "許可して接続"}
                </button>
              </div>
            </div>
          ) : null}
        </section>
      </main>
    </>
  );
}
